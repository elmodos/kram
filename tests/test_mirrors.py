"""kram.core.mirrors: the lists, the speed test against a local server, where a repository's mirrors come from."""
import http.server
import threading
from types import SimpleNamespace

import pytest

from kram.core import mirrors as m
from kram.core.mirrors import Mirror, MirrorSource, Probe, SourceKind

METALINK = b"""<?xml version="1.0" encoding="utf-8"?>
<metalink version="3.0" xmlns="http://www.metalinker.org/" type="dynamic">
 <files><file name="repomd.xml"><resources maxconnections="1">
  <url protocol="http" type="http" location="DE" preference="100">http://a.example/fedora/updates/45/Everything/x86_64/repodata/repomd.xml</url>
  <url protocol="https" type="https" location="DE" preference="100">https://a.example/fedora/updates/45/Everything/x86_64/repodata/repomd.xml</url>
  <url protocol="rsync" type="rsync" location="DE" preference="100">rsync://a.example/fedora/updates/45/Everything/x86_64/repodata/repomd.xml</url>
  <url protocol="https" type="https" location="NL" preference="99">https://b.example/fedora/updates/45/Everything/x86_64/repodata/repomd.xml</url>
  <url protocol="https" type="https" location="NL" preference="99">https://b.example/fedora/updates/45/Everything/x86_64/repodata/repomd.xml</url>
  <url protocol="https" type="https" location="XX" preference="x">https://c.example:8443/f/repodata/repomd.xml</url>
  <url protocol="https" type="https" location="XX" preference="1">https://evil.example/$releasever/repodata/repomd.xml</url>
  <url protocol="https" type="https" location="XX" preference="1">https://user:pw@evil.example/f/repodata/repomd.xml</url>
 </resources></file></files></metalink>"""

REPOMD_XML = """<?xml version="1.0"?>
<repomd xmlns="http://linux.duke.edu/metadata/repo">
 <revision>%d</revision>
 <data type="filelists"><location href="repodata/filelists.xml.zck"/><size>500</size></data>
 <data type="primary"><location href="repodata/primary.xml.zck"/><size>9000000</size></data>
 <data type="other"><location href="../../etc/passwd"/><size>99999999</size></data>
</repomd>"""


def test_metalink_gives_the_http_and_https_mirrors_once():
    found = m.parse_metalink(METALINK)
    assert [(x.url, x.protocol, x.country, x.preference) for x in found] == [
        ("http://a.example/fedora/updates/45/Everything/x86_64/", "http", "DE", 100),
        ("https://a.example/fedora/updates/45/Everything/x86_64/", "https", "DE", 100),
        ("https://b.example/fedora/updates/45/Everything/x86_64/", "https", "NL", 99),
        ("https://c.example:8443/f/", "https", "XX", 0),   # a preference that is no number is 0
    ]  # no rsync; nothing with a variable or credentials in it


def test_a_metalink_that_is_not_xml_is_a_value_error():
    with pytest.raises(ValueError):
        m.parse_metalink(b"<html>captive portal")


def test_mirrorlist_is_one_base_address_a_line():
    body = b"# comment\nhttps://a.example/fedora/\nhttp://b.example/fedora\nftp://c.example/x/\n\nnonsense\n"
    assert [x.url for x in m.parse_mirrorlist(body)] == ["https://a.example/fedora/", "http://b.example/fedora/"]


def test_baseurl_the_helper_would_accept():
    assert m.valid_baseurl("https://a.example/f/")
    assert not m.valid_baseurl("https://a.example/f")
    assert not m.valid_baseurl("https://a.example/f/$x/")
    assert not m.valid_baseurl("file:///etc/")


def test_the_largest_data_file_is_what_gets_measured_and_dotdot_never():
    assert m._parse_repomd((REPOMD_XML % 7).encode()) == (7, "repodata/primary.xml.zck")
    assert m._parse_repomd(b"nope") == (None, "")


# ---------------------------------------------------------------------------------- where a repository's mirrors are

def repo(**kw):
    return SimpleNamespace(**{"id": "updates", "file_path": "", "metalink": "", "mirrorlist": "", "baseurls": (), **kw})


def test_substitute_replaces_known_variables_only():
    assert m.substitute("x?repo=f$releasever&a=${basearch}&b=$other", {"releasever": "45", "basearch": "x86_64"}) \
        == "x?repo=f45&a=x86_64&b=$other"


def test_a_repository_with_a_metalink_or_mirrorlist_chooses_automatically():
    assert m.source_of(repo(metalink="https://ml/"), {}) == MirrorSource(SourceKind.METALINK, "https://ml/", "")
    assert m.source_of(repo(mirrorlist="https://list/"), {}) == MirrorSource(SourceKind.MIRRORLIST, "https://list/", "")


