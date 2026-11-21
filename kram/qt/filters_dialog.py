"""Settings → Custom Filters (kram.app.filters_edit): create and edit named lists of conditions (Synaptic's filter editor)."""
from PySide6.QtCore import Signal
from PySide6.QtGui import QDoubleValidator, QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..app.filters_edit import FiltersEdit, value_editor
from ..core.custom_filters import (
    FIELD_LABELS,
    OP_LABELS,
    Condition,
    CustomFilter,
    Field,
    Op,
    ops_for,
)
from ..core.model import CatalogSnapshot
from ..i18n import _
from .qt_loop import QtScheduler
from .qt_ui import QtUi


def _discard(w: QWidget) -> None:
    """Take a widget out of its layout now; deleteLater alone leaves it on screen until the next event loop pass."""
    w.hide()
    w.setParent(None)
    w.deleteLater()


class ConditionRow(QWidget):
    changed = Signal()
    removeRequested = Signal(object)

    def __init__(self, cond: Condition, snap: CatalogSnapshot | None, parent=None):
        super().__init__(parent)
        self._snap = snap
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.field = QComboBox()
        for f in Field:
            self.field.addItem(FIELD_LABELS[f], f)
        self.op = QComboBox()
        self.value_box = QHBoxLayout()
        self.value: QWidget | None = None
        remove = QToolButton()
        remove.setIcon(QIcon.fromTheme("list-remove"))
        remove.setToolTip(_("Remove this condition"))
        remove.clicked.connect(lambda: self.removeRequested.emit(self))
        lay.addWidget(self.field)
        lay.addWidget(self.op)
        lay.addLayout(self.value_box, 1)
        lay.addWidget(remove)
        self.field.setCurrentIndex(self.field.findData(cond.field))
        self._rebuild(cond)
        self.field.currentIndexChanged.connect(lambda _i: (self._rebuild(None), self.changed.emit()))
        self.op.currentIndexChanged.connect(lambda _i: self.changed.emit())

    def _rebuild(self, cond: Condition | None) -> None:
        f: Field = self.field.currentData()
        self.op.blockSignals(True)
        self.op.clear()
        for op in ops_for(f):
            self.op.addItem(OP_LABELS[op], op)
        if cond is not None:
            self.op.setCurrentIndex(max(0, self.op.findData(cond.op)))
        self.op.blockSignals(False)

        if self.value is not None:
            _discard(self.value)
        value = cond.value if cond is not None else ""
        editor = value_editor(f, self._snap)
        if editor.options is None:
            w = QLineEdit(value)
            if editor.numeric:
                w.setValidator(QDoubleValidator(0, 1e9, 2, w))
            w.setPlaceholderText(editor.placeholder)
            w.textChanged.connect(lambda _t: self.changed.emit())
        else:
            w = QComboBox()
            w.setEditable(editor.editable)
            for v, label in editor.options:
                w.addItem(label, v)
            if value and w.findData(value) < 0:
                w.addItem(value, value)  # e.g. a repo that is disabled now
            w.setCurrentIndex(max(0, w.findData(value)) if value else 0)
            w.currentIndexChanged.connect(lambda _i: self.changed.emit())
            if w.isEditable():
                w.editTextChanged.connect(lambda _t: self.changed.emit())
        self.value = w
        self.value_box.addWidget(w)

    def condition(self) -> Condition:
        f: Field = self.field.currentData()
        w = self.value
        if isinstance(w, QLineEdit):
            value = w.text().strip()
        elif w.isEditable() and w.currentText() != w.itemText(w.currentIndex()):
            value = w.currentText().strip()
        else:
            value = w.currentData() or ""
        return Condition(f, self.op.currentData(), value)


