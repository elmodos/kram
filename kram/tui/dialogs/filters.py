"""The Custom Filters dialog (docs/TUI_SPEC.md §10.10): the `FiltersView` of kram.app.filters_edit.FiltersEdit, as
kram.gtk.dialogs.filters is. It edits a copy of the user's filters; OK gives them back to kram.app.custom_filters,
which saves them and shows the filter that was being edited.

The filters are a small table at the top (the GUIs' list on the left: a terminal is short of width more than of
lines), the editor of the one under its cursor below it: the name, "Show packages that match" as `(•)` choices, the
conditions one per line (field, operator and value, a `< - >` that removes the line) and, under them, Add condition
with the live count of the packages the filter matches. A field with a fixed set of values is a `Choice`; one whose
values may be typed over (a repository disabled now, an architecture not in the catalog) is a text line with a
`< ↓ >` that lists them. New and Delete act on the filters; Cancel and Esc drop every change, as in the GUIs.

The editor's widgets keep what they show in Python (`ConditionRow.condition`), so the presenter can read them back at
any time (`editor_contents`), mounted or not.

Narrow dialogs put the match choice under its label and give the field and the operator less room; nothing is
dropped.
"""
from collections.abc import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from ...app.filters_edit import FiltersEdit, value_editor
from ...core.custom_filters import FIELD_LABELS, OP_LABELS, Condition, CustomFilter, Field, Op, ops_for
from ...core.model import CatalogSnapshot
from ...i18n import _
from .. import loop
from ..palette import role
from ..table import Column, Table
from ..widgets import Button, ButtonBar, Choice, ChoiceList, Radio, hint
from .apply import Lines

FIELDS = list(Field)
FILTERS_SHOWN = 5  # rows of the filters' table before it scrolls: the editor needs the lines more
NARROW = 80        # cells of the dialog below which the editor is laid out for a narrow terminal


class ConditionRow(Horizontal):
    """A condition: its field, its operator, its value, and the button that removes it. `changed()` after the user
    changed any of them, `remove(row)` for the button."""

    DEFAULT_CSS = """
    ConditionRow { height: 1; width: 100%; }
    ConditionRow > Choice { margin-right: 1; }
    ConditionRow #field { width: 22; }
    ConditionRow #op { width: 18; }
    ConditionRow .value { width: 1fr; }
    ConditionRow #pick { margin-left: 1; }
    ConditionRow #remove { margin-left: 1; }
    """

    def __init__(self, cond: Condition, snap: CatalogSnapshot | None, changed: Callable[[], None],
                 remove: Callable[["ConditionRow"], None]):
        super().__init__(classes="condition")
        self.snap, self.changed, self.remove_row = snap, changed, remove
        self.field = cond.field
        self.op = cond.op
        self.value = cond.value
        self.options: list[tuple[str, str]] | None = None  # the field's values; None: free text
        self.typed = True  # the value is a text line, not a Choice
        self.focus_when_mounted = False  # a row just added: the value takes the focus once it is there

    # ---------------------------------------------------------------- the widgets

    def compose(self) -> ComposeResult:
        yield Choice([(f, FIELD_LABELS[f]) for f in FIELDS], self.field, id="field")
        yield Choice(self._ops(), self.op, id="op")
        yield from self._value_widgets()
        yield Button("-", id="remove")

    def _ops(self) -> list[tuple[Op, str]]:
        return [(op, OP_LABELS[op]) for op in ops_for(self.field)]

    def _value_widgets(self):
        """The value's editor for the field: a text line (with a `< ↓ >` that lists the values one may type over),
        or a Choice of the field's values. A stored value the choice does not know is kept as a choice of its own,
        as GTK does."""
        editor = value_editor(self.field, self.snap)
        self.options = editor.options
        self.typed = editor.options is None or editor.editable
        if self.typed:
            restrict = r"[0-9.,]*" if editor.numeric else None
            yield Input(self.value, placeholder=editor.placeholder, restrict=restrict, classes="value", id="text")
            if editor.options:
                yield Button(self.app.glyphs.down, id="pick")
            return
        options = list(editor.options)
        if self.value and self.value not in [v for v, _label in options]:
            options.append((self.value, self.value))
        self.options = options
        if self.value not in [v for v, _label in options]:
            self.value = options[0][0] if options else ""
        yield Choice(options, self.value, FIELD_LABELS[self.field], classes="value", id="values")

    def condition(self) -> Condition:
        op = self.op if self.op in ops_for(self.field) else ops_for(self.field)[0]
        return Condition(self.field, op, self.value.strip() if self.typed else self.value)

    def focus_value(self) -> None:
        self.query_one(".value").focus()

    def on_mount(self) -> None:
        if self.focus_when_mounted:
            self.focus_value()
            self.scroll_visible(animate=False)

    # ---------------------------------------------------------------- the user

    async def _rebuild_value(self) -> None:
        """Another field: its operators and its kind of value, the value emptied (as in GTK)."""
        ops = [op for op, _label in self._ops()]
        if self.op not in ops:
            self.op = ops[0]
        op_choice = self.query_one("#op", Choice)
        op_choice.options = self._ops()
        op_choice.value = self.op
        op_choice.refresh(layout=True)
        self.value = ""
        await self.query(".value, #pick").remove()
        await self.mount_all(list(self._value_widgets()), before=self.query_one("#remove"))

    async def on_choice_changed(self, event: Choice.Changed) -> None:
        event.stop()
        match event.choice.id:
            case "field":
                self.field = event.value
                await self._rebuild_value()
            case "op":
                self.op = event.value
            case "values":
                self.value = event.value
        self.changed()

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        if event.value != self.value:
            self.value = event.value
            self.changed()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "remove":
            self.remove_row(self)
        elif event.button.id == "pick" and self.options:
            def chosen(value: str | None) -> None:
                if value is not None:
                    self.query_one("#text", Input).value = value  # its Changed message stores it
            self.app.push_screen(ChoiceList(FIELD_LABELS[self.field], self.options, self.value), chosen)