def test_a_repository_with_one_address_has_no_mirrors(tmp_path):
    f = tmp_path / "vscode.repo"
    f.write_text("[updates]\nbaseurl=https://one/\n")
    assert m.source_of(repo(baseurls=("https://one/",), file_path=str(f)), {}) is None
    assert m.source_of(repo(), {}) is None


def test_a_pinned_repository_is_found_again_from_its_file(tmp_path):
    f = tmp_path / "fedora-updates.repo"
    f.write_text("[updates]\nname=x\nmetalink=https://mirrors.example/metalink?repo=updates-f$releasever&arch=$basearch\n"
                 "[other]\nmetalink=https://other/\n")
    pinned = repo(baseurls=("https://a.example/f/",), file_path=str(f))
    assert m.source_of(pinned, {"releasever": "45", "basearch": "x86_64"}) == MirrorSource(
        SourceKind.METALINK, "https://mirrors.example/metalink?repo=updates-f45&arch=x86_64", "https://a.example/f/")
    assert m.source_of(repo(id="nope", baseurls=("https://a/",), file_path=str(f)), {}) is None
    assert m.source_of(repo(baseurls=("https://a/",), file_path=str(tmp_path / "missing.repo")), {}) is None


# ------------------------------------------------------------------------------------------------- the speed test

class Server(http.server.ThreadingHTTPServer):
    revision = 100
    primary = b"x" * (3 << 20)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if not self.path.startswith("/fedora/"):
            self.send_error(404)
            return
        if self.path.endswith("repodata/repomd.xml"):
            body = (REPOMD_XML % self.server.revision).encode()
        elif self.path.endswith("repodata/primary.xml.zck"):
            body = self.server.primary  # Range ignored, as some mirrors do: the test stops reading by itself
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass


@pytest.fixture
def server():
    srv = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def local(server, path="fedora/"):
    return Mirror(f"http://127.0.0.1:{server.server_port}/{path}", "http")


def test_latency_reads_repomd_and_its_revision(server):
    probe = m.probe_latency(local(server))
    assert probe.error == "" and probe.latency_s > 0
    assert (probe.revision, probe.sample) == (100, "repodata/primary.xml.zck")


def test_a_mirror_that_answers_404_or_nothing_has_an_error(server):
    probe = m.probe_latency(Mirror(f"http://127.0.0.1:{server.server_port}/", "http"))
    assert probe.latency_s is None and probe.error == "HTTP 404: Not Found"
    server.shutdown()
    server.server_close()
    assert m.probe_latency(local(server)).error  # connection refused


def test_speed_is_what_arrived_of_the_sample(server):
    speed = m.probe_speed(local(server), "repodata/primary.xml.zck")
    assert speed and speed > 100_000
    assert m.probe_speed(local(server), "repodata/missing") is None


def run_test(mirrors, latency, speed):
    events, finished = [], threading.Event()
    test = m.SpeedTest(mirrors, lambda fn: fn(), lambda mirror, probe: events.append((mirror.url, probe)),
                       finished.set, latency=latency, speed=speed)
    test.start()
    assert finished.wait(10)
    return test, events


def test_the_throughput_is_measured_for_the_quickest_only_and_after_all_latencies():
    mirrors = [Mirror(f"https://m{i}.example/", "https") for i in range(12)]
    latencies = {mir.url: Probe(latency_s=0.01 * (i + 1), revision=5, sample="repodata/p") for i, mir in enumerate(mirrors)}
    latencies[mirrors[3].url] = Probe(error="timed out")
    measured = []

    def speed(mirror, sample):
        measured.append(mirror.url)
        return 1000.0

    test, events = run_test(mirrors, lambda mir: latencies[mir.url], speed)
    stages = [bool(p.speed_bps) for _url, p in events]
    assert stages == sorted(stages)  # every latency came before the first speed
    assert len(measured) == m.SPEED_CANDIDATES
    assert mirrors[3].url not in measured and mirrors[0].url in measured and mirrors[11].url not in measured
    assert test.probes[mirrors[0].url].speed_bps == 1000.0 and test.probes[mirrors[3].url].error


def test_a_cancelled_test_reports_nothing_more():
    release, seen = threading.Event(), []
    mirrors = [Mirror("https://a.example/", "https")]
    posted = []
    test = m.SpeedTest(mirrors, posted.append, lambda *a: seen.append(a), lambda: seen.append("done"),
                       latency=lambda mir: (release.wait(5), Probe(latency_s=1, sample="x"))[1], speed=lambda *a: 1.0)
    test.start()
    test.cancel()
    release.set()
    threading.Event().wait(0.3)
    for fn in posted:
        fn()
    assert seen == []
