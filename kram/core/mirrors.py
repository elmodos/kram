"""Mirrors of a repository, and how fast they are. No Qt, no libdnf5.

Fedora's own repositories and RPM Fusion do not name a server: they name a *metalink*, a small XML file that lists
the mirrors (~20 of them, nearest first by the service's idea of "near"). libdnf5 takes that list and downloads from
the first mirrors that answer. When the first ones are slow, nothing says so: that is what "Mirrors…" is for. Kram
fetches the same list, measures every mirror and lets the user pin one: the helper writes its address as the
repository's `baseurl` and empties the `metalink` (kram_helper.set_mirrors).

A speed test has two parts, because a mirror that answers quickly may still be slow to download from:
  1. the latency of every mirror at once: how long `repodata/repomd.xml` takes to come, and its revision, which says
     whether the mirror is up to date;
  2. the throughput of the quickest few, one at a time (side by side they would measure each other): the first
     SAMPLE_BYTES of the repository's largest metadata file, which is what a refresh downloads.
"""
import configparser
import queue
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import Enum
from urllib.parse import urlsplit

from . import net
from .net import NetError, Request, open_url

REPOMD = "repodata/repomd.xml"
MAX_MIRRORS = 200
MAX_LIST_BYTES = 1 << 20      # a mirror list is a few kB; anything bigger is not one
MAX_REPOMD_BYTES = 1 << 20
LIST_TIMEOUT_S = 20
LATENCY_TIMEOUT_S = 6
LATENCY_WORKERS = 8
SPEED_CANDIDATES = 8          # mirrors that get the throughput test: the quickest to answer
SAMPLE_BYTES = 2 << 20
SPEED_TIMEOUT_S = 6           # to fetch the sample; a mirror slower than SAMPLE_BYTES / this is just "slow"
CHUNK = 64 << 10

METALINK_NS = "{http://www.metalinker.org/}"
REPOMD_NS = "{http://linux.duke.edu/metadata/repo}"
# an address the helper accepts as a baseurl (kram_helper.BASEURL_RE): no variables, no query, no credentials
BASEURL_RE = re.compile(r"^https?://[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::\d{1,5})?"
                        r"(?:/[A-Za-z0-9._~%+/-]*)?$")


class SourceKind(Enum):
    METALINK = "metalink"
    MIRRORLIST = "mirrorlist"


@dataclass(frozen=True)
class Mirror:
    url: str            # the repository's base address, with the closing "/"
    protocol: str       # "https" or "http"
    country: str = ""   # ISO code, when the list says
    preference: int = 0  # the list's own order of preference, higher first; 0 when it has none


@dataclass(frozen=True)
class Probe:
    """What the test learned about a mirror; every field but `error` is None until it is known."""
    latency_s: float | None = None
    speed_bps: float | None = None
    revision: int | None = None   # of the repository's metadata: the newest of the mirrors is the current one
    sample: str = ""              # the file the throughput was measured on, relative to the mirror
    error: str = ""


@dataclass(frozen=True)
class MirrorSource:
    """Where a repository gets its mirrors from."""
    kind: SourceKind
    url: str       # the metalink or mirrorlist, variables replaced
    pinned: str    # the base address the repository is pinned to; "" while libdnf5 chooses


def valid_baseurl(url: str) -> bool:
    return bool(BASEURL_RE.match(url)) and url.endswith("/")


def _as_base(url: str) -> str | None:
    """`url` as a mirror's base address: it ends in repodata/repomd.xml in a metalink; a mirrorlist gives the base."""
    url = url.strip()
    if url.endswith(REPOMD):
        url = url[: -len(REPOMD)]
    if not url.endswith("/"):
        url += "/"
    return url if valid_baseurl(url) else None


def _collect(found: list[tuple[str, str, int]]) -> list[Mirror]:
    seen: set[str] = set()
    mirrors = []
    for url, country, preference in found:
        base = _as_base(url)
        if base is None or base in seen:
            continue
        seen.add(base)
        mirrors.append(Mirror(base, urlsplit(base).scheme, country, preference))
    return mirrors[:MAX_MIRRORS]


