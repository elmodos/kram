"""A package file the user opened: header, signature and checksum, read with the user's own rights. No libdnf5,
no Qt; slow (hashes the whole file), so not on the GUI thread."""
import hashlib
import os
import re
import stat
import subprocess
from dataclasses import dataclass, field

import rpm

from ..helper.kram_helper import MAX_LOCAL_RPM
from .model import ChangelogEntry

MAX_CHANGELOG = 30
CHUNK = 1 << 20
# "Header OpenPGP V4 RSA/SHA256 signature, key fingerprint: 36f6…90a6: OK" (rpm 6),
# "Header V4 RSA/SHA256 Signature, key ID 6d9f90a6: NOKEY" (rpm 4)
SIGNATURE_RE = re.compile(r"signature, key (?:ID|fingerprint):? ([0-9a-f]+): (\w+)", re.I)
# rpm -V: "S.5....T.  c /etc/foo.conf", "missing     /usr/bin/foo", "missing   l /usr/share/x (Permission denied)"
VERIFY_RE = re.compile(r"^(missing|[.?SM5DLUGTP]{9})\s+?([cdglra]?)\s+(/.*)$")


class LocalRpmError(Exception):
    pass


@dataclass(slots=True)
class Signature:
    state: str            # ok | nokey | unsigned | bad (a digest or the signature does not match: damaged)
    key: str = ""         # fingerprint or key ID, as rpmkeys prints it
    signer: str = ""      # the imported key's name ("Fedora (44) <…>"), for "ok"


@dataclass(slots=True)
class LocalRpm:
    path: str
    sha256: str
    file_size: int
    name: str
    epoch: int | None
    version: str
    release: str
    arch: str
    summary: str
    description: str
    url: str
    license: str
    vendor: str
    packager: str
    build_time: int
    install_size: int
    source: bool          # a .src.rpm: can be built, not installed
    requires: list[str]
    recommends: list[str]
    suggests: list[str]
    supplements: list[str]
    provides: list[str]
    conflicts: list[str]
    obsoletes: list[str]
    files: list[str]
    changelog: list[ChangelogEntry]
    scripts: str          # `rpm -qp --scripts --triggers --filetriggers`, "" if none
    signature: Signature = field(default_factory=lambda: Signature("unsigned"))

    @property
    def evr(self) -> str:
        return f"{self.epoch}:{self.version}-{self.release}" if self.epoch else f"{self.version}-{self.release}"

    @property
    def nevra(self) -> str:
        return f"{self.name}-{self.evr}.{self.arch}"

    @property
    def adds_repository(self) -> list[str]:
        """Repository files it installs: it brings its own updates."""
        return [f for f in self.files if f.startswith("/etc/yum.repos.d/") and f.endswith(".repo")]


