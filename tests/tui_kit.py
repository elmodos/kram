"""What the terminal front end's tests are built on (docs/TUI_SPEC.md §14.2): a scheme's roles for the functions that
draw, run without an app; lines turned into a text grid and a grid of roles; snapshot files; a worker that runs its
jobs on the app's thread.

Not a test module: the TUI tests import from it, and its fixture `scheme` as `scheme_fixture`.
"""
import asyncio
import os
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.strip import Strip

from kram.tui import palette
from kram.tui.app import KramApp
from kram.tui.palette import Palette, Roles

SNAPSHOTS = Path(__file__).parent / "snapshots" / "tui"
UPDATE = os.environ.get("KRAM_UPDATE_SNAPSHOTS") == "1"
SCHEMES = ("textual-ansi", "kram-turbo", "kram-console", "textual-dark", "textual-light")


# ---------------------------------------------------------------- the roles of a scheme

class _RolesApp(KramApp):
    """The app with nothing but its palette: its CSS, its themes and the scheme switch, no window."""

    def make_main(self):
        return None

    def compose(self):
        yield Palette()

    def on_mount(self, event) -> None:
        event.prevent_default()  # Textual would run KramApp's own on_mount too, which needs the window
        self.theme_changed_signal.subscribe(self, self._theme_changed)


_roles: dict[str, Roles] = {}


def roles_of(scheme: str) -> Roles:
    """Every role of `scheme`, resolved once per test session by a palette-only app."""
    if not _roles:
        app = _RolesApp()

        async def go():
            async with app.run_test(size=(40, 5)) as pilot:
                for name in SCHEMES:
                    app.set_scheme(name, save=False)
                    await pilot.pause()
                    _roles[name] = Roles.taken()
        asyncio.run(go())
    return _roles[scheme]


@pytest.fixture(name="scheme")
def scheme_fixture(request):
    """The roles of a scheme (`parametrize("scheme", [...], indirect=True)`; Turbo if not given), answered by
    `role` while the test runs."""
    roles = roles_of(getattr(request, "param", "kram-turbo"))
    palette.use_roles(roles)
    yield roles
    palette.use_roles(None)


# ---------------------------------------------------------------- lines as cells

Line = Text | Strip | Iterable[Segment]
_console = Console(width=400, color_system="truecolor", legacy_windows=False, force_terminal=True)


def cells(line: Line) -> list[tuple[str, Style]]:
    """A line as its cells: (character, style); a wide character takes two, the second one "" ."""
    if isinstance(line, Text):
        segments = list(line.render(_console))
    else:
        segments = list(line)
    found: list[tuple[str, Style]] = []
    for seg in segments:
        if seg.control:
            continue
        style = seg.style or Style()
        for ch in seg.text:
            found.append((ch, style))
            if cell_len(ch) == 2:
                found.append(("", style))
    return found


def plain(line: Line) -> str:
    return "".join(ch for ch, _style in cells(line))


def styles_at(line: Line, text: str) -> set[Style]:
    """The styles of the cells of the first `text` in the line."""
    found = cells(line)
    joined = "".join(ch or "\0" for ch, _s in found)
    at = joined.index(text)
    return {style for _ch, style in found[at:at + len(text)]}


def role_names(style: Style, roles: Roles) -> str:
    """The roles a style is, as "cursor" or "cursor+installed"; its repr when it is none of them."""
    if not style:
        return "plain"
    for (name, bar), known in roles.styles.items():
        if look(known) == style:
            return f"bar-{name}" if bar else name
    return repr(style)


def look(style: Style) -> Style:
    """What a style looks like: its colours and attributes, without Textual's mouse bookkeeping (meta, links)."""
    return Style(color=style.color, bgcolor=style.bgcolor, bold=style.bold, dim=style.dim, italic=style.italic,
                 underline=style.underline, reverse=style.reverse, strike=style.strike)