def parse_metalink(body: bytes) -> list[Mirror]:
    """The http and https mirrors of a metalink; rsync and ftp ones are not for dnf. `ValueError` if it is no metalink."""
    try:
        root = ET.fromstring(body)  # noqa: S314 (expat refuses entity expansion bombs; the size is capped)
    except ET.ParseError as e:
        raise ValueError("The answer is not a metalink") from e
    found = []
    for el in root.iter(f"{METALINK_NS}url"):
        text = (el.text or "").strip()
        if not text.startswith(("http://", "https://")):
            continue
        try:
            preference = int(el.get("preference", "0"))
        except ValueError:
            preference = 0
        found.append((text, el.get("location", ""), preference))
    return _collect(found)


def parse_mirrorlist(body: bytes) -> list[Mirror]:
    """A mirrorlist: one base address per line, `#` comments."""
    lines = (line.strip() for line in body.decode("utf-8", "replace").splitlines())
    return _collect([(line, "", 0) for line in lines if line.startswith(("http://", "https://"))])


def parse_list(kind: SourceKind, body: bytes) -> list[Mirror]:
    return parse_metalink(body) if kind is SourceKind.METALINK else parse_mirrorlist(body)


def fetch_mirrors(source: MirrorSource, *, post: Callable[[Callable[[], None]], None],
                  done: Callable[[list[Mirror]], None], failed: Callable[[NetError], None]) -> Request:
    """Ask the metalink or mirrorlist for its mirrors (see kram.core.net.fetch)."""
    return net.fetch(source.url, timeout_s=LIST_TIMEOUT_S, post=post, done=done, failed=failed,
                     parse=lambda body: parse_list(source.kind, body))


# ------------------------------------------------------------------------------------------ where a repo's mirrors are

def substitute(text: str, variables: Mapping[str, str]) -> str:
    """`$name` and `${name}` replaced, as the repository files write them; unknown ones stay."""
    return re.sub(r"\$(?:\{(\w+)\}|(\w+))", lambda m: variables.get(m.group(1) or m.group(2), m.group(0)), text)


def original_source(file_path: str, repo_id: str, variables: Mapping[str, str]) -> tuple[SourceKind, str] | None:
    """The metalink or mirrorlist the repository's own file names. A pinned repository has none in its configuration
    any more (the helper emptied it); the file still does."""
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    try:
        if not file_path or not parser.read(file_path, encoding="utf-8") or not parser.has_section(repo_id):
            return None
    except (OSError, configparser.Error, UnicodeDecodeError):
        return None
    for kind in SourceKind:
        value = parser.get(repo_id, kind.value, fallback="").strip()
        if value:
            return kind, substitute(value, variables)
    return None


def source_of(repo, variables: Mapping[str, str]) -> MirrorSource | None:
    """`repo`'s (a `RepoInfo`) mirror source; None for a repository with a single address, which has nothing to choose."""
    if repo.metalink:
        return MirrorSource(SourceKind.METALINK, repo.metalink, "")
    if repo.mirrorlist:
        return MirrorSource(SourceKind.MIRRORLIST, repo.mirrorlist, "")
    if repo.baseurls:
        original = original_source(repo.file_path, repo.id, variables)
        if original is not None:
            return MirrorSource(original[0], original[1], repo.baseurls[0])
    return None


# ------------------------------------------------------------------------------------------------- the speed test

def _parse_repomd(body: bytes) -> tuple[int | None, str]:
    """(revision, the file to measure throughput on: the largest data file's location, "" if none is named)."""
    try:
        root = ET.fromstring(body)  # noqa: S314 (see parse_metalink)
    except ET.ParseError:
        return None, ""
    try:
        revision = int(root.findtext(f"{REPOMD_NS}revision", ""))
    except ValueError:
        revision = None
    best, size = "", -1
    for data in root.iter(f"{REPOMD_NS}data"):
        location = data.find(f"{REPOMD_NS}location")
        href = location.get("href", "") if location is not None else ""
        try:
            n = int(data.findtext(f"{REPOMD_NS}size", "0"))
        except ValueError:
            n = 0
        if href.startswith("repodata/") and ".." not in href and n > size:
            best, size = href, n
    return revision, best


