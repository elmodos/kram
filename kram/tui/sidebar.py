"""The sidebar of the terminal front end (docs/TUI_SPEC.md §7.2): a view over kram.app.sidebar.SidebarModel, as
kram.gtk.sidebar is, with the keys of a terminal in place of the GUIs' view buttons and clicks.

The view's name is the panel's title; `[` `]` step through the views and `v` lists them. Unlike the GUIs, changing
the view does not filter the list (`SidebarModel.browse`): a keyboard steps through views on its way to another
one, and filtering by the first entry of each would redraw the package list at every step. `Enter` on an entry
filters, and closes a slide-over.

The entries are drawn line by line from the model's listing (`render_line`), so a count that changes redraws its
line alone (`entry_changed`). Folding (Environments) is the drawing's: the model only remembers what is unfolded.
"""
from rich.cells import cell_len, set_cell_size
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Click
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Static

from ..app.sidebar import VIEWS, Listing, SidebarModel, entry_font
from ..core.filters import FilterEntry
from ..core.marks import Action
from ..i18n import _, pgettext
from .glyphs import Glyphs
from .keymap import CONTEXT_KEYS
from .package_list import MOVE
from .palette import role
from .widgets import ChoiceList, PopupMenu, hint

PLACEHOLDERS = {
    "search": lambda: _("No searches yet. Press / to search."),
    "custom": lambda: _("No custom filters. New Filter from Current View is in the menu."),
}


def view_label(view_id: str) -> str:
    return next(label for vid, label, _b in VIEWS if vid == view_id)


def entry_line(e: FilterEntry, width: int, prefix: str, ellipsis: str, base: Style, count_style: Style) -> Strip:
    """An entry on one line of `width` cells: a margin, `prefix` (the indent and the fold glyph), the label cut with
    the ellipsis, its count right-aligned and never cut, a margin."""
    count = str(e.count) if e.count is not None else ""
    room = max(0, width - 2 - cell_len(prefix) - (cell_len(count) + 1 if count else 0))
    label = e.label
    if cell_len(label) > room:
        cut = room - cell_len(ellipsis)
        label = set_cell_size(label, cut) + ellipsis if cut > 0 else set_cell_size(label, room)
    bold, italic = entry_font(e)
    gap = width - 2 - cell_len(prefix) - cell_len(label) - cell_len(count)
    return Strip([Segment(" " + prefix, base), Segment(label, base + Style(bold=bold or None, italic=italic or None)),
                  Segment(" " * max(0, gap), base), Segment(count, count_style), Segment(" ", base)]
                 ).adjust_cell_length(width, base)


