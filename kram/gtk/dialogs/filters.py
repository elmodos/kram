"""Settings → Custom Filters for GTK (kram.app.filters_edit): create and edit named lists of conditions (Synaptic's
filter editor)."""
from collections.abc import Callable

from gi.repository import Adw, Gtk, Pango

from ...app.filters_edit import FiltersEdit, value_editor
from ...core.custom_filters import FIELD_LABELS, OP_LABELS, Condition, CustomFilter, Field, Op, ops_for
from ...core.model import CatalogSnapshot
from ...i18n import _
from ..loop import GtkScheduler
from ..ui_port import GtkUi
from .common import frame, standard_button

FIELDS = list(Field)


class ConditionRow(Gtk.Box):
    """A condition: field, operator, value. `on_changed()` after the user changed it, `on_remove(row)` for its
    remove button."""

    def __init__(self, cond: Condition, snap: CatalogSnapshot | None):
        super().__init__(spacing=6)
        self._snap = snap
        self.on_changed: Callable[[], None] = lambda: None
        self.on_remove: Callable[["ConditionRow"], None] = lambda row: None
        self.field = Gtk.DropDown.new_from_strings([FIELD_LABELS[f] for f in FIELDS])
        self.field.set_selected(FIELDS.index(cond.field))
        self.op = Gtk.DropDown()
        self._ops: list[Op] = []
        self.value_slot = Gtk.Box(hexpand=True)
        self.value: Gtk.Widget | None = None
        self._options: list[tuple[str, str]] | None = None
        remove = Gtk.Button(icon_name="list-remove-symbolic", tooltip_text=_("Remove this condition"))
        remove.add_css_class("flat")
        remove.connect("clicked", lambda _b: self.on_remove(self))
        for w in (self.field, self.op, self.value_slot, remove):
            self.append(w)
        self._rebuild(cond)
        self.field.connect("notify::selected", lambda *_a: (self._rebuild(None), self.on_changed()))
        self._op_handler = self.op.connect("notify::selected", lambda *_a: self.on_changed())

    def _rebuild(self, cond: Condition | None) -> None:
        f = FIELDS[self.field.get_selected()]
        self._ops = ops_for(f)
        handler = getattr(self, "_op_handler", None)
        if handler is not None:
            self.op.handler_block(handler)
        self.op.set_model(Gtk.StringList.new([OP_LABELS[op] for op in self._ops]))
        self.op.set_selected(self._ops.index(cond.op) if cond is not None and cond.op in self._ops else 0)
        if handler is not None:
            self.op.handler_unblock(handler)

        if self.value is not None:
            self.value_slot.remove(self.value)
        value = cond.value if cond is not None else ""
        editor = value_editor(f, self._snap)
        self._options = editor.options
        if editor.options is None or editor.editable:
            # free text, or a choice that may be typed over (a repository that is disabled now, i686)
            entry = Gtk.Entry(text=value, placeholder_text=editor.placeholder, hexpand=True)
            if editor.numeric:
                entry.set_input_purpose(Gtk.InputPurpose.NUMBER)
            entry.connect("changed", lambda _e: self.on_changed())
            widget: Gtk.Widget = entry
            if editor.options:
                widget = Gtk.Box(hexpand=True)
                widget.add_css_class("linked")
                widget.append(entry)
                widget.append(self._choices_button(entry, editor.options))
            self.entry = entry
        else:
            options = list(editor.options)
            if value and value not in [v for v, _label in options]:
                options.append((value, value))
            self._options = options
            widget = Gtk.DropDown.new_from_strings([label for _v, label in options])
            widget.set_hexpand(True)
            values = [v for v, _label in options]
            widget.set_selected(values.index(value) if value in values else 0)
            widget.connect("notify::selected", lambda *_a: self.on_changed())
            self.entry = None
        self.value = widget
        self.value_slot.append(widget)

    @staticmethod
    def _choices_button(entry: Gtk.Entry, options: list[tuple[str, str]]) -> Gtk.MenuButton:
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("navigation-sidebar")
        for value, label in options:
            row = Gtk.ListBoxRow(child=Gtk.Label(label=label, xalign=0))
            row.value = value
            box.append(row)
        popover = Gtk.Popover(child=Gtk.ScrolledWindow(child=box, max_content_height=320,
                                                       propagate_natural_height=True,
                                                       hscrollbar_policy=Gtk.PolicyType.NEVER))

        def chosen(_box, row) -> None:
            entry.set_text(row.value)
            popover.popdown()
        box.connect("row-activated", chosen)
        return Gtk.MenuButton(popover=popover)

    def focus_value(self) -> None:
        (self.entry or self.value).grab_focus()

    def condition(self) -> Condition:
        f = FIELDS[self.field.get_selected()]
        op = self._ops[self.op.get_selected()] if self._ops else Op.CONTAINS
        if self.entry is not None:
            value = self.entry.get_text().strip()
        else:
            value = self._options[self.value.get_selected()][0] if self._options else ""
        return Condition(f, op, value)