def _identity(st: os.stat_result) -> tuple:
    return st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def read(path: str) -> LocalRpm:
    """Everything the installer shows about `path`. The checksum is what the helper later insists on, so the
    header shown is checked to come from the same bytes: the file must not change while it is read."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK)
    except OSError as e:
        raise LocalRpmError(e.strerror or str(e)) from e
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise LocalRpmError("not a regular file")
        if before.st_size > MAX_LOCAL_RPM:
            raise LocalRpmError("the file is too large")
        digest = hashlib.sha256()
        while chunk := os.read(fd, CHUNK):
            digest.update(chunk)
        os.lseek(fd, 0, os.SEEK_SET)
        # signatures are checked by rpmkeys below, against the system keyring, with its exact verdict
        ts = rpm.TransactionSet("", rpm._RPMVSF_NOSIGNATURES | rpm._RPMVSF_NODIGESTS)
        try:
            hdr = ts.hdrFromFdno(fd)
        except rpm.error as e:
            raise LocalRpmError("not an rpm package") from e
        same_file = f"/dev/fd/{fd}"
        signature = _signature(_run(["rpmkeys", "-Kv", same_file], fd))
        scripts = _run(["rpm", "-qp", "--scripts", "--triggers", "--filetriggers", same_file], fd).strip()
        if _identity(os.fstat(fd)) != _identity(before):
            raise LocalRpmError("the file changed while it was being read")
    finally:
        os.close(fd)

    def deps(tag) -> list[str]:
        return list(dict.fromkeys(d for d in hdr[tag] if not d.startswith("rpmlib(")))

    changelog = [ChangelogEntry(t, a, x) for t, a, x in zip(
        hdr[rpm.RPMTAG_CHANGELOGTIME], hdr[rpm.RPMTAG_CHANGELOGNAME], hdr[rpm.RPMTAG_CHANGELOGTEXT])]
    return LocalRpm(
        path=path, sha256=digest.hexdigest(), file_size=before.st_size,
        name=hdr[rpm.RPMTAG_NAME], epoch=hdr[rpm.RPMTAG_EPOCH], version=hdr[rpm.RPMTAG_VERSION],
        release=hdr[rpm.RPMTAG_RELEASE], arch=hdr[rpm.RPMTAG_ARCH] or "noarch",
        summary=hdr[rpm.RPMTAG_SUMMARY] or "", description=hdr[rpm.RPMTAG_DESCRIPTION] or "",
        url=hdr[rpm.RPMTAG_URL] or "", license=hdr[rpm.RPMTAG_LICENSE] or "", vendor=hdr[rpm.RPMTAG_VENDOR] or "",
        packager=hdr[rpm.RPMTAG_PACKAGER] or "", build_time=hdr[rpm.RPMTAG_BUILDTIME] or 0,
        install_size=hdr[rpm.RPMTAG_LONGSIZE] or 0, source=bool(hdr.isSource()),
        requires=deps(rpm.RPMTAG_REQUIRENEVRS), recommends=deps(rpm.RPMTAG_RECOMMENDNEVRS),
        suggests=deps(rpm.RPMTAG_SUGGESTNEVRS), supplements=deps(rpm.RPMTAG_SUPPLEMENTNEVRS),
        provides=deps(rpm.RPMTAG_PROVIDENEVRS), conflicts=deps(rpm.RPMTAG_CONFLICTNEVRS),
        obsoletes=deps(rpm.RPMTAG_OBSOLETENEVRS), files=list(hdr["filenames"] or []),
        changelog=changelog[:MAX_CHANGELOG], scripts=scripts, signature=signature,
    )


def _run(cmd: list[str], fd: int) -> str:
    env = {**os.environ, "LC_ALL": "C.UTF-8"}  # parsed, and rpm's script headers stay as rpm users know them
    try:
        out = subprocess.run(cmd, pass_fds=(fd,), capture_output=True, text=True, errors="replace", env=env,
                             timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout


def _signature(rpmkeys_output: str) -> Signature:
    if any(re.search(r":\s*BAD\b", line) for line in rpmkeys_output.splitlines()):
        return Signature("bad")
    m = SIGNATURE_RE.search(rpmkeys_output)
    if not m:
        return Signature("unsigned")
    key, verdict = m.group(1).lower(), m.group(2).upper()
    if verdict != "OK":
        return Signature("nokey", key)
    return Signature("ok", key, _signer(key))


def _signer(key: str) -> str:
    """The imported public key's name: rpm 6 keeps the fingerprint as its version, rpm 4 the short key ID."""
    out = subprocess.run(["rpm", "-q", "gpg-pubkey", "--qf", "%{version} %{summary}\n"], capture_output=True,
                         text=True, errors="replace", check=False).stdout
    for line in out.splitlines():
        version, _sep, summary = line.partition(" ")
        version = version.lower()
        if version and (key.endswith(version) or version.endswith(key)):
            return summary.removesuffix(" public key")
    return ""


@dataclass(slots=True)
class VerifyResult:
    """`rpm -V` of an installed package, run as the user."""
    changed: list[tuple[str, str, bool]] = field(default_factory=list)  # (path, rpm's flags, a config file)
    missing: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)                  # could not be checked (permissions)

    @property
    def problems(self) -> int:
        return len(self.changed) + len(self.missing)


def verify_command(name: str, version: str, release: str, arch: str) -> list[str]:
    # no dependency check (another question) and no %verifyscript (package code, not run for the user)
    return ["rpm", "-V", "--nodeps", "--noscripts", f"{name}-{version}-{release}.{arch}"]


def parse_verify(output: str) -> VerifyResult:
    result = VerifyResult()
    for line in output.splitlines():
        m = VERIFY_RE.match(line)
        if not m:
            continue
        flags, attr, path = m.groups()
        if flags == "missing":
            path, _sep, error = path.partition(" (")
            if error and not error.startswith("No such file"):
                result.unreadable.append(path)
            else:
                result.missing.append(path)
        elif set(flags) <= {".", "?"}:
            result.unreadable.append(path)
        else:
            result.changed.append((path, flags, attr == "c"))
    return result
