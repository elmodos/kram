"""Qt's side of kram.core.mainloop and kram.app.scheduler: `post(fn)` runs fn on the GUI thread, from whichever
thread calls it; `QtScheduler` is the Scheduler port on QTimer."""
import threading
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QObject, Qt, QTimer, Signal


class _Poster(QObject):
    # emitted from any thread, run from the GUI thread's event loop: queued even when posted from the GUI thread
    # itself, so `post` never calls back into its caller
    _call = Signal(object)

    def __init__(self):
        super().__init__()
        app = QCoreApplication.instance()
        if app is not None:
            self.moveToThread(app.thread())
        self._call.connect(self._run, Qt.ConnectionType.QueuedConnection)

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


class _Timer:
    def __init__(self, ms: int, fn: Callable[[], None], parent: QObject | None):
        self._timer = QTimer(parent, singleShot=True, interval=ms)
        self._timer.timeout.connect(fn)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def active(self) -> bool:
        return self._timer.isActive()


class QtScheduler:
    """`kram.app.scheduler.Scheduler` on QTimer. With a `parent`, its timers and `later` calls belong to that object
    and go with it: nothing fires into a widget Qt has deleted."""

    def __init__(self, parent: QObject | None = None):
        self._parent = parent

    def timer(self, ms: int, fn: Callable[[], None]) -> _Timer:
        return _Timer(ms, fn, self._parent)

    def later(self, fn: Callable[[], None]) -> None:
        if self._parent is None:
            QTimer.singleShot(0, fn)
        else:
            QTimer.singleShot(0, self._parent, fn)