class FiltersDialog(QDialog):
    """Edits a copy of the filters; `filters()` returns the result after accept()."""

    def __init__(self, filters: list[CustomFilter], snap: CatalogSnapshot | None, parent=None,
                 select: str | None = None, new: CustomFilter | None = None, resolve_provides=None):
        """`resolve_provides(queries, done, failed)` adds the answers to `snap.provides` in the background, then calls
        done, or failed when they cannot be had."""
        super().__init__(parent)
        self.setWindowTitle(_("Custom Filters"))
        self.resize(980, 560)
        self._snap = snap
        self.edit = FiltersEdit(filters, snap, self, QtScheduler(self), resolve_provides)
        self._rows: list[ConditionRow] = []

        lay = QVBoxLayout(self)
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._on_select)
        ll.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        add = QPushButton(QIcon.fromTheme("list-add"), _("New"))
        add.clicked.connect(lambda: self._add(CustomFilter(self.edit.unique(_("New filter")))))
        self.delete_btn = QPushButton(QIcon.fromTheme("edit-delete"), _("Delete"))
        self.delete_btn.clicked.connect(self._delete)
        buttons.addWidget(add)
        buttons.addWidget(self.delete_btn)
        ll.addLayout(buttons)
        split.addWidget(left)

        self.editor = QWidget()
        el = QVBoxLayout(self.editor)
        el.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.textEdited.connect(self._on_name)
        form.addRow(_("Name:"), self.name)
        self.match = QComboBox()
        self.match.addItem(_("all conditions"), True)
        self.match.addItem(_("any condition"), False)
        self.match.currentIndexChanged.connect(lambda _i: self.edit.changed())
        form.addRow(_("Show packages that match:"), self.match)
        el.addLayout(form)
        self.rows_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.rows_widget)
        el.addWidget(scroll, 1)
        row = QHBoxLayout()
        add_cond = QPushButton(QIcon.fromTheme("list-add"), _("Add condition"))
        add_cond.clicked.connect(lambda: self._add_row(Condition(Field.NAME, Op.CONTAINS, ""), focus=True))
        row.addWidget(add_cond)
        row.addStretch(1)
        self.count = QLabel()
        row.addWidget(self.count)
        el.addLayout(row)
        split.addWidget(self.editor)
        split.setSizes([260, 720])
        lay.addWidget(split, 1)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

        for f in self.edit.filters:
            self.list.addItem(f.name)
        if new is not None:
            new.name = self.edit.unique(new.name)
            self._add(new)
        else:
            names = [f.name for f in self.edit.filters]
            self.list.setCurrentRow(names.index(select) if select in names else (0 if names else -1))
        self._update_enabled()

    def filters(self) -> list[CustomFilter]:
        return self.edit.filters

    def current_name(self) -> str | None:
        return self.edit.current_name()

    def _update_count(self) -> None:
        self.edit.update_count()

    # ------------------------------------------------------------------ list

    def _add(self, f: CustomFilter) -> None:
        row = self.edit.add(f)
        self.list.addItem(f.name)
        self.list.setCurrentRow(row)
        self.name.setFocus()
        self.name.selectAll()
        self._update_enabled()

    def _delete(self) -> None:
        i = self.edit.delete()
        if i is None:
            return
        self.list.takeItem(i)
        self._on_select(self.list.currentRow())
        self._update_enabled()

    def _update_enabled(self) -> None:
        has = bool(self.edit.filters)
        self.editor.setEnabled(has)
        self.delete_btn.setEnabled(has)
        if not has:
            self.name.clear()
            self._clear_rows()
            self.count.clear()

    # ---------------------------------------------------------------- editor

    def _on_select(self, row: int) -> None:
        f = self.edit.select(row)
        if f is None:
            return
        self.name.setText(f.name)
        self.match.blockSignals(True)
        self.match.setCurrentIndex(0 if f.match_all else 1)
        self.match.blockSignals(False)
        self._clear_rows()
        for c in f.conditions:
            self._add_row(c)
        self.edit.update_count()

    def _clear_rows(self) -> None:
        for r in self._rows:
            _discard(r)
        self._rows = []

    def _add_row(self, cond: Condition, focus: bool = False) -> None:
        r = ConditionRow(cond, self._snap)
        r.changed.connect(self.edit.changed)
        r.removeRequested.connect(self._remove_row)
        self.rows_layout.insertWidget(len(self._rows), r)
        self._rows.append(r)
        if focus:
            r.value.setFocus()
            self.edit.changed()

    def _remove_row(self, r: ConditionRow) -> None:
        self._rows.remove(r)
        _discard(r)
        self.edit.changed()

    def _on_name(self, text: str) -> None:
        if 0 <= self.edit.current < len(self.edit.filters):
            self.list.item(self.edit.current).setText(text)

    def _accept(self) -> None:
        if problem := self.edit.problem():
            QtUi(self).warn(_("Custom Filters"), problem)
            return
        self.accept()

    # ---------------------------------------------------------------- FiltersView

    def editor_contents(self) -> tuple[str, bool, list[Condition]]:
        return self.name.text(), bool(self.match.currentData()), [r.condition() for r in self._rows]

    def show_count(self, text: str) -> None:
        self.count.setText(text)
