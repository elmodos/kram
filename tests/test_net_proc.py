"""kram.core.net and kram.core.proc: requests and programs on threads of their own, answers through `post`."""
import json
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from kram import __version__
from kram.core import net, proc

WAIT_S = 10


class MainLoop:
    """`post` from the worker threads; `run_one` runs the next posted call here, as a main loop would."""

    def __init__(self):
        self.calls = queue.Queue()

    def post(self, fn):
        self.calls.put(fn)

    def run_one(self, timeout=WAIT_S):
        self.calls.get(timeout=timeout)()

    def idle(self, wait=0.3):
        try:
            self.calls.get(timeout=wait)
        except queue.Empty:
            return True
        return False


class Handler(BaseHTTPRequestHandler):
    seen: list = []

    def do_GET(self):  # noqa: N802
        Handler.seen.append((self.path, self.headers.get("User-Agent"), self.headers.get("Accept")))
        if self.path.startswith("/slow"):
            self.server.release.wait(WAIT_S)
        status, body = {"/missing": (404, b"no"), "/html": (200, b"<html>bot check</html>")}.get(
            self.path.split("?")[0], (200, json.dumps({"path": self.path}).encode()))
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.release = threading.Event()
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    Handler.seen = []
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.release.set()
    httpd.shutdown()
    httpd.server_close()


def fetch_json(loop, url, **kw):
    out = []
    net.fetch_json(url, timeout_s=kw.pop("timeout_s", 5), post=loop.post, done=lambda v: out.append(("done", v)),
                   failed=lambda e: out.append(("failed", e)), **kw)
    loop.run_one()
    return out[0]


def test_json_answer_with_its_query_and_who_asks(server):
    loop = MainLoop()
    kind, value = fetch_json(loop, server + "/api", params={"query": "a b&c", "limit": "5"})
    assert kind == "done" and value == {"path": "/api?query=a+b%26c&limit=5"}
    # Bodhi answers a client it does not know with an HTML bot check
    assert Handler.seen[0][1:] == (f"Kram/{__version__}", "application/json")


def test_every_failure_is_a_net_error_with_a_reason(server):
    loop = MainLoop()
    for path, reason in (("/missing", "HTTP 404"), ("/html", "not JSON")):
        kind, error = fetch_json(loop, server + path)
        assert kind == "failed" and isinstance(error, net.NetError) and reason in str(error)
    kind, error = fetch_json(loop, server + "/slow", timeout_s=0.3)
    assert kind == "failed" and "timed out" in str(error)
    kind, error = fetch_json(loop, "http://127.0.0.1:9/")  # nothing listens on the discard port
    assert kind == "failed" and str(error)


def test_raw_bytes_and_a_cancelled_request_says_nothing(server):
    loop, out = MainLoop(), []
    net.fetch(server + "/html", timeout_s=5, post=loop.post, done=out.append, failed=out.append)
    loop.run_one()
    assert out == [b"<html>bot check</html>"]
    request = net.fetch(server + "/slow", timeout_s=5, post=loop.post, done=out.append, failed=out.append)
    request.cancel()
    assert loop.idle() and out == [b"<html>bot check</html>"]


def test_a_request_cancelled_after_its_answer_was_posted_is_dropped(server):
    """The answer may already wait in the main loop's queue when a newer search replaces the request."""
    loop, out = MainLoop(), []
    request = net.fetch(server + "/api", timeout_s=5, post=loop.post, done=out.append, failed=out.append)
    deliver = loop.calls.get(timeout=WAIT_S)
    request.cancel()
    deliver()
    assert out == []


def run(loop, argv, **kw):
    out = []
    process = proc.run(argv, post=loop.post, done=lambda *result: out.append(result), **kw)
    loop.run_one()
    return process, out[0]


def test_run_hands_over_code_and_output_with_its_environment():
    loop = MainLoop()
    code = "import os, sys; print(os.environ['KRAM_TEST']); print('é', file=sys.stderr); sys.exit(3)"
    process, result = run(loop, [sys.executable, "-c", code], env={"KRAM_TEST": "yes"})
    assert result == (3, "yes\n", "é\n") and not process.running


def test_a_program_that_is_not_there_finishes_with_a_reason():
    loop = MainLoop()
    _process, (code, stdout, stderr) = run(loop, ["/nonexistent/kram-test"])
    assert code == proc.FAILED_TO_START and stdout == "" and stderr


def test_a_killed_program_says_nothing():
    loop, out = MainLoop(), []
    process = proc.run([sys.executable, "-c", "import time; time.sleep(30)"], post=loop.post,
                       done=lambda *r: out.append(r))
    assert process.running
    process.kill()
    assert loop.idle(1.0) and out == [] and not process.running


def test_spawn_detached(tmp_path):
    mark = tmp_path / "ran"
    assert proc.spawn_detached([sys.executable, "-c", f"open({str(mark)!r}, 'w').write('x')"])
    assert not proc.spawn_detached(["/nonexistent/kram-test"])
    for _ in range(100):
        if mark.exists():
            break
        threading.Event().wait(0.05)
    assert mark.read_text() == "x"
