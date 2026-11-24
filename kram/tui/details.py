"""The details panel of the terminal front end (docs/TUI_SPEC.md §7.4): the tab strip and the tab's document, as the
DetailsSink of the Browser's DetailsLoader, as kram.gtk.details.DetailsView is. What each tab says is
kram.app.details', drawn as text by kram.tui.doc_view; the Files tab is kram.tui.files.

One focusable widget, `DetailsBody`, draws whichever tab is shown, line by line: a document, the versions table or
the files. The panel keeps the content of every tab and lays out only the shown one, for the panel's width, when it
is drawn.

While the cursor rests on its way to the next package, the old documents stay, dimmed, until the new ones arrive
(§7.4.2); the advisories come with the row, so that tab is new at once.
"""
from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.actions import SkipAction
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Click
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input

from ..app.details import (
    DETAILS_TAB_KEY,
    TABS,
    TabChoice,
    VersionRow,
    advisories_doc,
    blocked_doc,
    changelog_doc,
    dependencies_doc,
    description_doc,
    general_doc,
    tab_titles,
    version_rows,
)
from ..app.doc import Doc, Link
from ..app.files import FILES_VIEW_KEY, can_show_in_file_manager, filter_placeholder
from ..core.model import PkgDetails, PkgRow
from ..core.settings import store as settings
from ..i18n import _, pgettext
from . import ui_port
from .doc_view import DocLines, doc_lines, link_of
from .files import FileState
from .glyphs import Glyphs
from .package_list import EXTEND, MOVE, fit
from .palette import role
from .widgets import ChoiceList, hint

FILTER_DELAY_MS = 150  # as the GUIs: a package can have tens of thousands of files, filter once the typing pauses
DOC_TABS = ("description", "general", "advisories", "dependencies", "changelog")
VERSION_WIDTH = 28  # the version column at most; the repository's as wide as its longest
REPO_WIDTH = 24


def hint_words() -> dict[str, str]:
    """The words after the keys in the panel's hints, by what they do."""
    return {"prev": pgettext("details key hint", "prev"), "next": pgettext("details key hint", "next"),
            "tabs": pgettext("details key hint", "tabs"), "links": pgettext("details key hint", "links"),
            "open": pgettext("details key hint", "open"), "tree": pgettext("details key hint", "tree"),
            "list": pgettext("details key hint", "list"), "filter": pgettext("details key hint", "filter"),
            "copy": pgettext("details key hint", "copy"), "show": pgettext("details key hint", "show")}


def versions_lines(rows: list[VersionRow], width: int, ellipsis: str) -> list[Text]:
    """The Versions tab (§7.4.4): version, repository and state, the installed version and the candidate bold, one
    the version lock leaves out dimmed, as in the GUIs."""
    if not rows:
        return []
    titles = (_("Version"), _("Repository"), _("State"))
    evr = min(VERSION_WIDTH, max(cell_len(titles[0]), *(cell_len(r.evr) for r in rows)))
    repo = min(REPO_WIDTH, max(cell_len(titles[1]), *(cell_len(r.repo) for r in rows)))
    state = max(1, width - evr - repo - 5)  # a margin, and two cells between the columns

    def line(cells: tuple[str, str, str], style: Style) -> Text:
        return Text(" " + fit(cells[0], evr, False, ellipsis) + "  " + fit(cells[1], repo, False, ellipsis) + "  "
                    + fit(cells[2], state, False, ellipsis).rstrip(), style)
    return [line(titles, role("header")),
            *(line((r.evr, r.repo, r.state), Style(bold=r.bold or None, dim=r.dimmed or None)) for r in rows)]


