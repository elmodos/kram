"""DnfWorker: results come back on the GUI thread, and nothing of a job is freed on the worker (a widget freed
there made PySide delete it once more on the GUI thread: SIGSEGV, 2026-11-14). The worker needs no Qt: a queue
drained by the test stands for the main loop; the last test runs it on Qt's."""
import gc
import os
import queue
import threading
import time

import pytest

from kram.core.worker import DnfWorker


class Tracked:
    """Stands for a dialog: records the thread it is freed on."""
    freed_on: list[str] = []

    def __del__(self):
        Tracked.freed_on.append(threading.current_thread().name)


class Loop:
    """A main loop: `post` from any thread, `run_until` on the main thread."""

    def __init__(self):
        self.calls: queue.SimpleQueue = queue.SimpleQueue()

    def post(self, fn):
        self.calls.put(fn)

    def run_until(self, condition, timeout=5.0):
        end = time.monotonic() + timeout
        while not condition() and time.monotonic() < end:
            try:
                self.calls.get(timeout=0.01)()
            except queue.Empty:
                pass
        assert condition()


def _submit_tracked(dnf, fails, delivered):
    in_fn, in_callback = Tracked(), Tracked()

    def work(held=in_fn):
        time.sleep(0.05)  # the GUI side has long dropped its own references by now
        if fails:
            raise RuntimeError("no metadata")
        return 42

    def done(result, held=in_callback):
        delivered.append(("done", result, threading.current_thread() is threading.main_thread()))

    def failed(error, held=in_callback):
        delivered.append(("failed", str(error), threading.current_thread() is threading.main_thread()))

    dnf.submit(work, done, failed)  # once this returns, only the job holds them


@pytest.mark.parametrize("fails", [False, True])
def test_job_is_freed_on_the_gui_thread(fails):
    Tracked.freed_on = []
    loop, delivered = Loop(), []
    dnf = DnfWorker(loop.post)
    _submit_tracked(dnf, fails, delivered)
    loop.run_until(lambda: delivered)
    gc.collect()
    assert delivered == [("failed", "no metadata", True)] if fails else [("done", 42, True)]
    assert Tracked.freed_on == ["MainThread", "MainThread"]
    assert dnf._jobs == {}
    dnf.shutdown()


def test_jobs_run_one_at_a_time_in_order():
    loop, seen = Loop(), []
    dnf = DnfWorker(loop.post)
    threads = set()
    for i in range(5):
        dnf.submit(lambda i=i: (threads.add(threading.current_thread().name), i)[1], seen.append)
    loop.run_until(lambda: len(seen) == 5)
    assert seen == [0, 1, 2, 3, 4] and len(threads) == 1
    dnf.shutdown()


def test_on_qt_main_loop():
    pytest.importorskip("PySide6.QtCore")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication

    from kram.qt.qt_loop import post

    app = QCoreApplication.instance() or QCoreApplication([])
    Tracked.freed_on = []
    delivered = []
    dnf = DnfWorker(post)
    _submit_tracked(dnf, False, delivered)
    end = time.monotonic() + 5
    while not delivered and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    gc.collect()
    assert delivered == [("done", 42, True)]
    assert Tracked.freed_on == ["MainThread", "MainThread"]
    dnf.shutdown()


def test_qt_post_is_queued_even_from_the_gui_thread():
    pytest.importorskip("PySide6.QtCore")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication

    from kram.qt.qt_loop import post

    app = QCoreApplication.instance() or QCoreApplication([])
    seen = []
    post(lambda: seen.append(1))
    assert seen == []  # never a call back into the poster
    app.processEvents()
    assert seen == [1]
