"""kram.app.progress without a toolkit: what the progress dialog shows for the helper's events."""
from datetime import datetime
from types import SimpleNamespace

from kram.app.ports import RecordingUi
from kram.app.progress import BUSY_BAR, Bar, Progress, Stage, shows_download, shows_rpm
from kram.core.mainloop import Signal


class View:
    def __init__(self):
        self.stages, self.download, self.rpm, self.log, self.done = [], [], [], [], []

    def show_stage(self, stage):
        self.stages.append(stage)

    def show_download(self, bar, label):
        self.download.append((bar, label))

    def show_rpm(self, bar, label):
        self.rpm.append((bar, label))

    def append_log(self, line):
        self.log.append(line)

    def request_done(self, ok):
        self.done.append(ok)


def progress(answers=(), accepted=True):
    answered = []
    client = SimpleNamespace(event=Signal(), failed=Signal(), request=lambda _r: accepted,
                             answer=lambda qid, yes: answered.append((qid, yes)))
    view, ui = View(), RecordingUi(list(answers))
    p = Progress(client, {"op": "transaction"}, view, ui, now=lambda: datetime(2026, 1, 1, 12, 0, 5))
    return p, client, view, ui, answered


def test_which_bars_a_request_has():
    assert shows_rpm({"op": "transaction"}) and not shows_rpm({"op": "refresh"})
    assert shows_download({"op": "refresh"}) and shows_download({"op": "clean_cache", "target": "dnf_metadata"})
    assert not shows_download({"op": "clean_cache", "target": "dnf_packages"})
    assert BUSY_BAR == Bar(0, 0)


def test_a_refused_request_connects_nothing():
    p, client, view, _ui, _answered = progress(accepted=False)
    assert not p.start()
    client.event.emit({"event": "done", "ok": True})
    assert view.done == []


def test_the_key_question_is_asked_and_answered():
    p, client, view, ui, answered = progress(answers=["yes"])
    p.start()
    client.event.emit({"event": "question", "id": 4, "kind": "gpg_key", "key_id": "ABCD", "user_ids": ["Fedora"],
                       "fingerprint": "F1", "url": "file:///key"})
    client.event.emit({"event": "question", "id": 5, "kind": "other"})
    assert answered == [(4, True), (5, False)] and "Fingerprint: F1" in ui.calls[0][1].text
    assert view.log == ["12:00:05  Key ABCD: importing"]


def test_success_fills_the_bars_and_a_failure_says_why():
    p, client, view, _ui, _answered = progress()
    p.start()
    client.event.emit({"event": "done", "ok": True, "download_only": True})
    assert view.stages[-1] == Stage("Done.", "done", "Packages downloaded.") and view.done == [True]
    assert view.download[-1] == (Bar(1, 1), None) and view.rpm[-1] == (Bar(1, 1), None) and p.ok and not p.running
    p.stop()
    p, client, view, _ui, _answered = progress()
    p.start()
    client.failed.emit("helper died\nmore")
    assert view.stages[-1] == Stage("Error:", "error", "helper died") and view.done == [False]
    assert view.log[-1] == "12:00:05  ERROR: helper died\nmore" and view.download[-1] == (Bar(0, 1), None)