class TabStrip(Widget):
    """The tabs on one line (§7.4.1): every one when they fit, `1 Description │ 2 General │ …`; else the current
    one between arrows with its number, and a word when the package has advisories. A click picks a tab, or steps on
    an arrow."""

    DEFAULT_CSS = "TabStrip { height: 1; }"

    def __init__(self, details: "Details", **kw):
        super().__init__(**kw)
        self.details = details
        self.regions: list[tuple[int, int, str | int]] = []  # (from, to, a tab's name or a step)

    def render(self) -> Text:
        text, self.regions = self.details.strip_text(self.size.width)
        return text

    def on_click(self, event: Click) -> None:
        for start, end, what in self.regions:
            if start <= event.x < end:
                if isinstance(what, int):
                    self.details.action_tab(what)
                else:
                    self.details.choose(what)
                return


class FilterLine(Input):
    """The Files tab's filter (§7.4.3): text anywhere in the path, or a shell pattern. Enter keeps it and goes back
    to the files; Esc empties it."""

    BINDINGS = [Binding("escape", "close", show=False)]
    DEFAULT_CSS = """
    FilterLine { border: none; height: 1; padding: 0 1; background: $background; }
    FilterLine.hidden { display: none; }
    """

    def __init__(self, details: "Details", **kw):
        super().__init__(placeholder=filter_placeholder(), **kw)
        self.details = details

    def action_close(self) -> None:
        self.details.close_filter()


