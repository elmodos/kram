"""The search field's logic: its text and mode, when to search, and when a search belongs in the history.

The front end shows the text and the mode and reports what the user does (`edited`, `mode_chosen`, `submit`);
`shown(text, mode)` tells it to show a query without searching (it blocks its own change signals meanwhile).
"""
from ..core.mainloop import Signal
from ..core.search import Mode
from .scheduler import Scheduler

DEBOUNCE_MS = 150  # typing goes on: search once it pauses
HISTORY_IDLE_MS = 1500  # a search left alone this long goes into the history


class SearchController:
    """`changed()`: search again (the text paused, or the mode changed). `submitted()`: Enter. `settled()`: the
    results of a search have been left alone for a while, so it belongs in the history (`start_history` after showing
    them)."""

    def __init__(self, scheduler: Scheduler):
        self._text = ""
        self._mode = Mode.NAME
        self.changed = Signal()
        self.submitted = Signal()
        self.settled = Signal()
        self.shown = Signal()
        self._debounce = scheduler.timer(DEBOUNCE_MS, self.changed.emit)
        self._history = scheduler.timer(HISTORY_IDLE_MS, self.settled.emit)

    # ---------------------------------------------------------------- what the user does

    def edited(self, text: str) -> None:
        self._text = text
        self._debounce.start()

    def mode_chosen(self, mode: int) -> None:
        if Mode(mode) is not self._mode:
            self._mode = Mode(mode)
            self.changed.emit()

    def submit(self) -> None:
        self.submitted.emit()

    # ---------------------------------------------------------------- for the window

    def text(self) -> str:
        return self._text.strip()

    def mode(self) -> Mode:
        return self._mode

    @property
    def filtering(self) -> bool:
        """The search text filters the list: the field says so (a funnel), so that it is not missed after switching
        views."""
        return bool(self._text.strip())

    def set_mode(self, mode: int) -> None:
        """Search in another mode (searching again if it changed)."""
        if Mode(mode) is self._mode:
            return
        self._mode = Mode(mode)
        self.shown.emit(self._text, self._mode)
        self.changed.emit()

    def set_query(self, text: str, mode: int) -> None:
        """Show a search without running it: the caller does."""
        self._text, self._mode = text, Mode(mode)
        self.shown.emit(text, self._mode)

    def clear(self, quietly: bool = False) -> None:
        """Empty the field; `quietly` without searching again, for a caller that shows another list anyway."""
        self.set_query("", self._mode)
        if not quietly:
            self._debounce.start()

    def cancel_pending(self) -> None:
        """The search is running now: no need for the one the last keystroke scheduled."""
        self._debounce.stop()

    def start_history(self) -> None:
        self._history.start()

    def stop_history(self) -> None:
        self._history.stop()
