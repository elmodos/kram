"""Textual's side of kram.core.mainloop and kram.app.scheduler: `post(fn)` runs fn on the app's thread, from
whichever thread calls it; `TuiScheduler` is the Scheduler port on Textual's timers.

Both need the running app, which `attach` names (KramApp does, as it mounts). A call before that, or after the app
has closed, is dropped: there is no loop left to run it on. So is a posted call that comes due while the app is
closing, once its screens are gone: a catalog that finished loading as Kram quit asked for the window's bindings
there, and Textual raised.
"""
import asyncio
from collections.abc import Callable

from textual.app import App
from textual.timer import Timer as TextualTimer

_app: App | None = None
_loop: asyncio.AbstractEventLoop | None = None


def attach(app: App | None) -> None:
    """From the app's thread, while it runs (its mount): its asyncio loop is the running one."""
    global _app, _loop
    _app = app
    _loop = asyncio.get_running_loop() if app is not None else None


def post(fn: Callable[[], None]) -> None:
    """Run `fn` on the app's thread soon, in order with the other calls.

    Every call, from any thread, goes through the loop's own queue (`call_soon_threadsafe`) and from there to
    `App.call_later`, so that a call from the app's thread cannot overtake an earlier one from a worker. Not
    `App.call_from_thread`: that one waits until fn has run, so a worker would wait on the UI thread, and at exit a
    worker would wait forever on a loop that is gone; GTK's and Qt's `post` do not wait either."""
    app, running = _app, _loop
    if app is None or running is None:
        return
    try:
        running.call_soon_threadsafe(app.call_later, _while_open(app, fn))
    except RuntimeError:  # the loop is closed: the app has ended
        pass


def _while_open(app: App, fn: Callable[[], None]) -> Callable[[], None]:
    """`fn`, run only while the app has its screens (the module's docstring)."""
    def run() -> None:
        if app.screen_stack:
            fn()
    return run


class _Timer:
    def __init__(self, ms: int, fn: Callable[[], None]):
        self._ms, self._fn = ms, fn
        self._timer: TextualTimer | None = None

    def start(self) -> None:
        self.stop()
        if _app is not None:
            self._timer = _app.set_timer(self._ms / 1000, self._fire)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    @property
    def active(self) -> bool:
        return self._timer is not None

    def _fire(self) -> None:
        self._timer = None
        self._fn()


class TuiScheduler:
    """`kram.app.scheduler.Scheduler` on the app's timers. Widgets are not deleted under their Python objects, so,
    as in GTK, a dialog stops its own timers when it closes."""

    def timer(self, ms: int, fn: Callable[[], None]) -> _Timer:
        return _Timer(ms, fn)

    def later(self, fn: Callable[[], None]) -> None:
        if _app is not None:
            _app.call_later(fn)
