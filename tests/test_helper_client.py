"""HelperClient without Qt: a fake helper script stands for the pkexec'd one, a queue for the main loop."""
import queue
import sys
import threading
import time

from kram.ipc import client as ipc

FAKE_HELPER = r'''
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    if req["op"] == "quit":
        break
    if req["op"] == "crash":
        sys.exit(3)
    if req["op"] == "cancel":
        sys.exit(126)
    print("scriptlet says hi", file=sys.stderr, flush=True)
    print("not json", flush=True)
    print(json.dumps({"event": "progress", "op": req["op"]}), flush=True)
    print(json.dumps({"event": "done", "ok": True}), flush=True)
'''


class Loop:
    def __init__(self):
        self.calls: queue.SimpleQueue = queue.SimpleQueue()
        self.threads: set[str] = set()

    def post(self, fn):
        self.calls.put(fn)

    def run_until(self, condition, timeout=10.0):
        end = time.monotonic() + timeout
        while not condition() and time.monotonic() < end:
            try:
                fn = self.calls.get(timeout=0.01)
            except queue.Empty:
                continue
            self.threads.add(threading.current_thread().name)
            fn()
        assert condition()


def _client(monkeypatch, tmp_path, command=None):
    script = tmp_path / "helper.py"
    script.write_text(FAKE_HELPER)
    monkeypatch.setattr(ipc.HelperClient, "_command",
                        lambda self: command or [sys.executable, "-I", str(script)])
    loop = Loop()
    client = ipc.HelperClient(loop.post)
    events, failures = [], []
    client.event.connect(events.append)
    client.failed.connect(failures.append)
    return loop, client, events, failures


def test_events_until_done_then_idle(monkeypatch, tmp_path):
    loop, client, events, failures = _client(monkeypatch, tmp_path)
    client.request({"op": "refresh"})
    assert client.busy
    loop.run_until(lambda: not client.busy)
    stdout = [e for e in events if not e.get("stderr")]
    assert stdout == [{"event": "log", "text": "not json"}, {"event": "progress", "op": "refresh"},
                      {"event": "done", "ok": True}]
    assert failures == [] and loop.threads == {"MainThread"}
    # the same helper takes the next request (one password per session)
    proc = client._proc
    client.request({"op": "again"})
    loop.run_until(lambda: not client.busy)
    assert client._proc is proc and events[-1] == {"event": "done", "ok": True}
    loop.run_until(lambda: sum(1 for e in events if e.get("stderr")) == 2)
    assert {"event": "log", "text": "scriptlet says hi", "stderr": True} in events
    client.stop()
    assert proc.poll() == 0


def test_a_dying_helper_fails_the_request(monkeypatch, tmp_path):
    loop, client, _events, failures = _client(monkeypatch, tmp_path)
    client.request({"op": "crash"})
    loop.run_until(lambda: failures)
    assert not client.busy and failures == ["The privileged helper exited unexpectedly (code 3)."]


def test_a_cancelled_password_dialog(monkeypatch, tmp_path):
    loop, client, events, failures = _client(monkeypatch, tmp_path)
    client.request({"op": "cancel"})
    loop.run_until(lambda: failures)
    assert failures == ["Authentication was cancelled or not authorized."]
    client.request({"op": "refresh"})  # a new try starts a new helper
    loop.run_until(lambda: not client.busy)
    assert events[-1] == {"event": "done", "ok": True} and len(failures) == 1
    client.stop()


def test_no_pkexec_is_reported_from_the_main_loop(monkeypatch, tmp_path):
    loop, client, _events, failures = _client(monkeypatch, tmp_path, command=[str(tmp_path / "no-such-pkexec")])
    client.request({"op": "refresh"})
    assert failures == [] and client.busy  # not from inside request()
    loop.run_until(lambda: failures)
    assert failures == ["Could not start pkexec. Is polkit installed?"] and not client.busy


def test_busy_refuses_a_second_request(monkeypatch, tmp_path):
    loop, client, *_ = _client(monkeypatch, tmp_path)
    assert client.request({"op": "refresh"}) is True
    written = []
    monkeypatch.setattr(client, "_write", written.append)
    assert client.request({"op": "refresh"}) is False
    assert written == []  # nothing is sent to the helper
    loop.run_until(lambda: not client.busy)
    client.stop()


def test_a_non_object_json_line_becomes_a_log_event(monkeypatch, tmp_path):
    script = tmp_path / "numbers.py"
    script.write_text('import sys\nfor line in sys.stdin:\n    print(42, flush=True)\n'
                      '    print(\'{"event": "done", "ok": true}\', flush=True)\n')
    loop, client, events, _failures = _client(monkeypatch, tmp_path, command=[sys.executable, str(script)])
    client.request({"op": "refresh"})
    loop.run_until(lambda: not client.busy)
    assert {"event": "log", "text": "42"} in events and events[-1] == {"event": "done", "ok": True}
    client.stop()


class _StubbornProc:
    """A helper that does not quit in time and cannot be signalled, as after pkexec's uid change."""

    class _Stdin:
        def write(self, data):
            pass

        def flush(self):
            pass

        def close(self):
            pass

    def __init__(self):
        self.stdin = self._Stdin()

    def poll(self):
        return None

    def wait(self, timeout=None):
        raise ipc.subprocess.TimeoutExpired("helper", timeout)

    def kill(self):
        raise PermissionError("Operation not permitted")


def test_stop_survives_a_helper_it_cannot_kill(monkeypatch):
    monkeypatch.setattr(ipc.HelperClient, "_running", lambda self: True)
    client = ipc.HelperClient(lambda fn: None)
    client._proc = _StubbornProc()
    client.stop()  # must not raise

