"""The Apply changes dialog (docs/TUI_SPEC.md §10.1): the `ApplyReviewView` of kram.app.apply_review.ApplyReview, as
kram.gtk.dialogs.apply is.

At the top, where it stays in sight: the summary line (what the transaction does, its sizes, the free space of the
filesystems it takes room on), the warning of `removal_warning` and why Apply is off when the disk is too full, both
in the danger role. Under them one scrolling area holds the rest, so that a narrow terminal still shows some of
everything: the marked changes the resolver left out, the changes by what happens to them (each kind in its role),
the recommendations as checkboxes, Download only and the dnf5 command. The buttons stay at the bottom.

What does not fit the width is dropped by column, never by word wrapping a row: a narrow dialog shows a package's
name, the version it ends up at and the size; a wide one adds the old version and the repository.

The dialog's result is the request to run (`ApplyReview.result`), or None. Its owner starts the transaction from
the dismissal callback, so that the progress dialog opens once this one is gone (kram.tui.root).
"""
from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget

from ...app.apply_review import (
    GROUP_SECTIONS,
    ApplyReview,
    ChangeRow,
    ChangeSection,
    Recommendations,
    RecRow,
    Resolver,
    free_space,
)
from ...app.columns import human_size
from ...app.doc import Span
from ...core.model import TransactionPreview
from ...i18n import _, ngettext
from ..doc_view import spans_text
from ..package_list import fit
from ..palette import role
from ..widgets import Button, CheckBox, hint

NARROW = 80            # cells of the list below which a row shows only the name, the new version and the size
NAME_WIDTHS = (12, 40)  # the name column's narrowest and widest
REPO_WIDTH = 12
SIZE_WIDTH = 9
INDENT = 2
# the colour roles of the sections (§10.1): the GUIs' colours of installing, upgrading and removing; others muted
ACTION_ROLES = {"install": "ok", "upgrade": "info", "remove": "danger"}
SECTION_ROLES = {colour: ACTION_ROLES[action] for action, _title, colour in GROUP_SECTIONS}
DIALOG_SHARE = 0.9     # of the screen's height, as every dialog (the app's `.dialog` rule)


def section_role(section: ChangeSection) -> str:
    return SECTION_ROLES.get(section.color, "muted")


def counts_line(preview: TransactionPreview) -> str:
    """How many packages are put in and taken out, in the main window's words for the marks."""
    remove = sum(1 for i in preview.items if i.action == "remove")
    install = sum(1 for i in preview.items if i.action not in ("remove", "reason"))
    return ngettext("{install} to install/upgrade, {remove} to remove.",
                    "{install} to install/upgrade, {remove} to remove.", install).format(install=install,
                                                                                          remove=remove)


def free_text(free: list[tuple[str, int]]) -> str:
    return "  ".join(_("{size} free on {mount}.").format(size=human_size(n), mount=mount) for mount, n in free)


class Lines(Widget):
    """Text drawn from `make()` at every paint, so that the colour roles follow a change of the scheme; it wraps."""

    DEFAULT_CSS = "Lines { height: auto; }"

    def __init__(self, make=None, **kw):
        super().__init__(**kw)
        self.make = make or Text

    def show(self, make) -> None:
        self.make = make
        self.display = bool(make().plain)
        self.refresh(layout=True)

    def render(self) -> Text:
        return self.make()


