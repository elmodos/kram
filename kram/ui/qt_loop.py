"""Qt's side of kram.core.mainloop: `post(fn)` runs fn on the GUI thread, from whichever thread calls it."""
import threading
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal


class _Poster(QObject):
    # emitted from any thread, run from the GUI thread's event loop: queued even when posted from the GUI thread
    # itself, so `post` never calls back into its caller
    _call = Signal(object)

    def __init__(self):
        super().__init__()
        app = QCoreApplication.instance()
        if app is not None:
            self.moveToThread(app.thread())
        self._call.connect(self._run, Qt.QueuedConnection)

    def _run(self, fn: Callable[[], None]) -> None:
        fn()


_poster: _Poster | None = None
_lock = threading.Lock()  # the first post may come from a worker thread


def post(fn: Callable[[], None]) -> None:
    global _poster
    with _lock:
        if _poster is None:
            _poster = _Poster()
    try:
        _poster._call.emit(fn)
    except RuntimeError:  # the application is going away: nobody is left to tell
        pass
