"""Timers without a toolkit: the `Scheduler` port, and `FakeScheduler`, which runs them on demand in tests.

The front end passes its scheduler to the logic that waits: the search waits for typing to pause, the details for the
cursor to rest, the files filter for its text to settle. Qt implements it with QTimer (`kram.qt.qt_loop`), GTK with
GLib.timeout_add and GLib.idle_add.
"""
from collections.abc import Callable
from typing import Protocol


class Timer(Protocol):
    """A single-shot timer that can be restarted: `start` while it runs pushes the call back by its whole interval."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    @property
    def active(self) -> bool: ...


class Scheduler(Protocol):
    def timer(self, ms: int, fn: Callable[[], None]) -> Timer:
        """A timer that calls `fn` `ms` milliseconds after its last `start`. It does nothing until started."""
        ...

    def later(self, fn: Callable[[], None]) -> None:
        """Call `fn` once the main loop is idle: after the event being handled, and whatever it caused, is done."""
        ...


class FakeTimer:
    def __init__(self, scheduler: "FakeScheduler", ms: int, fn: Callable[[], None]):
        self._scheduler, self.ms, self.fn = scheduler, ms, fn
        self.due: int | None = None

    def start(self) -> None:
        self.due = self._scheduler.now + self.ms

    def stop(self) -> None:
        self.due = None

    @property
    def active(self) -> bool:
        return self.due is not None

    def fire(self) -> None:
        """Run it now, as if its time had come."""
        self.due = None
        self.fn()


class FakeScheduler:
    """A scheduler whose time moves only when a test says so: `advance(ms)` runs the timers that fall due, in order,
    and `run_idle()` the calls `later` queued."""

    def __init__(self) -> None:
        self.now = 0
        self.timers: list[FakeTimer] = []
        self.idle: list[Callable[[], None]] = []

    def timer(self, ms: int, fn: Callable[[], None]) -> FakeTimer:
        timer = FakeTimer(self, ms, fn)
        self.timers.append(timer)
        return timer

    def later(self, fn: Callable[[], None]) -> None:
        self.idle.append(fn)

    def advance(self, ms: int) -> None:
        end = self.now + ms
        while True:
            due = [t for t in self.timers if t.due is not None and t.due <= end]
            if not due:
                break
            timer = min(due, key=lambda t: t.due)
            self.now = timer.due
            timer.fire()
        self.now = end

    def run_idle(self) -> None:
        while self.idle:
            self.idle.pop(0)()