class DetailsBody(ScrollView, can_focus=True):
    """The shown tab, line by line. A document scrolls; `tab` moves between its links and `enter` follows one; the
    Files tab has a cursor, line 0 says how many files there are and stays in place."""

    BINDINGS = [
        Binding("up,k", "move(-1)", MOVE, show=False),
        Binding("down,j", "move(1)", MOVE, show=False),
        Binding("pageup", "page(-1)", MOVE, show=False),
        Binding("pagedown", "page(1)", MOVE, show=False),
        Binding("home", "jump(0)", MOVE, show=False),
        Binding("end", "jump(-1)", MOVE, show=False),
        Binding("shift+up", "extend(-1)", EXTEND, show=False),
        Binding("shift+down", "extend(1)", EXTEND, show=False),
        Binding("tab", "link(1)", _("Next or previous link"), show=False),
        Binding("shift+tab", "link(-1)", _("Next or previous link"), show=False),
        Binding("enter", "follow", _("Follow the link"), show=False),
    ]
    DEFAULT_CSS = "DetailsBody { height: 1fr; background: $background; overflow-x: hidden; }"

    def __init__(self, details: "Details", **kw):
        super().__init__(**kw)
        self.details = details
        self.link: int | None = None  # the focused link of the document
        self._cache: dict[tuple, DocLines] = {}  # by the tab, the width and what it says

    # ---------------------------------------------------------------- what is shown

    @property
    def files_mode(self) -> bool:
        return self.details.tab == "files"

    @property
    def text_width(self) -> int:
        """The width the lines are laid out in: without the scrollbar, when they do not fit."""
        width = max(1, self.size.width)
        if self.files_mode:
            return width
        lines = self._lines_for(width)
        height = self.size.height
        if height and len(lines.lines) > height:
            return max(1, width - self.styles.scrollbar_size_vertical)
        return width

    def _lines_for(self, width: int) -> DocLines:
        d = self.details
        key = (d.tab, width, d.generation)
        lines = self._cache.get(key)
        if lines is None:
            if len(self._cache) > 4:  # with and without the scrollbar, of the shown tab: the rest is old
                self._cache.clear()
            if d.tab == "versions":
                lines = DocLines(versions_lines(d.versions, width, d.glyphs.ellipsis))
            else:
                lines = doc_lines(d.doc(d.tab), width, d.glyphs, self.app.console)
            self._cache[key] = lines
        return lines

    def doc_lines(self) -> DocLines:
        return self._lines_for(self.text_width)

    def content_changed(self, to_top: bool) -> None:
        """What the tab shows changed: laid out again; `to_top`: a new package or tab, read from its start."""
        self.link = None
        self._cache.clear()
        self.sync_size()
        if to_top:
            self.scroll_to(x=0, y=0, animate=False, force=True)
        self.refresh()

    def sync_size(self) -> None:
        if self.files_mode:
            files = self.details.files
            files.build()
            lines = len(files.rows) + 1
        else:
            lines = len(self.doc_lines().lines)
        self.virtual_size = Size(self.size.width, lines)

    def on_resize(self) -> None:
        self.sync_size()
        self.details.show_hints()

    @property
    def lines_shown(self) -> int:
        return max(1, self.scrollable_content_region.height - (1 if self.files_mode else 0))

    # ---------------------------------------------------------------- drawing

    def render_line(self, y: int) -> Strip:
        width = self.scrollable_content_region.width
        d = self.details
        top = self.scroll_offset.y
        if self.files_mode:
            files = d.files
            if y == 0:
                text = files.info() if files.paths else Text()
            else:
                pos = top + y - 1
                text = files.line(pos, self.has_focus) if pos < len(files.rows) else Text()
            if text.cell_len > width:
                cut = width - cell_len(d.glyphs.ellipsis)
                text.truncate(max(0, cut))
                text.append(d.glyphs.ellipsis)
        else:
            lines = self._lines_for(self.text_width)
            n = top + y
            text = lines.lines[n] if n < len(lines.lines) else Text()
        segments = list(text.render(self.app.console))
        focused = self.link if self.has_focus and not self.files_mode else None
        dim = d.stale and d.tab != "advisories"
        if focused is not None or dim:
            current, faint = role("current"), Style(dim=True)
            segments = [Segment(s.text, (s.style or Style()) + current if link_of(s.style) == focused else s.style)
                        for s in segments] if focused is not None else segments
            if dim:
                segments = [Segment(s.text, (s.style or Style()) + faint) for s in segments]
        return Strip(segments).adjust_cell_length(width)

    # ---------------------------------------------------------------- keys

    def ensure_visible(self, line: int, height: int = 1) -> None:
        top, shown = self.scroll_offset.y, self.lines_shown
        if line < top:
            self.scroll_to(y=line, animate=False, force=True)
        elif line + height > top + shown:
            self.scroll_to(y=max(0, line + height - shown), animate=False, force=True)

    def _scroll(self, line: int) -> None:
        self.scroll_to(y=max(0, line), animate=False, force=True)

    def _go(self, pos: int, extend: bool = False) -> None:
        files = self.details.files
        files.go(pos, extend)
        self.ensure_visible(files.cursor)
        self.refresh()

    def action_move(self, d: int) -> None:
        if self.files_mode:
            self._go(self.details.files.cursor + d)
        else:
            self._scroll(self.scroll_offset.y + d)

    def action_page(self, d: int) -> None:
        step = max(1, self.lines_shown - 1)
        if self.files_mode:
            self._go(self.details.files.cursor + d * step)
        else:
            self._scroll(self.scroll_offset.y + d * step)

    def action_jump(self, pos: int) -> None:
        if self.files_mode:
            self._go(pos if pos >= 0 else len(self.details.files.rows) - 1)
        else:
            self._scroll(0 if pos >= 0 else self.virtual_size.height)

    def action_extend(self, d: int) -> None:
        if self.files_mode:
            self._go(self.details.files.cursor + d, extend=True)

    def action_link(self, d: int) -> None:
        """The next (or the previous) link: from the first one in sight; past the last one the focus goes on to the
        next panel, as `tab` does elsewhere."""
        lines = self.doc_lines() if not self.files_mode else None
        if lines is None or not lines.links:
            raise SkipAction()
        starts = lines.link_lines
        if self.link is None:
            top, bottom = self.scroll_offset.y, self.scroll_offset.y + self.lines_shown
            found = [i for i, line in enumerate(starts) if (line >= top if d > 0 else line < bottom)]
            i = (found[0] if d > 0 else found[-1]) if found else None
        else:
            i = self.link + d if 0 <= self.link + d < len(starts) else None
        self.link = i
        self.refresh()
        self.details.show_hints()
        if i is None:
            raise SkipAction()
        self.ensure_visible(starts[i])

    def action_follow(self) -> None:
        lines = self.doc_lines() if not self.files_mode else None
        if lines is None or self.link is None or self.link >= len(lines.links):
            raise SkipAction()
        self.details.follow(lines.links[self.link])

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "extend":
            return self.files_mode
        return True

    # ---------------------------------------------------------------- focus and the mouse

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()
        self.details.show_hints()

    def on_click(self, event: Click) -> None:
        if self.files_mode:
            if event.y >= 1:
                self._go(self.scroll_offset.y + event.y - 1)
            return
        number = link_of(event.style)
        lines = self.doc_lines()
        if number is not None and number < len(lines.links):
            self.link = number
            self.refresh()
            self.details.follow(lines.links[number])