class EntryList(ScrollView, can_focus=True):
    """The entries of the shown view; the cursor is a line of `lines` (the entries not folded away)."""

    BINDINGS = [
        Binding("up,k", "move(-1)", MOVE, show=False),
        Binding("down,j", "move(1)", MOVE, show=False),
        Binding("pageup", "page(-1)", MOVE, show=False),
        Binding("pagedown", "page(1)", MOVE, show=False),
        Binding("home", "jump(0)", MOVE, show=False),
        Binding("end", "jump(-1)", MOVE, show=False),
        Binding("left,h", "fold(False)", _("Fold or unfold"), show=False),
        Binding("right,l", "fold(True)", _("Fold or unfold"), show=False),
        Binding("enter", "choose", _("Filter the list by the entry"), show=False),
    ]
    # the labels are cut to the width: nothing to scroll sideways to
    DEFAULT_CSS = "EntryList { height: 1fr; background: $background; overflow-x: hidden; }"

    def __init__(self, sidebar: "Sidebar", glyphs: Glyphs, **kw):
        super().__init__(**kw)
        self.sidebar = sidebar
        self.glyphs = glyphs
        self.listing: Listing | None = None
        self.expanded: set[str] = set()
        self.lines: list[int] = []  # the entries' indices in the listing, as shown
        self.cursor = 0
        self.current_id: str | None = None  # the view's current entry: in the filter's view, the filter's

    # ---------------------------------------------------------------- the listing

    def show(self, listing: Listing) -> None:
        """The model's listing. The same view drawn again (its counts, a restored entry) keeps the cursor on the
        entry it was on; another view, or the same one with another current entry (`SidebarModel.select` from
        code: a link, Esc in the search), starts at its current entry."""
        old = self.listing
        same = old is not None and old.view == listing.view and listing.current == self.current_id
        keep = self.current_entry() if same else None
        self.listing = listing
        self.current_id = listing.current
        self.expanded = set(listing.expanded) if listing.collapsible else set()
        self._layout()
        ids = [listing.entries[i].id for i in self.lines]
        target = keep.id if keep is not None and keep.id in ids else listing.current
        self.cursor = ids.index(target) if target in ids else 0
        if old is None or old.view != listing.view:
            self.scroll_to(y=0, animate=False, force=True)
        self.ensure_visible()
        self.refresh()

    def _layout(self) -> None:
        listing = self.listing
        if listing is None:
            self.lines = []
        else:
            self.lines = [i for i, parent in enumerate(listing.parents)
                          if parent is None or not listing.collapsible
                          or listing.entries[parent].id in self.expanded]
        self.virtual_size = Size(0, len(self.lines))

    def on_resize(self) -> None:
        self._layout()
        self.ensure_visible()

    def redraw_entry(self, index: int) -> None:
        """One entry's count changed: its line alone."""
        if index in self.lines:
            self.refresh_line(self.lines.index(index))

    def current_entry(self) -> FilterEntry | None:
        if self.listing is None or not self.lines:
            return None
        return self.listing.entries[self.lines[min(self.cursor, len(self.lines) - 1)]]

    def current_index(self) -> int | None:
        return self.lines[self.cursor] if self.lines else None

    def back_to_current(self) -> None:
        """The cursor back on the view's current entry: the one the list is filtered by in its view."""
        listing = self.listing
        if listing is None:
            return
        ids = [listing.entries[i].id for i in self.lines]
        if self.current_id in ids and ids.index(self.current_id) != self.cursor:
            self.cursor = ids.index(self.current_id)
            self.ensure_visible()
            self.refresh()

    # ---------------------------------------------------------------- drawing

    def _has_children(self, index: int) -> bool:
        parents = self.listing.parents
        return index + 1 < len(parents) and parents[index + 1] == index

    def _prefix(self, index: int) -> str:
        """The indent of an entry; in a view that folds, a parent's fold glyph, and room for it before the others."""
        listing = self.listing
        e = listing.entries[index]
        indent = "  " * e.indent
        if not listing.collapsible:
            return indent
        if listing.parents[index] is None and self._has_children(index):
            g = self.glyphs
            return indent + (g.unfolded if e.id in self.expanded else g.folded) + " "
        return indent + "  "

    def render_line(self, y: int) -> Strip:
        width = self.scrollable_content_region.width
        listing = self.listing
        if listing is None:
            return Strip.blank(width)
        if not listing.entries:
            return self._placeholder_line(y, width)
        line = self.scroll_offset.y + y
        if line >= len(self.lines):
            return Strip.blank(width)
        index = self.lines[line]
        e = listing.entries[index]
        base = Style()
        count_style = role("muted")
        if line == self.cursor:
            base = role("cursor") if self.has_focus else role("cursor-blurred")
            count_style = base if self.has_focus else base + role("muted")
        return entry_line(e, width, self._prefix(index), self.glyphs.ellipsis, base, count_style)

    def _placeholder_line(self, y: int, width: int) -> Strip:
        """How to fill an empty view (§7.2.5), wrapped, a line below the top."""
        text_of = PLACEHOLDERS.get(self.listing.view)
        if text_of is None:
            return Strip.blank(width)
        text = Text()
        text.append(text_of(), role("muted") + Style(italic=True))
        console = self.app.console
        wrapped = text.wrap(console, max(1, width - 2))
        if 1 <= y <= len(wrapped):
            part = wrapped[y - 1]
            return Strip.join([Strip.blank(1), Strip(list(part.render(console)), part.cell_len)]) \
                .adjust_cell_length(width)
        return Strip.blank(width)

    # ---------------------------------------------------------------- the cursor

    @property
    def lines_shown(self) -> int:
        return max(1, self.scrollable_content_region.height)

    def ensure_visible(self) -> None:
        top, shown = self.scroll_offset.y, self.lines_shown
        if self.cursor < top:
            self.scroll_to(y=self.cursor, animate=False, force=True)
        elif self.cursor >= top + shown:
            self.scroll_to(y=self.cursor - shown + 1, animate=False, force=True)

    def go(self, line: int) -> None:
        if not self.lines:
            return
        self.cursor = max(0, min(len(self.lines) - 1, line))
        self.ensure_visible()
        self.refresh()

    def action_move(self, d: int) -> None:
        self.go(self.cursor + d)

    def action_page(self, d: int) -> None:
        self.go(self.cursor + d * max(1, self.lines_shown - 1))

    def action_jump(self, line: int) -> None:
        self.go(line if line >= 0 else len(self.lines) - 1)

    def action_fold(self, unfold: bool) -> None:
        """→ unfolds a parent; ← folds it, or goes to the parent of a child (§7.2.4). Only where the view folds."""
        listing = self.listing
        index = self.current_index()
        if listing is None or not listing.collapsible or index is None:
            return
        parent = listing.parents[index]
        if parent is not None:
            if not unfold:
                self.go(self.lines.index(parent))
            return
        if not self._has_children(index) or (listing.entries[index].id in self.expanded) == unfold:
            return
        (self.expanded.add if unfold else self.expanded.discard)(listing.entries[index].id)
        self.sidebar.model.folded(index, unfold)
        self._layout()
        self.cursor = self.lines.index(index)
        self.ensure_visible()
        self.refresh()

    def action_choose(self) -> None:
        self.sidebar.choose(self.current_index())

    # ---------------------------------------------------------------- focus and the mouse

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        # the focus went elsewhere in the window, not to a popup over it: the cursor goes back to the entry the
        # list is filtered by, so that what is highlighted is what the list shows
        if self.app.screen is self.screen:
            self.back_to_current()
        self.refresh()

    def on_click(self, event: Click) -> None:
        line = self.scroll_offset.y + event.y
        if 0 <= line < len(self.lines):
            self.go(line)
            if event.button == 3:
                self.sidebar.action_menu()
            else:
                self.action_choose()