class FiltersDialog(Adw.Dialog):
    """Edits a copy of the filters; `done((filters, current name))` after OK, `done(None)` when cancelled."""

    def __init__(self, filters: list[CustomFilter], snap: CatalogSnapshot | None,
                 done: Callable[[tuple[list[CustomFilter], str | None] | None], None],
                 select: str | None = None, new: CustomFilter | None = None, resolve_provides=None):
        """`resolve_provides(queries, done, failed)` adds the answers to `snap.provides` in the background, then calls
        done, or failed when they cannot be had."""
        super().__init__(title=_("Custom Filters"), content_width=980, content_height=560)
        self._snap = snap
        self._done = done
        self._accepted = False
        self.ui = GtkUi(self)
        self.edit = FiltersEdit(filters, snap, self, GtkScheduler(), resolve_provides)
        self._rows: list[ConditionRow] = []
        header, body = frame(self)
        cancel = standard_button("_Cancel")
        cancel.connect("clicked", lambda _b: self.close())
        header.pack_start(cancel)
        ok = standard_button("_OK")
        ok.add_css_class("suggested-action")
        ok.connect("clicked", self._accept)
        header.pack_end(ok)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.list.add_css_class("navigation-sidebar")
        self._select_handler = self.list.connect("row-selected", self._on_select)
        left.append(Gtk.ScrolledWindow(child=self.list, vexpand=True))
        buttons = Gtk.Box(spacing=6)
        add = Gtk.Button(child=Adw.ButtonContent(label=_("New"), icon_name="list-add-symbolic"))
        add.connect("clicked", lambda _b: self._add(CustomFilter(self.edit.unique(_("New filter")))))
        self.delete_btn = Gtk.Button(child=Adw.ButtonContent(label=_("Delete"), icon_name="user-trash-symbolic"))
        self.delete_btn.connect("clicked", lambda _b: self._delete())
        buttons.append(add)
        buttons.append(self.delete_btn)
        left.append(buttons)

        self.editor = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_start=12)
        form = Gtk.Grid(column_spacing=12, row_spacing=6)
        form.attach(Gtk.Label(label=_("Name:"), xalign=0), 0, 0, 1, 1)
        self.name = Gtk.Entry(hexpand=True)
        self.name.connect("changed", self._on_name)
        form.attach(self.name, 1, 0, 1, 1)
        form.attach(Gtk.Label(label=_("Show packages that match:"), xalign=0), 0, 1, 1, 1)
        self.match = Gtk.DropDown.new_from_strings([_("all conditions"), _("any condition")])
        self.match.set_halign(Gtk.Align.START)
        self._match_handler = self.match.connect("notify::selected", lambda *_a: self.edit.changed())
        form.attach(self.match, 1, 1, 1, 1)
        self.editor.append(form)
        self.rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.editor.append(Gtk.ScrolledWindow(child=self.rows_box, vexpand=True,
                                              hscrollbar_policy=Gtk.PolicyType.NEVER))
        row = Gtk.Box(spacing=6)
        add_cond = Gtk.Button(child=Adw.ButtonContent(label=_("Add condition"), icon_name="list-add-symbolic"))
        add_cond.connect("clicked", lambda _b: self._add_row(Condition(Field.NAME, Op.CONTAINS, ""), focus=True))
        row.append(add_cond)
        self.count = Gtk.Label(xalign=1, hexpand=True)
        self.count.add_css_class("dim-label")
        row.append(self.count)
        self.editor.append(row)

        split = Gtk.Paned(start_child=left, end_child=self.editor, position=260, shrink_start_child=False,
                          resize_start_child=False, vexpand=True)
        body.append(split)

        self._loading = False
        for f in self.edit.filters:
            self.list.append(self._list_row(f.name))
        if new is not None:
            new.name = self.edit.unique(new.name)
            self._add(new)
        else:
            names = [f.name for f in self.edit.filters]
            if names:
                self.list.select_row(self.list.get_row_at_index(names.index(select) if select in names else 0))
        self.connect("closed", self._closed)
        self._update_enabled()

    @staticmethod
    def _list_row(name: str) -> Gtk.ListBoxRow:
        return Gtk.ListBoxRow(child=Gtk.Label(label=name, xalign=0, ellipsize=Pango.EllipsizeMode.END))

    def filters(self) -> list[CustomFilter]:
        return self.edit.filters

    def current_name(self) -> str | None:
        return self.edit.current_name()

    # ------------------------------------------------------------------ list

    def _add(self, f: CustomFilter) -> None:
        row = self.edit.add(f)
        self.list.append(self._list_row(f.name))
        self.list.select_row(self.list.get_row_at_index(row))
        self.name.grab_focus()
        self._update_enabled()

    def _delete(self) -> None:
        i = self.edit.delete()
        if i is None:
            return
        with self.list.handler_block(self._select_handler):
            self.list.remove(self.list.get_row_at_index(i))
        if (row := self.list.get_row_at_index(min(i, len(self.edit.filters) - 1))) is not None:
            self.list.select_row(row)
            self._on_select(self.list, row)  # a row that was selected already says nothing
        self._update_enabled()

    def _update_enabled(self) -> None:
        has = bool(self.edit.filters)
        self.editor.set_sensitive(has)
        self.delete_btn.set_sensitive(has)
        if not has:
            self._loading = True
            self.name.set_text("")
            self._loading = False
            self._clear_rows()
            self.count.set_text("")

    # ---------------------------------------------------------------- editor

    def _on_select(self, _list, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        f = self.edit.select(row.get_index())
        if f is None:
            return
        self._loading = True  # the editor shows the filter: no renaming of the list's rows
        self.name.set_text(f.name)
        self._loading = False
        with self.match.handler_block(self._match_handler):
            self.match.set_selected(0 if f.match_all else 1)
        self._clear_rows()
        for c in f.conditions:
            self._add_row(c)
        self.edit.update_count()

    def _clear_rows(self) -> None:
        for r in self._rows:
            self.rows_box.remove(r)
        self._rows = []

    def _add_row(self, cond: Condition, focus: bool = False) -> None:
        r = ConditionRow(cond, self._snap)
        r.on_changed = self.edit.changed
        r.on_remove = self._remove_row
        self.rows_box.append(r)
        self._rows.append(r)
        if focus:
            r.focus_value()
            self.edit.changed()

    def _remove_row(self, r: ConditionRow) -> None:
        self._rows.remove(r)
        self.rows_box.remove(r)
        self.edit.changed()

    def _on_name(self, entry: Gtk.Entry) -> None:
        if self._loading:
            return
        if 0 <= self.edit.current < len(self.edit.filters):
            self.list.get_row_at_index(self.edit.current).get_child().set_text(entry.get_text())

    def _accept(self, _button) -> None:
        if problem := self.edit.problem():
            self.ui.warn(_("Custom Filters"), problem)
            return
        self._accepted = True
        self.close()

    def _closed(self, _dialog) -> None:
        done, self._done = self._done, None
        if done is not None:
            done((self.edit.filters, self.edit.current_name()) if self._accepted else None)

    # ---------------------------------------------------------------- FiltersView

    def editor_contents(self) -> tuple[str, bool, list[Condition]]:
        return self.name.get_text(), self.match.get_selected() == 0, [r.condition() for r in self._rows]

    def show_count(self, text: str) -> None:
        self.count.set_text(text)