def probe_latency(mirror: Mirror, timeout_s: float = LATENCY_TIMEOUT_S) -> Probe:
    """Fetch the mirror's repomd.xml: how long until it is whole, and what it says."""
    start = time.monotonic()
    try:
        with open_url(mirror.url + REPOMD, timeout_s) as answer:
            body = answer.read(MAX_REPOMD_BYTES)
    except NetError as e:
        return Probe(error=str(e))
    except OSError as e:
        return Probe(error=str(net.as_net_error(e)))
    elapsed = time.monotonic() - start
    revision, sample = _parse_repomd(body)
    if revision is None and not sample:
        return Probe(error="Not a repository")
    return Probe(latency_s=elapsed, revision=revision, sample=sample)


def probe_speed(mirror: Mirror, sample: str, timeout_s: float = SPEED_TIMEOUT_S) -> float | None:
    """Bytes per second on the first SAMPLE_BYTES of `sample`, or None if nothing came."""
    try:
        with open_url(mirror.url + sample, timeout_s, {"Range": f"bytes=0-{SAMPLE_BYTES - 1}"}) as answer:
            start, got = time.monotonic(), 0
            while got < SAMPLE_BYTES and time.monotonic() - start < timeout_s:
                chunk = answer.read(min(CHUNK, SAMPLE_BYTES - got))
                if not chunk:
                    break
                got += len(chunk)
            elapsed = time.monotonic() - start
    except (NetError, OSError):
        return None
    return got / elapsed if got and elapsed > 0 else None


class SpeedTest:
    """Measures `mirrors` on threads of its own and reports on the main thread (`post`): `on_probe(mirror, probe)`
    after each step, `on_done()` at the end. After `cancel` nothing more is reported. The threads are daemons: a test
    that is running never keeps Kram from quitting."""

    def __init__(self, mirrors: list[Mirror], post: Callable[[Callable[[], None]], None],
                 on_probe: Callable[[Mirror, Probe], None], on_done: Callable[[], None], *,
                 latency: Callable[[Mirror], Probe] = probe_latency,
                 speed: Callable[[Mirror, str], float | None] = probe_speed):
        self._mirrors, self._post = mirrors, post
        self._on_probe, self._on_done = on_probe, on_done
        self._latency, self._speed = latency, speed
        self._cancelled = threading.Event()
        self.probes: dict[str, Probe] = {}

    def start(self) -> None:
        threading.Thread(target=self._run, name="kram-mirror-test", daemon=True).start()

    def cancel(self) -> None:
        self._cancelled.set()

    def _report(self, mirror: Mirror, probe: Probe) -> None:
        def deliver() -> None:
            if not self._cancelled.is_set():
                self.probes[mirror.url] = probe
                self._on_probe(mirror, probe)
        if not self._cancelled.is_set():
            self._post(deliver)

    def _run(self) -> None:
        todo: queue.Queue[Mirror] = queue.Queue()
        for mirror in self._mirrors:
            todo.put(mirror)
        results: dict[str, Probe] = {}
        lock = threading.Lock()

        def worker() -> None:
            while not self._cancelled.is_set():
                try:
                    mirror = todo.get_nowait()
                except queue.Empty:
                    return
                probe = self._latency(mirror)
                with lock:
                    results[mirror.url] = probe
                self._report(mirror, probe)

        workers = [threading.Thread(target=worker, name="kram-mirror-latency", daemon=True)
                   for _ in range(min(LATENCY_WORKERS, len(self._mirrors)))]
        for t in workers:
            t.start()
        for t in workers:
            t.join()
        quickest = sorted((m for m in self._mirrors if results.get(m.url, Probe()).latency_s is not None),
                          key=lambda m: results[m.url].latency_s)[:SPEED_CANDIDATES]
        for mirror in quickest:
            if self._cancelled.is_set():
                return
            probe = results[mirror.url]
            speed = self._speed(mirror, probe.sample) if probe.sample else None
            self._report(mirror, replace(probe, speed_bps=speed))
        if not self._cancelled.is_set():
            self._post(lambda: None if self._cancelled.is_set() else self._on_done())