def grid(lines: Iterable[Line], roles: Roles | None = None) -> str:
    """A snapshot of lines: the text between bars, then the same cells as letters, each letter a style named under
    them (by its role where it is exactly one, `roles`)."""
    rows = [cells(line) for line in lines]
    width = max((len(r) for r in rows), default=0)
    letters: dict[Style, str] = {}
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    text_rows, style_rows = [], []
    for row in rows:
        text_rows.append("|" + "".join(ch for ch, _s in row) + " " * (width - len(row)) + "|")
        codes = []
        for _ch, style in row:
            style = look(style)
            if style not in letters:
                letters[style] = alphabet[len(letters) % len(alphabet)]
            codes.append(letters[style])
        style_rows.append("|" + "".join(codes).ljust(width) + "|")
    legend = [f"{letter}: {role_names(style, roles) if roles else repr(style)}" for style, letter in letters.items()]
    return "\n".join(["text:", *text_rows, "styles:", *style_rows, "legend:", *legend]) + "\n"


def assert_snapshot(name: str, content: str, per_textual: bool = False) -> None:
    """`content` is what tests/snapshots/tui/<name>.txt holds; KRAM_UPDATE_SNAPSHOTS=1 writes it instead (a missing
    one fails otherwise). `per_textual`: a file for each major version of Textual (<name>.textual8.txt), for what
    Textual draws itself, which its versions draw differently (a field's placeholder, the order of its styles)."""
    if per_textual:
        import textual
        name = f"{name}.textual{textual.__version__.split('.')[0]}"
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return
    if not path.exists():
        raise AssertionError(f"no snapshot {path.name}: write it with KRAM_UPDATE_SNAPSHOTS=1 and read it in the diff")
    expected = path.read_text()
    assert content == expected, f"{path.name} differs (KRAM_UPDATE_SNAPSHOTS=1 rewrites it):\n{content}"


def screen_lines(app) -> list[Strip]:
    """The screen on top as the terminal gets it, line by line."""
    return app.screen._compositor.render_strips()


# ---------------------------------------------------------------- the worker

class InlineWorker:
    """`kram.core.worker.DnfWorker` without its thread: a job runs on the app's thread when submitted, its result is
    delivered through `post` as the real worker's is. `hold()` keeps the jobs until `release()`: a test sees the
    state while one is running, then lets it finish."""

    def __init__(self, post: Callable[[Callable[[], None]], None]):
        import threading
        self._post = post
        self.cancelled = threading.Event()
        self.held: list[tuple[Callable[[], Any], Callable[[Any], None], Callable[[BaseException], None] | None]] = []
        self.holding = False

    def submit(self, fn, on_done, on_error=None) -> None:
        if self.holding:
            self.held.append((fn, on_done, on_error))
        else:
            self._run(fn, on_done, on_error)

    def hold(self) -> None:
        self.holding = True

    def release(self) -> None:
        self.holding = False
        held, self.held = self.held, []
        for job in held:
            self._run(*job)

    def _run(self, fn, on_done, on_error) -> None:
        try:
            result = fn()
        except BaseException as e:  # noqa: BLE001 - delivered as the real worker does
            error = e
            if on_error is not None:
                self._post(lambda: on_error(error))
            else:
                def fail():
                    raise error
                self._post(fail)
            return
        self._post(lambda: on_done(result))

    def shutdown(self) -> None:
        self.cancelled.set()


# ---------------------------------------------------------------- the clock

class _ManualTimer:
    def __init__(self, clock: "ManualClock", ms: int, fn: Callable[[], None]):
        self.clock, self.ms, self.fn = clock, ms, fn
        self.active = False

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False


class ManualClock:
    """`kram.app.scheduler.Scheduler` whose timers go off when the test says so (`fire`), not after their time: a
    debounce or an idle timer is tested without waiting for it."""

    def __init__(self, post: Callable[[Callable[[], None]], None]):
        self._post = post
        self.timers: list[_ManualTimer] = []

    def timer(self, ms: int, fn: Callable[[], None]) -> _ManualTimer:
        t = _ManualTimer(self, ms, fn)
        self.timers.append(t)
        return t

    def later(self, fn: Callable[[], None]) -> None:
        self._post(fn)

    def fire(self, up_to_ms: int | None = None) -> int:
        """Every running timer of at most `up_to_ms` (all when None) goes off, as if that time had passed; how many
        did."""
        due = [t for t in self.timers if t.active and (up_to_ms is None or t.ms <= up_to_ms)]
        for t in due:
            t.active = False
            t.fn()
        return len(due)
