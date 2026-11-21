"""The two things the backend needs from whatever GUI toolkit runs it, so that it imports none.

`Post` hands a callable to the GUI's main loop: it may be called from any thread and must run the callable soon on
the GUI thread, in order. Qt: `kram.qt.qt_loop.post`; GTK would be `GLib.idle_add` with a callable that returns
False. Background work (the libdnf5 worker, the helper's output readers) reports back only through it, so every
`Signal` below is emitted, and every slot runs, on the GUI thread.
"""
from collections.abc import Callable
from typing import Any

Post = Callable[[Callable[[], None]], None]


class Signal:
    """A plain observer list with the shape of a Qt signal (connect / disconnect / emit), for backend objects.

    Slots run synchronously in `emit`, in the order they were connected.
    """

    def __init__(self) -> None:
        self._slots: list[Callable[..., Any]] = []

    def connect(self, slot: Callable[..., Any]) -> None:
        self._slots.append(slot)

    def disconnect(self, slot: Callable[..., Any]) -> None:
        self._slots.remove(slot)  # ValueError for a slot that is not connected, like Qt's RuntimeError

    def emit(self, *args: Any) -> None:
        for slot in list(self._slots):  # a slot may disconnect itself
            slot(*args)
