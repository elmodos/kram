"""The Install package file dialog (docs/TUI_SPEC.md §10.8): the `InstallView` of kram.app.install.Install, as
kram.gtk.dialogs.install is, gdebi-style: what the file is, what installing it changes, and the button that does it.

At the top, where they stay in sight: the package's name, version and summary, and the removal warning. Under them
one scrolling area holds the rest, in the order it matters, so that a short terminal shows the first of it: the
header's lines of the presenter (whether it installs, upgrades, downgrades or reinstalls, the signature, the
repository, the scripts, what `rpm -V` found), each after a glyph that says its kind without the colour (§9.5), the
size line, what installing it changes (the Apply dialog's sections), the recommendations as checkboxes, before a
reinstall what it repairs (the files `rpm -V` found missing or changed), the `sudo dnf5 install <file>` line (`y`
copies it), then what the GUIs show in tabs: the description, the dependencies, the files, the changelog, the
scripts and the details. The line of what still runs (reading the file, resolving, checking the installed files) is
above the buttons; the button waits for it. Esc closes it, but not while the installation runs: while root is asked
for, its progress dialog is not up yet.

Self-contained, as the GTK page is: it gets the catalog, its dnf thread, whether the helper is busy and a way to run
a request with its progress (`run(request, title, done(ok))`), so it works over the main window (File → Open
Package File…, a pasted path) and alone (`kram-tui FILE.rpm`, kram.tui.installer). Marks in the main window are not
part of it. Once installed it closes; its result is whether it changed the system (the window then reloads).
"""
from collections.abc import Callable

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget

from ...app.apply_review import ChangeSection, RecRow
from ...app.doc import Doc, Span
from ...app.icons import ERROR, INFO, OK, WARN
from ...app.install import INDENT, Install, InstallButton, Note
from ...core.worker import DnfWorker
from ...i18n import _
from .. import loop
from ..doc_view import doc_lines, spans_text
from ..palette import role
from ..widgets import Button, ButtonBar, CheckBox, hint
from .apply import ChangeList, Lines, RecBox, RecList

CHECK_PREFIX = "# "  # files_text's lines of what `rpm -V` found, before the file list


def note_text(note: Note, glyphs) -> Text:
    """A header line after the glyph of its kind, in its role; an INDENT line under the one before it."""
    marks = {OK: (glyphs.yes, "ok"), WARN: (glyphs.warning, "danger"), ERROR: (glyphs.no, "danger"),
             INFO: ("i", "info")}
    text = Text()
    if note.kind == INDENT:
        text.append("  ")
    else:
        glyph, name = marks.get(note.kind, (" ", "muted"))
        text.append(glyph, role(name) + Style(bold=True))
        text.append(" ")
    text.append_text(spans_text(note.spans, [], keep_newlines=note.kind == INDENT))
    return text


def split_files(text: str) -> tuple[list[str], str]:
    """files_text as (what `rpm -V` found, the file list)."""
    lines = text.split("\n")
    check = []
    while lines and lines[0].startswith(CHECK_PREFIX):
        check.append(lines.pop(0)[len(CHECK_PREFIX):])
    if check and lines and not lines[0]:
        lines.pop(0)
    return check, "\n".join(lines)


class DocBlock(Widget):
    """A document of kram.app.doc laid out for the width (kram.tui.doc_view), drawn at every paint so that its roles
    follow the scheme."""

    DEFAULT_CSS = "DocBlock { height: auto; }"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.doc = Doc([])

    def show(self, doc: Doc) -> None:
        self.doc = doc
        self.display = bool(doc.blocks)
        self.refresh(layout=True)

    def _lines(self, width: int) -> list[Text]:
        return doc_lines(self.doc, max(1, width), self.app.glyphs, self.app.console).lines

    def get_content_height(self, container, viewport, width: int) -> int:
        return len(self._lines(width))

    def render(self) -> Text:
        return Text("\n").join(self._lines(self.size.width))


