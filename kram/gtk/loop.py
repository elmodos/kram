"""GTK's side of kram.core.mainloop and kram.app.scheduler: `post(fn)` runs fn on the GUI thread, from whichever
thread calls it; `GtkScheduler` is the Scheduler port on GLib timeouts."""
from collections.abc import Callable

from gi.repository import GLib


def post(fn: Callable[[], None]) -> None:
    """Run `fn` on the main loop soon. GLib.idle_add is thread-safe; at the default priority (not idle's) so that
    results keep their order with the rest of the loop's events and are not starved by redraws."""
    def run():
        fn()
        return GLib.SOURCE_REMOVE
    GLib.idle_add(run, priority=GLib.PRIORITY_DEFAULT)


class _Timer:
    def __init__(self, ms: int, fn: Callable[[], None]):
        self._ms, self._fn = ms, fn
        self._source = 0

    def start(self) -> None:
        self.stop()
        self._source = GLib.timeout_add(self._ms, self._fire)

    def stop(self) -> None:
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0

    @property
    def active(self) -> bool:
        return bool(self._source)

    def _fire(self) -> bool:
        self._source = 0
        self._fn()
        return GLib.SOURCE_REMOVE


class GtkScheduler:
    """`kram.app.scheduler.Scheduler` on GLib. GTK widgets are not deleted under their Python objects as Qt's are,
    so there is no parent to tie the timers to; a window stops its own timers when it closes."""

    def timer(self, ms: int, fn: Callable[[], None]) -> _Timer:
        return _Timer(ms, fn)

    def later(self, fn: Callable[[], None]) -> None:
        def run():
            fn()
            return GLib.SOURCE_REMOVE
        GLib.idle_add(run)