class Details(Vertical):
    """The panel. `main` is the MainWindow: the Browser follows the package links, the Ui port the web links, copies
    and shows files."""

    # a cell between the left border and the text, as the list's margin
    DEFAULT_CSS = "Details { padding: 0 0 0 1; }"
    BINDINGS = [
        Binding("left_square_bracket", "tab(-1)", _("Previous or next tab"), show=False),
        Binding("right_square_bracket", "tab(1)", _("Previous or next tab"), show=False),
        *[Binding(str(i), f"tab_no({i})", _("A tab by its number"), show=False) for i in range(1, len(TABS) + 1)],
        Binding("t", "tabs", _("Tabs")),
        Binding("f", "files_mode", _("Tree or list"), show=False),
        Binding("slash", "filter", _("Filter the files"), show=False),
        Binding("y", "copy", _("Copy the selected paths"), show=False),
        Binding("o", "show_file", _("Show in File Manager"), show=False),
    ]

    def __init__(self, main, glyphs: Glyphs, **kw):
        super().__init__(**kw)
        self.main = main
        self.glyphs = glyphs
        self.desktop = ui_port.has_desktop()
        self.choice = TabChoice()
        self.tab = "description"
        self.docs: dict[str, Doc] = {name: Doc() for name in DOC_TABS}
        self.deps_body = Doc()
        self.blocked = Doc()
        self.has_advisories = False
        self.versions: list[VersionRow] = []
        self.files = FileState(glyphs)
        self.files.tree = settings.get(FILES_VIEW_KEY, "tree") != "list"
        self.generation = 0  # bumped when what a tab says changes: the laid-out lines are drawn again
        self.stale = False   # the documents are the last package's, the next one's are on their way
        self.shown_key: tuple[str, str] | None = None
        self.strip = TabStrip(self, id="details-tabs")
        self.filter = FilterLine(self, id="details-filter", classes="hidden")
        self.body = DetailsBody(self, id="details-body")
        self._filter_timer: Timer | None = None
        self.hints = Text()  # what the bottom border shows

    def compose(self) -> ComposeResult:
        yield self.strip
        yield self.filter
        yield self.body

    def on_resize(self) -> None:
        self.show_hints()

    def refresh_colours(self) -> None:
        """The scheme changed: the laid-out lines carry the old one's colours."""
        self.generation += 1
        self.body.content_changed(to_top=False)
        self.show_hints()

    # ---------------------------------------------------------------- the tabs

    def tabs(self) -> list[str]:
        return [name for name in TABS if name != "advisories" or self.has_advisories]

    def doc(self, name: str) -> Doc:
        if name == "dependencies":
            return self.blocked + self.deps_body
        return self.docs.get(name, Doc())

    def strip_text(self, width: int) -> tuple[Text, list[tuple[int, int, str | int]]]:
        """The strip for `width` cells, and where each tab (or arrow) is on it."""
        tabs, titles, g = self.tabs(), tab_titles(), self.glyphs
        full = Text()
        regions: list[tuple[int, int, str | int]] = []
        for i, name in enumerate(tabs, 1):
            if i > 1:
                full.append(g.separator, role("rule"))
            if name == self.tab:
                style = role("current")
            elif name == "advisories":
                style = role("upgradable") + Style(bold=True)
            elif name == "dependencies" and self.blocked:
                style = role("danger")
            else:
                style = Style()
            start = full.cell_len
            full.append(f" {i} {titles[name]} ", style)
            regions.append((start, full.cell_len, name))
        if full.cell_len <= width:
            return full, regions
        compact = Text()
        compact.append(g.left, role("muted"))
        regions = [(0, compact.cell_len, -1)]
        compact.append(f"  {titles[self.tab]} ", role("current"))
        compact.append(" ")
        start = compact.cell_len
        compact.append(g.right, role("muted"))
        regions.append((start, compact.cell_len, 1))
        compact.append(f"  {tabs.index(self.tab) + 1}/{len(tabs)}", role("muted"))
        if self.has_advisories and self.tab != "advisories":
            compact.append("  ")
            start = compact.cell_len
            compact.append(f"{g.warning} {pgettext('details tab strip', 'advisories')}",
                           role("upgradable") + Style(bold=True))
            regions.append((start, compact.cell_len, "advisories"))
        compact.truncate(width)
        return compact, regions

    def choose(self, name: str) -> None:
        """The user picked a tab: kept for the next packages and the next session (§7.4.1, §13.3)."""
        if name not in self.tabs():
            return
        self.choice.user_selected(name)
        settings.set(DETAILS_TAB_KEY, self.choice.saved_name(name))
        self._show_tab(name)

    def select_name(self, name: str) -> None:
        """The tab saved in the settings, as the GUIs' select_name: the advisories tab waits for a package that has
        advisories."""
        if (name := self.choice.to_select(name, self.has_advisories)) is not None:
            self.choice.user_selected(name)
            self._show_tab(name)

    def current_name(self) -> str:
        return self.choice.saved_name(self.tab)

    def _show_tab(self, name: str) -> None:
        changed = name != self.tab
        self.tab = name
        if name != "files" and self.filter.has_focus:
            self.body.focus()
        self.filter.set_class(name != "files" or not self.files.filter_text, "hidden")
        if changed:
            self.body.content_changed(to_top=True)
        self.strip.refresh()
        self.show_hints()
        self.refresh_bindings()

    def action_tab(self, d: int) -> None:
        tabs = self.tabs()
        self.choose(tabs[(tabs.index(self.tab) + d) % len(tabs)])

    def action_tab_no(self, n: int) -> None:
        tabs = self.tabs()
        if n <= len(tabs):
            self.choose(tabs[n - 1])

    def action_tabs(self) -> None:
        titles = tab_titles()
        items = [(name, f"{i}  {titles[name]}") for i, name in enumerate(self.tabs(), 1)]

        def chosen(name: str | None) -> None:
            if name is not None:
                self.choose(name)
        self.app.push_screen(ChoiceList(_("Tabs"), items, self.tab), chosen)

    # ---------------------------------------------------------------- the Files tab

    def action_files_mode(self) -> None:
        """`f`: the tree or the flat list, kept as the GUIs keep it."""
        self.files.set_tree(not self.files.tree)
        settings.set(FILES_VIEW_KEY, "tree" if self.files.tree else "list")
        self.body.content_changed(to_top=True)
        self.show_hints()

    def action_filter(self) -> None:
        self.filter.remove_class("hidden")
        self.filter.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        if self._filter_timer is not None:
            self._filter_timer.stop()
        self._filter_timer = self.set_timer(FILTER_DELAY_MS / 1000, self._apply_filter)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._apply_filter()
        self.filter.set_class(not self.files.filter_text, "hidden")
        self.body.focus()

    def _apply_filter(self) -> None:
        if self._filter_timer is not None:
            self._filter_timer.stop()
            self._filter_timer = None
        self.files.set_filter(self.filter.value)
        if self.tab == "files":
            self.body.content_changed(to_top=True)

    def close_filter(self) -> None:
        """Esc in the filter: it empties and goes away."""
        self.filter.value = ""
        self._apply_filter()
        self.filter.add_class("hidden")
        self.body.focus()

    def action_copy(self) -> None:
        if paths := self.files.selected_paths():
            self.main.ui.copy_text("\n".join(paths))

    def action_show_file(self) -> None:
        """`o`: the file in the file manager (§12.2). With no desktop there is none: the top line says so."""
        path = self.files.current_path()
        if not self.desktop:
            self.main.ui.status(_("No desktop to show it in"), ui_port.STATUS_MS)
        elif not can_show_in_file_manager(self.files.installed, path):
            self.main.ui.status(_("The file is not on this system: its package is not installed"),
                                ui_port.STATUS_MS)
        else:
            self.main.ui.show_in_file_manager(path)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "tab_no":
            return parameters[0] <= len(self.tabs())
        if action in ("files_mode", "filter", "show_file"):
            return self.tab == "files"
        if action == "copy":
            return self.tab == "files" and bool(self.files.rows)
        return True

    # ---------------------------------------------------------------- links (§7.4.5)

    def follow(self, link: Link) -> None:
        """A package or a dependency: selected in the list (alt+← goes back); a web address: the browser, or
        copied without a desktop (the Ui port)."""
        if link.kind in ("pkg", "dep"):
            self.main.browser.follow_link(link.kind, link.target)
        elif link.kind == "web":
            self.main.ui.open_web_link(link.target)

    # ---------------------------------------------------------------- the hints (§4.5)

    def show_hints(self) -> None:
        """The keys of the shown tab, as many as the bottom border has room for."""
        words = hint_words()
        pairs = [("[", words["prev"]), ("]", words["next"])]
        if self.tab == "files":
            pairs += [("f", words["list"] if self.files.tree else words["tree"]), ("/", words["filter"])]
            if self.files.rows:
                pairs.append(("y", words["copy"]))
            if self.desktop:
                pairs.append(("o", words["show"]))
        elif self.body.is_mounted and self.doc_has_links():
            pairs.append(("tab", words["links"]))
            if self.body.link is not None and self.body.has_focus:
                pairs.append(("enter", words["open"]))
        pairs.append(("t", words["tabs"]))
        room = self.size.width - 4  # the corners and a space on each side of the hints
        while pairs and hint(*pairs).cell_len > room:
            pairs.pop()
        self.hints = hint(*pairs)
        self.border_subtitle = self.hints

    def doc_has_links(self) -> bool:
        return self.tab != "versions" and bool(self.body.doc_lines().links)

    # ---------------------------------------------------------------- DetailsSink

    def _changed(self, tabs: tuple[str, ...], to_top: bool) -> None:
        self.generation += 1
        if not self.is_mounted:
            return
        if self.tab in tabs:
            self.body.content_changed(to_top)
        self.strip.refresh()
        self.show_hints()
        self.refresh_bindings()

    def show_advisories(self, row: PkgRow | None) -> None:
        if row is not None and self.shown_key is not None and row.key != self.shown_key:
            self.stale = True
        was = self.tab
        doc = advisories_doc(row) if row is not None else Doc()
        self.docs["advisories"] = doc
        self.has_advisories = bool(doc)
        if not doc and self.tab == "advisories":
            self.tab = self.choice.instead_of_advisories()
        elif doc and self.choice.wants_advisories:
            self.tab = "advisories"
        if self.tab != was and self.is_mounted:
            self._show_tab(self.tab)
        self._changed(("advisories",), to_top=True)
        if self.stale and self.is_mounted:
            self.body.refresh()  # dimmed

    def show_blocked(self, reason: str | None) -> None:
        self.blocked = blocked_doc(reason) if reason is not None else Doc()
        self._changed(("dependencies",), to_top=False)

    def show_package(self, row: PkgRow, d: PkgDetails) -> None:
        self.docs.update(description=description_doc(d), general=general_doc(row, d), changelog=changelog_doc(d))
        self.deps_body = dependencies_doc(d)
        self.files.set_files(d.files, d.files_complete)
        self.versions = version_rows(d)
        self.stale = False
        self.shown_key = row.key
        self._changed(TABS, to_top=True)

    def clear(self) -> None:
        self.docs.update(description=Doc(), general=Doc(), changelog=Doc())
        self.deps_body = Doc()
        self.files.set_files([], True)
        self.versions = []
        self.stale = False
        self.shown_key = None
        self.show_blocked(None)
        self.show_advisories(None)