class InstallDialog(ModalScreen):
    """`busy()`: the helper runs another request; `run(request, title, done(ok))` runs the installation with its
    progress dialog; `load_catalog`: alone (`kram-tui FILE.rpm`), nobody has loaded the catalog yet."""

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("ctrl+a", "install", show=False, priority=True),
        Binding("y", "copy_command", show=False),
        Binding("pageup", "page(-1)", show=False),
        Binding("pagedown", "page(1)", show=False),
    ]
    DEFAULT_CSS = """
    InstallDialog { align: center middle; }
    InstallDialog #install-box { height: 90%; }
    InstallDialog #install-scroll { height: 1fr; margin-top: 1; }
    InstallDialog .head { margin-top: 1; }
    InstallDialog #status { margin-top: 1; }
    """

    def __init__(self, path: str, catalog, dnf: DnfWorker, *, busy: Callable[[], bool],
                 run: Callable[[dict, str, Callable[[bool], None]], None], basearch: str = "x86_64", marks: int = 0,
                 load_catalog: bool = False):
        super().__init__()
        self.run_request = run
        self.logic = Install(path, catalog, dnf, loop.post, self, busy=busy, basearch=basearch, marks=marks,
                             load_catalog=load_catalog)
        self.button = InstallButton(_("Install"), "", True, False)
        self.command = ""
        self.title_parts = ("", "", "")
        self.notes: list[Note] = []
        self._dismissing = self._close_pending = False  # not `_closing`: that is Textual's own
        self._button_focused = False  # the default button gets the focus once, when it first can be pressed
        self.installing = False

    @property
    def changed_system(self) -> bool:
        return self.logic.changed_system

    # ---------------------------------------------------------------- the widgets

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog install", id="install-box")
        box.border_title = _("Install package file")
        with box:
            yield Lines(self._title, id="title")
            yield Lines(id="warning")
            with VerticalScroll(id="install-scroll"):
                yield Lines(self._notes, id="notes")
                yield Lines(id="sizes")
                yield self._header(_("What installing it changes"), "changes-title")
                yield ChangeList(self.app.glyphs, id="changes")
                yield Lines(id="problems")
                yield RecList(id="rec-list")
                # TRANSLATORS: the terminal's Install package file dialog: the files `rpm -V` found missing or
                # changed in the installed copy, which a reinstall puts back
                yield self._header(_("What reinstalling repairs"), "check-title")
                yield Lines(id="check")
                yield self._header(_("Equivalent command"), "command-title")
                yield Lines(lambda: Text(self.command, role("muted")), id="command")
                yield self._header(_("Description"), "description-title")
                yield DocBlock(id="description")
                yield self._header(_("Dependencies"), "deps-title")
                yield DocBlock(id="deps")
                yield self._header(_("Files"), "files-title")
                yield Lines(id="files")
                yield self._header(_("Changelog"), "changelog-title")
                yield DocBlock(id="changelog")
                yield self._header(_("Scripts"), "scripts-title")
                yield Lines(id="scripts")
                yield self._header(_("Details"), "details-title")
                yield DocBlock(id="details")
            yield Lines(id="status")
            with ButtonBar(classes="buttons"):
                with Horizontal():
                    yield Button(_("Install"), id="install", variant="primary", disabled=True)
                    yield Button(_("Close"), id="close")

    @staticmethod
    def _header(text: str, id: str) -> Lines:
        return Lines(lambda: Text(text, role("header")), id=id, classes="head")

    def on_mount(self) -> None:
        self.query_one("#install-scroll").focus()
        self._hint()
        self.logic.start()

    def _hint(self) -> None:
        pairs = [("space", _("tick"))] if self.query(RecBox) else []
        if self.command:
            pairs.append(("y", _("copy")))
        if self.button.visible and self.button.enabled:
            pairs.append(("ctrl+a", self.button.text.lower()))
        pairs.append(("esc", _("close")))
        self.query_one("#install-box").border_subtitle = hint(*pairs)

    def _title(self) -> Text:
        name, version, summary = self.title_parts
        text = Text(name, Style(bold=True))
        if version:
            text.append(" " + version)
        if summary:
            text.append("\n")
            text.append(summary, role("muted"))
        return text

    def _notes(self) -> Text:
        return Text("\n").join(note_text(n, self.app.glyphs) for n in self.notes)

    def _show(self, name: str, text: str, style: str = "", header: str = "") -> None:
        """A line (or lines) of the dialog in a colour role ("": plain), with its header, both hidden while empty."""
        def make() -> Text:
            return Text(text, role(style) if style else Style())
        self.query_one(f"#{name}", Lines).show(make)
        if header:
            self.query_one(f"#{header}", Lines).display = bool(text)

    def _show_doc(self, name: str, doc: Doc) -> None:
        self.query_one(f"#{name}", DocBlock).show(doc)
        self.query_one(f"#{name}-title", Lines).display = bool(doc.blocks)

    # ---------------------------------------------------------------- keys and buttons

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "install":
            self.action_install()
        else:
            self.action_close()

    def on_check_box_changed(self, event: CheckBox.Changed) -> None:
        event.stop()
        box = event.checkbox
        if isinstance(box, RecBox) and box.row.rec.checked != event.value:
            self.logic.recs.set_checked(box.row.rec, event.value)
            self.logic.recs_changed()

    def action_install(self) -> None:
        if self.button.visible and self.button.enabled:
            self.logic.install()

    def action_copy_command(self) -> None:
        if self.command:
            self.app.ui.copy_text(self.command)

    def action_page(self, step: int) -> None:
        scroll = self.query_one("#install-scroll", VerticalScroll)
        scroll.scroll_to(y=scroll.scroll_y + step * max(1, scroll.size.height - 1), animate=False)

    def action_close(self) -> None:
        """Not while the installation runs: while root is asked for, its progress dialog is not up yet."""
        if not self.installing:
            self._close()

    # ---------------------------------------------------------------- closing

    def _close(self) -> None:
        """Only from the top of the screens (kram.tui.dialogs.repos.ReposDialog._close): once installed, the
        progress dialog over it closes first."""
        if self._dismissing:
            return
        if self.app.screen is not self:
            self._close_pending = True
            return
        self._dismissing = True
        self.logic.close()  # what arrives later is dropped, the catalog forgets the file
        self.dismiss(self.logic.changed_system)

    def on_screen_resume(self) -> None:
        if self._close_pending:
            self._close_pending = False
            self._close()

    def on_unmount(self) -> None:
        self.logic.close()

    # ---------------------------------------------------------------- InstallView

    def show_title(self, name: str, version: str, summary: str) -> None:
        self.title_parts = (name, version, summary)
        self.query_one("#title", Lines).refresh(layout=True)

    def show_notes(self, notes: list[Note]) -> None:
        self.notes = notes
        self.query_one("#notes", Lines).show(self._notes)

    def show_sizes(self, spans: list[Span]) -> None:
        self.query_one("#sizes", Lines).show(lambda: spans_text(spans, []))

    def show_warning(self, text: str) -> None:
        self.query_one("#warning", Lines).show(lambda: Text(text, role("danger") + Style(bold=True)))

    def show_command(self, text: str | None) -> None:
        self.command = text or ""
        self._show("command", self.command, "muted", "command-title")
        self._hint()

    def show_button(self, button: InstallButton) -> None:
        self.button = button
        widget = self.query_one("#install", Button)
        widget.set_label(button.text)
        widget.display = button.visible
        widget.set_enabled(button.visible and button.enabled)
        self.query_one(ButtonBar).fit()
        if button.visible and button.enabled and not self._button_focused:
            self._button_focused = True  # the default button (§10), once: later the user's focus stays
            widget.focus()
        self._hint()

    def show_status(self, text: str) -> None:
        self._show("status", text, "muted")

    def show_file(self, description: Doc, details: Doc, changelog: Doc, scripts: str) -> None:
        self._show_doc("description", description)
        self._show_doc("details", details)
        self._show_doc("changelog", changelog)
        self._show("scripts", scripts, "muted", "scripts-title")

    def show_deps(self, doc: Doc) -> None:
        self._show_doc("deps", doc)

    def show_files(self, text: str) -> None:
        check, files = split_files(text)
        self._show("check", "\n".join(check), "danger", "check-title")
        self._show("files", files, "muted", "files-title")

    def show_changes(self, sections: list[ChangeSection], problems: list[str]) -> None:
        self.query_one(ChangeList).show(sections)
        self.query_one("#changes-title", Lines).display = bool(sections)
        self._show("problems", "\n".join(problems), "danger")

    def show_recs(self, rows: tuple[list[RecRow], list[RecRow]], visible: bool) -> None:
        recs = self.query_one(RecList)
        recs.show(*rows)
        recs.display = visible
        self._hint()

    def set_recs_enabled(self, on: bool) -> None:
        self.query_one(RecList).set_enabled(on)

    def run_transaction(self, request: dict, title: str, done: Callable[[bool], None]) -> None:
        self.installing = True

        def finished(ok: bool) -> None:
            self.installing = False
            done(ok)
        self.run_request(request, title, finished)

    def close_installed(self) -> None:
        self._close()