class ViewList(Static):
    """Every view, `●` at the shown one, under the entries of a wide and tall terminal (§5.2, §7.2.1). A click
    shows a view, as `[ ]` and `v` do."""

    def on_click(self, event: Click) -> None:
        if 0 <= event.y < len(VIEWS):
            self.parent.browse(VIEWS[event.y][0])


class Sidebar(Vertical):
    """The panel. `main` is the MainWindow: the Browser, the actions of the menu and the dialogs of later steps."""

    BINDINGS = [
        Binding("left_square_bracket", "view(-1)", _("Previous or next view"), show=False),
        Binding("right_square_bracket", "view(1)", _("Previous or next view"), show=False),
        Binding("v", "views", _("Views")),
        Binding(",".join(CONTEXT_KEYS), "menu", _("Menu")),
        Binding("plus", "group(True)", _("Install Group…"), show=False),
        Binding("minus", "group(False)", _("Remove Group…"), show=False),
        Binding("e", "edit", _("Edit Filter…"), show=False),
        # a pinned sidebar narrower or wider (WINDOW_PANES_SAVED)
        Binding("less_than_sign", "app.resize_panel('sidebar', -2)", _("Make the panel smaller or larger"),
                show=False),
        Binding("greater_than_sign", "app.resize_panel('sidebar', 2)", _("Make the panel smaller or larger"),
                show=False),
    ]

    def __init__(self, main, glyphs: Glyphs, **kw):
        super().__init__(**kw)
        self.main = main
        self.glyphs = glyphs
        self.model: SidebarModel = main.browser.sidebar
        self.entries = EntryList(self, glyphs, id="sidebar-body")
        self.views = ViewList("", id="views")
        self.model.listed.connect(self._listed)
        self.model.entry_changed.connect(lambda index, _entry: self.entries.redraw_entry(index))

    def compose(self) -> ComposeResult:
        yield self.entries
        yield self.views

    def on_mount(self) -> None:
        self.show_view()

    def on_resize(self) -> None:
        self.show_hints()

    def _listed(self, listing: Listing) -> None:
        self.entries.show(listing)
        self.show_view()

    # ---------------------------------------------------------------- drawing

    def show_view(self) -> None:
        """The title and the list of views at the bottom follow the shown view."""
        view = self.model.current_view
        self.border_title = view_label(view)
        views = Text()
        for i, (view_id, label, _builder) in enumerate(VIEWS):
            current = view_id == view
            views.append(("\n" if i else "") + (self.glyphs.bullet if current else " ") + " " + label,
                         "bold" if current else "")
        self.views.update(views)

    def show_hints(self) -> None:
        """`[ prev  ] next  v all` (§4.5), as much of it as the bottom border has room for."""
        pairs = [("[", pgettext("sidebar key hint", "prev")), ("]", pgettext("sidebar key hint", "next")),
                 ("v", pgettext("sidebar key hint", "all"))]
        room = self.size.width - 4  # the corners and a space on each side of the hints
        while pairs and hint(*pairs).cell_len > room:
            pairs.pop()
        self.border_subtitle = hint(*pairs)

    def refresh_colours(self) -> None:
        self.show_hints()

    # ---------------------------------------------------------------- views

    def browse(self, view_id: str) -> None:
        if view_id != self.model.current_view:
            self.model.browse(view_id)
            self.show_view()  # also before the catalog is there, when the model draws nothing

    def action_view(self, d: int) -> None:
        ids = [view_id for view_id, _label, _b in VIEWS]
        self.browse(ids[(ids.index(self.model.current_view) + d) % len(ids)])

    def action_views(self) -> None:
        items = [(view_id, label) for view_id, label, _b in VIEWS]

        def chosen(view_id: str | None) -> None:
            if view_id is not None:
                self.browse(view_id)
        self.app.push_screen(ChoiceList(_("Views"), items, self.model.current_view), chosen)

    # ---------------------------------------------------------------- entries

    def choose(self, index: int | None) -> None:
        """Filter by the entry; a slide-over has done its job then."""
        if index is None:
            return
        self.model.chosen(index)
        self.entries.current_id = self.model.current_entry_id
        if self.app.narrow:
            self.app.list_widget.focus()

    def action_menu(self) -> None:
        """The entry's context menu (§7.2.6), next to its line: Browser.sidebar_menu."""
        entry = self.entries.current_entry()
        items = self.main.sidebar_menu(entry)
        line = self.entries.cursor - self.entries.scroll_offset.y
        region = self.entries.region
        at = (region.x + 2, region.y + line + 1)

        def chosen(i: int | None) -> None:
            if i is not None:
                self.main.run_menu_item(items[i])
        self.app.push_screen(PopupMenu(entry.label if entry is not None else view_label(self.model.current_view),
                                       [self.main.menu_item(item) if item is not None else None for item in items],
                                       at), chosen)

    def action_group(self, install: bool) -> None:
        """`+` installs a group or an environment (upgrades an installed one), `-` removes it (§6.5)."""
        entry = self.entries.current_entry()
        if entry is not None and entry.group:
            self.main.change_group(entry.group, Action.INSTALL if install else Action.REMOVE)

    def action_edit(self) -> None:
        entry = self.entries.current_entry()
        if entry is not None and self.main.browser.custom_filters is not None:
            self.main.browser.custom_filters.activated(entry)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        entry = self.entries.current_entry()
        if action == "group":
            return bool(entry is not None and entry.group)
        if action == "edit":
            return entry is not None and entry.id.startswith("custom:")
        return True
