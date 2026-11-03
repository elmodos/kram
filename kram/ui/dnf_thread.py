"""Runs all libdnf5 work on one dedicated thread and delivers results back on the GUI thread."""
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from PySide6.QtCore import QObject, Signal


class DnfThread(QObject):
    _finished = Signal(object, object, object)  # callback, result, exception

    def __init__(self, parent=None):
        super().__init__(parent)
        # one worker == libdnf5 is only ever touched from a single thread
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="libdnf5")
        self._finished.connect(self._deliver)

    def submit(self, fn: Callable[[], Any], on_done: Callable[[Any], None],
               on_error: Callable[[BaseException], None] | None = None) -> None:
        def run():
            try:
                result = fn()
            except BaseException as e:  # noqa: BLE001 - reported to the GUI
                self._finished.emit((on_done, on_error), None, e)
            else:
                self._finished.emit((on_done, on_error), result, None)
        self._pool.submit(run)

    def _deliver(self, callbacks, result, error):
        on_done, on_error = callbacks
        if error is None:
            on_done(result)
        elif on_error is not None:
            on_error(error)
        else:
            raise error

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