class ChangeList(Widget):
    """The changes by section: a title line in the section's role, then a line per package, cut to the width
    (never wrapped: the height is the number of lines whatever the width)."""

    DEFAULT_CSS = "ChangeList { height: auto; }"

    def __init__(self, glyphs, **kw):
        super().__init__(**kw)
        self.glyphs = glyphs
        self.sections: list[ChangeSection] = []

    def show(self, sections: list[ChangeSection]) -> None:
        self.sections = sections
        self.refresh(layout=True)

    def get_content_height(self, container, viewport, width: int) -> int:
        return sum(1 + len(s.rows) for s in self.sections)

    def render(self) -> Text:
        width = max(self.size.width, 20)
        narrow = width < NARROW
        rows = [r for s in self.sections for r in s.rows]
        name_w = max(NAME_WIDTHS[0], min(NAME_WIDTHS[1], max((cell_len(r.name) for r in rows), default=0) + 2))
        name_w = min(name_w, max(NAME_WIDTHS[0], width // 2 - INDENT))
        fixed = INDENT + name_w + 1 + SIZE_WIDTH + (0 if narrow else REPO_WIDTH + 1)
        # no wider than the versions: the repository and the size then stay next to them
        versions = max((cell_len(r.version) for r in rows), default=0) + 1
        version_w = max(1, min(width - fixed - 1, versions))
        e = self.glyphs.ellipsis
        out = Text(no_wrap=True, overflow="ellipsis")
        for i, section in enumerate(self.sections):
            if i:
                out.append("\n")
            out.append(section.title, role(section_role(section)) + Style(bold=True))
            for row in section.rows:
                out.append("\n")
                out.append_text(self._row(row, narrow, name_w, version_w, e))
        return out

    def _row(self, row: ChangeRow, narrow: bool, name_w: int, version_w: int, e: str) -> Text:
        t = Text(" " * INDENT)
        if row.warning:  # a removal the user may not expect (the GUIs' warning icon): the header's warning says why
            t.append(self.glyphs.warning, role("danger"))
            t.append(fit(" " + row.name, name_w - 1, False, e))
        else:
            t.append(fit(row.name, name_w, False, e))
        if row.group_id:  # a comps group: its name only
            return t
        version = row.version
        if narrow and " → " in version and not version.startswith("→"):
            version = version.rsplit(" → ", 1)[1]  # where it ends up
        t.append(" ")
        t.append(fit(version, version_w, False, e), role("muted"))
        if not narrow:
            t.append(" ")
            t.append(fit(row.repo, REPO_WIDTH, False, e), role("muted"))
        t.append(" ")
        t.append(fit(row.size, SIZE_WIDTH, True, e))
        return t


class RecBox(CheckBox):
    """A recommendation's checkbox; its label is laid out by the dialog for the width."""

    def __init__(self, row: RecRow, nested: bool):
        super().__init__("", row.rec.checked, classes="nested" if nested else "")
        self.row = row


class ApplyDialog(ModalScreen):
    """`resolve`: resolves the request again when a recommendation is unticked (Browser's)."""

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("ctrl+a", "apply", show=False, priority=True),
        Binding("y", "copy_command", show=False),
        Binding("pageup", "page(-1)", show=False),
        Binding("pagedown", "page(1)", show=False),
    ]
    DEFAULT_CSS = """
    ApplyDialog { align: center middle; }
    ApplyDialog #apply-scroll { height: auto; }
    ApplyDialog #changes { margin-top: 1; }
    ApplyDialog #recs { height: auto; }
    ApplyDialog RecBox { width: 100%; }
    ApplyDialog RecBox.nested { padding-left: 2; }
    ApplyDialog .head { margin-top: 1; }
    """

    def __init__(self, preview: TransactionPreview, request: dict, basearch: str, resolve: Resolver | None = None):
        super().__init__()
        self.review = ApplyReview(preview, request, basearch, self, resolve)
        self.can_apply = False
        self.busy = False
        self.sizes: list[Span] = []
        self.resolving_text: str | None = None
        self.command = ""
        self.recs: list[RecRow] = []
        self.nested: list[RecRow] = []
        self.free: list[tuple[str, int]] = []  # free_space, worked out when the space is checked

    # ---------------------------------------------------------------- the widgets

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog apply", id="apply-box")
        box.border_title = _("Apply changes")
        box.border_subtitle = hint(("space", _("tick")), ("y", _("copy")), ("ctrl+a", _("apply")),
                                   ("esc", _("cancel")))
        with box:
            yield Lines(self._summary, id="summary")
            yield Lines(id="warning")
            yield Lines(id="space")
            with VerticalScroll(id="apply-scroll"):
                yield Lines(id="skipped-title", classes="head")
                yield Lines(id="skipped")
                yield ChangeList(self.app.glyphs, id="changes")
                yield Lines(id="note", classes="head")
                yield Lines(id="recs-note", classes="head")
                yield Lines(id="recs-header")
                yield Vertical(id="recs")
                yield CheckBox(_("Download packages only"), False, id="download-only", classes="head")
                yield Lines(lambda: Text(_("Equivalent command"), role("header")), classes="head")
                yield Lines(lambda: Text(self.command, role("muted")), id="command")
            with Horizontal(classes="buttons"):
                yield Button(_("Apply"), id="apply", variant="primary")
                yield Button(_("Cancel"), id="cancel")

    def on_mount(self) -> None:
        self.review.start()
        apply = self.query_one("#apply", Button)
        (apply if apply.enabled else self.query_one("#cancel", Button)).focus()
        self._fit()

    def on_resize(self) -> None:
        self._label_recs()
        self._fit()

    def _fit(self) -> None:
        """The scrolling area takes what the dialog's lines and buttons leave of its height (90% of the screen):
        Textual sizes an area of `height: auto` to its content and would push the buttons out."""
        def fit_now() -> None:
            box, scroll = self.query_one("#apply-box"), self.query_one("#apply-scroll")
            others = sum(w.outer_size.height + w.styles.margin.top + w.styles.margin.bottom
                         for w in box.children if w is not scroll and w.display)
            room = int(self.size.height * DIALOG_SHARE) - 2 - others  # 2: the frame
            scroll.styles.max_height = max(3, room)
        self.call_after_refresh(fit_now)

    def _summary(self) -> Text:
        if self.resolving_text is not None:
            return Text(self.resolving_text, Style() if self.busy else role("danger"))
        preview = self.review.preview
        text = Text(counts_line(preview) + "  " if preview.items else "")
        text.append_text(spans_text(self.sizes, []))
        if free := free_text(self.free):
            text.append("  ")
            text.append(free, role("muted"))
        return text

    def _lines(self, name: str, text: str, style: str = "") -> None:
        """A line of the dialog in a colour role ("": plain); a warning in the danger role is bold as well."""
        def make() -> Text:
            if not style:
                return Text(text)
            return Text(text, role(style) + Style(bold=True) if style == "danger" else role(style))
        self.query_one(f"#{name}", Lines).show(make)

    # ---------------------------------------------------------------- the recommendations

    def _show_recs(self, direct: list[RecRow], nested: list[RecRow]) -> None:
        box = self.query_one("#recs", Vertical)
        old = list(box.query(RecBox))
        if [b.row.rec.what for b in old] == [r.rec.what for r in direct + nested]:
            for b, row in zip(old, direct + nested, strict=True):  # the same ones: in place, the focus stays
                b.row = row
                b.set_value(row.rec.checked)
        else:
            focused = self.focused.row.rec.what if isinstance(self.focused, RecBox) else None
            box.remove_children()
            boxes = [RecBox(r, False) for r in direct]
            if nested:
                title = Recommendations.nested_title(len(nested))
                boxes.append(Lines(lambda: Text(title, role("header")), classes="head"))
                boxes += [RecBox(r, True) for r in nested]
            box.mount(*boxes)
            again = next((b for b in boxes if isinstance(b, RecBox) and b.row.rec.what == focused), None)
            if again is not None:
                self.call_after_refresh(again.focus)
        self.recs, self.nested = direct, nested
        def note() -> Text:
            if not (direct or nested):
                return Text()
            text = Text(_("Recommended packages."), Style(bold=True))
            text.append(" " + _("Not required, but suggested by the packages being installed. "
                                "Uncheck what you do not want."))
            return text
        self.query_one("#recs-note", Lines).show(note)
        self.call_after_refresh(self._label_recs)

    def _rec_widths(self) -> tuple[int, int, bool]:
        """(the package column, the recommended-by column, whether that one is shown) for the width."""
        rows = self.recs + self.nested
        width = self.query_one("#recs").size.width or 60
        narrow = width < NARROW
        label = min(30, max([cell_len(r.label) for r in rows] + [cell_len(_("Recommended package"))]) + 2)
        by = min(30, max([cell_len(r.by) for r in rows] + [cell_len(_("Recommended by"))]) + 2)
        return label, by, not narrow

    def _label_recs(self) -> None:
        if not self.is_mounted:
            return
        label_w, by_w, with_by = self._rec_widths()
        e = self.app.glyphs.ellipsis
        def cell(text: str, width: int) -> str:  # a column and the gap after it
            return fit(text, width - 2, False, e) + "  "
        for b in self.query(RecBox):
            w = label_w - (2 if b.has_class("nested") else 0)
            text = cell(b.row.label, w) + (cell(b.row.by, by_w) if with_by else "") + b.row.adds
            b.set_label(text.rstrip())
        header = self.query_one("#recs-header", Lines)
        if self.recs or self.nested:
            # 4: the checkbox's "[x] " before the label
            text = " " * 4 + cell(_("Recommended package"), label_w) + (
                cell(_("Recommended by"), by_w) if with_by else "") + _("Adds")
            header.show(lambda: Text(text, role("header")))
        else:
            header.show(Text)

    def on_check_box_changed(self, event: CheckBox.Changed) -> None:
        event.stop()
        box = event.checkbox
        if box.id == "download-only":
            self.review.set_download_only(event.value)  # the space is checked again: show_space
        elif isinstance(box, RecBox) and box.row.rec.checked != event.value:
            self.review.recs.set_checked(box.row.rec, event.value)
            self.review.recs_changed()

    # ---------------------------------------------------------------- keys and buttons

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "apply":
            self.action_apply()
        else:
            self.action_cancel()

    def action_apply(self) -> None:
        if self.can_apply:
            self.review.close()  # results that arrive later are dropped
            self.dismiss(self.review.result())

    def action_cancel(self) -> None:
        self.review.close()
        self.dismiss(None)

    def action_copy_command(self) -> None:
        if self.command:
            self.app.ui.copy_text(self.command)

    def action_page(self, step: int) -> None:
        scroll = self.query_one("#apply-scroll", VerticalScroll)
        scroll.scroll_to(y=scroll.scroll_y + step * max(1, scroll.size.height - 1), animate=False)

    # ---------------------------------------------------------------- ApplyReviewView

    def show_preview(self, preview: TransactionPreview, sections: list[ChangeSection],
                     recs: tuple[list[RecRow], list[RecRow]]) -> None:
        self.query_one(ChangeList).show(sections)
        self._show_recs(*recs)
        self._fit()

    def show_texts(self, sizes: list[Span], note: str, warning: str, skipped_title: str, skipped: str) -> None:
        self.sizes = sizes
        self.query_one("#summary", Lines).refresh(layout=True)
        self._lines("note", note)
        self._lines("warning", warning, "danger")
        self._lines("skipped-title", skipped_title, "danger")
        self._lines("skipped", skipped, "muted")
        self._fit()

    def show_space(self, text: str) -> None:
        # the free space of the filesystems it takes room on, which change with Download only
        self.free = free_space(self.review.preview, self.review.download_only)
        self.query_one("#summary", Lines).refresh(layout=True)
        self._lines("space", text, "danger")
        self._fit()

    def show_command(self, text: str) -> None:
        self.command = text
        self.query_one("#command", Lines).refresh(layout=True)

    def set_can_apply(self, on: bool) -> None:
        self.can_apply = on
        self.query_one("#apply", Button).set_enabled(on)

    def set_resolving(self, busy: bool, text: str | None = None) -> None:
        self.busy = busy
        self.resolving_text = text if busy or text is not None else None
        for box in self.query(RecBox):
            box.set_enabled(not busy)
        self.query_one("#summary", Lines).refresh(layout=True)
        self._fit()