class FiltersDialog(ModalScreen):
    """`done((filters, current name))` after OK, `done(None)` when cancelled: the screen's result, for
    kram.app.custom_filters.CustomFilters. `resolve_provides(queries, done, failed)` asks libdnf5 what provides a
    capability, for the count; `ui` says why the filters cannot be saved."""

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        # a text field's own ctrl+s would not take it, but the priority keeps it the dialog's from any field
        Binding("ctrl+s", "accept", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    FiltersDialog { align: center middle; }
    FiltersDialog #filters-box { height: 90%; }
    FiltersDialog #filter-list { height: 2; }
    FiltersDialog #editor { height: 1fr; margin-top: 1; }
    FiltersDialog .line { height: 1; }
    FiltersDialog .label { width: auto; margin-right: 1; }
    FiltersDialog #name { width: 1fr; }
    FiltersDialog #match-line { height: auto; margin-top: 1; }
    FiltersDialog .-narrow #match-line { layout: vertical; }
    /* the field and the operator give the value room in a narrow dialog (ConditionRow's own CSS is scoped to it) */
    FiltersDialog .-narrow ConditionRow #field { width: 15; }
    FiltersDialog .-narrow ConditionRow #op { width: 13; }
    FiltersDialog #conditions-title { margin-top: 1; }
    FiltersDialog #conditions { height: auto; max-height: 100%; }
    FiltersDialog #count-line { height: 1; margin-top: 1; }
    FiltersDialog #count { width: 1fr; margin-left: 2; }
    """

    def __init__(self, filters: list[CustomFilter], snap: CatalogSnapshot | None, ui, select: str | None = None,
                 new: CustomFilter | None = None, resolve_provides=None, scheduler=None):
        super().__init__()
        self.snap, self.ui = snap, ui
        self.select_name, self.new = select, new
        self.edit = FiltersEdit(filters, snap, self, scheduler or loop.TuiScheduler(), resolve_provides)
        self.rows: list[ConditionRow] = []
        self.name_text = ""
        self.match_all = True
        self.count = ""
        self._ready = False
        self._dismissing = False

    # ---------------------------------------------------------------- the widgets

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog filters", id="filters-box")
        box.border_title = _("Custom Filters")
        box.border_subtitle = hint(("tab", _("next")), ("ctrl+s", _("save")), ("esc", _("cancel")))
        with box:
            yield Table([Column("name", _("Name"), 10)], self._filter_cell, self.app.glyphs.ellipsis,
                        id="filter-list")
            yield Lines(id="no-filters")
            with Vertical(id="editor"):
                with Horizontal(classes="line"):
                    yield Static(_("Name:"), classes="label", markup=False)
                    yield Input(id="name")
                with Horizontal(id="match-line"):
                    yield Static(_("Show packages that match:"), classes="label", markup=False)
                    yield Radio([(True, _("all conditions")), (False, _("any condition"))], True, id="match")
                yield Lines(lambda: Text(_("Conditions"), role("header")), id="conditions-title")
                yield VerticalScroll(id="conditions")
                with Horizontal(id="count-line"):
                    yield Button(_("Add condition"), id="add-condition")
                    yield Lines(lambda: Text(self.count, role("muted")), id="count")
            with ButtonBar(classes="buttons"):
                with Horizontal():
                    yield Button(_("New"), id="new")
                    yield Button(_("Delete"), id="delete", variant="error")
                with Horizontal():
                    yield Button(_("OK"), id="ok", variant="primary")
                    yield Button(_("Cancel"), id="cancel")

    def on_mount(self) -> None:
        self._ready = True
        self._show_filters()
        names = [f.name for f in self.edit.filters]
        if self.new is not None:
            self.new.name = self.edit.unique(self.new.name)
            self._add(self.new)
        elif names:
            self._select(names.index(self.select_name) if self.select_name in names else 0)
            self.filter_table.focus()
        self._update_enabled()

    def on_resize(self) -> None:
        box = self.query_one("#filters-box")
        box.set_class(box.size.width < NARROW, "-narrow")

    @property
    def filter_table(self) -> Table:
        return self.query_one("#filter-list", Table)

    def _filter_cell(self, index: int, _column: str) -> Text:
        if index == self.edit.current:  # the name being typed, before it is stored
            return Text(self.name_text)
        return Text(self.edit.filters[index].name)

    def _show_filters(self) -> None:
        table = self.filter_table
        n = len(self.edit.filters)
        table.set_rows(list(range(n)))
        table.styles.height = max(1, min(n, FILTERS_SHOWN)) + 1  # and the header
        table.redraw()

    def _update_enabled(self) -> None:
        has = bool(self.edit.filters)
        self.query_one("#editor").display = has
        self.filter_table.display = has
        self.query_one("#delete", Button).set_enabled(has)
        self.query_one("#no-filters", Lines).show(
            lambda: Text("" if has else _("No filters yet. New makes one."), role("muted")))

    # ---------------------------------------------------------------- the editor

    def _select(self, index: int) -> None:
        """The editor shows the filter at `index` (the one before it stored first)."""
        f = self.edit.select(index)
        if f is None:
            return
        self.filter_table.select_key(index)
        self.name_text = f.name
        self.query_one("#name", Input).value = f.name
        self.match_all = f.match_all
        self.query_one("#match", Radio).set_value(f.match_all)
        self._set_rows(f.conditions)
        self.filter_table.redraw()
        self.edit.update_count()

    def _set_rows(self, conditions: list[Condition]) -> None:
        box = self.query_one("#conditions", VerticalScroll)
        box.remove_children()
        self.rows = [ConditionRow(c, self.snap, self._changed, self._remove_row) for c in conditions]
        if self.rows:
            box.mount_all(self.rows)

    def _add_row(self, cond: Condition) -> None:
        row = ConditionRow(cond, self.snap, self._changed, self._remove_row)
        row.focus_when_mounted = True
        self.rows.append(row)
        self.query_one("#conditions", VerticalScroll).mount(row)
        self._changed()

    def _remove_row(self, row: ConditionRow) -> None:
        if row in self.rows:
            i = self.rows.index(row)
            self.rows.remove(row)
            row.remove()
            if self.rows:
                self.call_after_refresh(self.rows[min(i, len(self.rows) - 1)].focus_value)
            else:
                self.query_one("#add-condition", Button).focus()
        self._changed()

    def _changed(self) -> None:
        self.edit.changed()

    def _add(self, f: CustomFilter) -> None:
        index = self.edit.add(f)
        self._show_filters()
        self._select(index)
        self._update_enabled()
        self.query_one("#name", Input).focus()

    def _delete(self) -> None:
        i = self.edit.delete()
        if i is None:
            return
        self._show_filters()
        if self.edit.filters:
            self._select(min(i, len(self.edit.filters) - 1))
        else:
            self.name_text = ""
            self._set_rows([])
            self.count = ""
            self.query_one("#new", Button).focus()
        self._update_enabled()

    # ---------------------------------------------------------------- the user

    def on_table_highlighted(self, event: Table.Highlighted) -> None:
        """The cursor moved to another filter. Its row now, not the message's: a message posted before the editor
        moved on its own (a new filter, the one asked for at the start) is out of date, and following it would move
        the cursor back and forth."""
        event.stop()
        key = self.filter_table.current
        if key is not None and key != self.edit.current:
            self._select(key)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "name":
            return
        event.stop()
        if event.value != self.name_text:
            self.name_text = event.value
            self.filter_table.redraw()
            self._changed()

    def on_radio_changed(self, event: Radio.Changed) -> None:
        event.stop()
        self.match_all = bool(event.value)
        self._changed()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        match event.button.id:
            case "new":
                self._add(CustomFilter(self.edit.unique(_("New filter"))))
            case "delete":
                self._delete()
            case "add-condition":
                self._add_row(Condition(Field.NAME, Op.CONTAINS, ""))
            case "ok":
                self.action_accept()
            case "cancel":
                self.action_cancel()

    def action_accept(self) -> None:
        if problem := self.edit.problem():
            self.ui.warn(_("Custom Filters"), problem)
            return
        self._close((self.edit.filters, self.edit.current_name()))

    def action_cancel(self) -> None:
        self._close(None)

    def _close(self, result) -> None:
        if not self._dismissing and self.app.screen is self:
            self._dismissing = True
            self.dismiss(result)

    # ---------------------------------------------------------------- FiltersView

    def editor_contents(self) -> tuple[str, bool, list[Condition]]:
        return self.name_text, self.match_all, [r.condition() for r in self.rows]

    def show_count(self, text: str) -> None:
        self.count = text
        if self._ready and not self._dismissing:
            self.query_one("#count", Lines).refresh(layout=True)
