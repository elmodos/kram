"""DnfThread: results come back on the GUI thread, and nothing of a job is freed on the worker (a widget freed
there made PySide delete it once more on the GUI thread: SIGSEGV, 2026-11-14)."""
import gc
import os
import threading
import time

import pytest

pytest.importorskip("PySide6.QtCore")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from kram.ui.dnf_thread import DnfThread  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


class Tracked:
    """Stands for a dialog: records the thread it is freed on."""
    freed_on: list[str] = []

    def __del__(self):
        Tracked.freed_on.append(threading.current_thread().name)


def wait_until(app, condition, timeout=5.0):
    end = time.monotonic() + timeout
    while not condition() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)
    assert condition()


@pytest.mark.parametrize("fails", [False, True])
def test_job_is_freed_on_the_gui_thread(app, fails):
    Tracked.freed_on = []
    dnf = DnfThread()
    delivered = []
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

    dnf.submit(work, done, failed)
    del work, done, failed, in_fn, in_callback  # only the job holds them now
    wait_until(app, lambda: delivered)
    gc.collect()
    assert delivered == [("failed", "no metadata", True)] if fails else [("done", 42, True)]
    assert Tracked.freed_on == ["MainThread", "MainThread"]
    assert dnf._jobs == {}
    dnf.shutdown()
