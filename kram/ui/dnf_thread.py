"""Runs all libdnf5 work on one dedicated thread and delivers results back on the GUI thread.

Every reference to a job (its function, callbacks, result or error) is owned by the GUI thread: the worker reads
the function from `_jobs`, puts the outcome back there and drops its own references before it signals. The
callbacks are often methods of dialogs or lambdas holding widgets. Had the worker dropped the last reference to
such a widget (the GUI having closed the dialog meanwhile), PySide would have deferred the C++ delete to the GUI
thread, where Qt had already deleted the widget with its parent: a crash (SIGSEGV in a pending call, 2026-11-14).
"""
import itertools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PySide6.QtCore import QObject, Signal


class DnfThread(QObject):
    _finished = Signal(int)  # job id; everything else stays in _jobs

    def __init__(self, parent=None):
        super().__init__(parent)
        # one worker == libdnf5 is only ever touched from a single thread
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="libdnf5")
        self._jobs: dict[int, list] = {}  # id -> [fn, on_done, on_error, result, error]
        self._ids = itertools.count()
        self._finished.connect(self._deliver)

    def submit(self, fn: Callable[[], Any], on_done: Callable[[Any], None],
               on_error: Callable[[BaseException], None] | None = None) -> None:
        job_id = next(self._ids)
        self._jobs[job_id] = [fn, on_done, on_error, None, None]
        self._pool.submit(self._run, job_id)

    def _run(self, job_id: int) -> None:
        """On the worker. Holds nothing of the job once it returns: the GUI thread frees all of it."""
        job = self._jobs[job_id]
        try:
            job[3] = job[0]()
        except BaseException as e:  # noqa: BLE001 - reported to the GUI
            job[4] = e
            del e
        del job
        self._finished.emit(job_id)

    def _deliver(self, job_id: int) -> None:
        _fn, on_done, on_error, result, error = self._jobs.pop(job_id)
        if error is None:
            on_done(result)
        elif on_error is not None:
            on_error(error)
        else:
            raise error

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
