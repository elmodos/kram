"""Settings → Custom Filters: create and edit named lists of conditions (Synaptic's filter editor)."""
import copy

from PySide6.QtCore import QTimer, Signal
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
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.custom_filters import (
    FIELD_LABELS,
    OP_LABELS,
    Condition,
    CustomFilter,
    Field,
    Op,
    choices,
    ops_for,
    provides_queries,
)
from ..core.model import CatalogSnapshot
from ..i18n import _, ngettext

EDITABLE_CHOICES = (Field.REPO, Field.ARCH)  # values may not be in the current catalog (disabled repo, i686)
RECOUNT_MS = 200


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
        options = choices(f, self._snap)
        if options is None:
            w = QLineEdit(value)
            if f is Field.SIZE:
                w.setValidator(QDoubleValidator(0, 1e9, 2, w))
                w.setPlaceholderText(_("megabytes"))
            elif f is Field.PROVIDES:
                w.setPlaceholderText(_("capability, e.g. application()"))
            else:
                w.setPlaceholderText(_("text"))
            w.textChanged.connect(lambda _t: self.changed.emit())
        else:
            w = QComboBox()
            w.setEditable(f in EDITABLE_CHOICES)
            for v, label in options:
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
        """`resolve_provides(queries, done)` adds the answers to `snap.provides` in the background, then calls done."""
        super().__init__(parent)
        self.setWindowTitle(_("Custom Filters"))
        self.resize(980, 560)
        self._snap = snap
        self._resolve_provides = resolve_provides
        self._asked: set[tuple[str, bool]] = set()
        self._filters = copy.deepcopy(filters)
        self._current = -1
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
        add.clicked.connect(lambda: self._add(CustomFilter(self._unique(_("New filter")))))
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
        self.match.currentIndexChanged.connect(self._on_changed)
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

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

        self._recount = QTimer(self, singleShot=True, interval=RECOUNT_MS)
        self._recount.timeout.connect(self._update_count)

        for f in self._filters:
            self.list.addItem(f.name)
        if new is not None:
            new.name = self._unique(new.name)
            self._add(new)
        else:
            names = [f.name for f in self._filters]
            self.list.setCurrentRow(names.index(select) if select in names else (0 if names else -1))
        self._update_enabled()

    def filters(self) -> list[CustomFilter]:
        return self._filters

    def current_name(self) -> str | None:
        return self._filters[self._current].name if 0 <= self._current < len(self._filters) else None

    # ------------------------------------------------------------------ list

    def _unique(self, base: str) -> str:
        names = {f.name for f in self._filters}
        name, n = base, 2
        while name in names:
            name, n = f"{base} {n}", n + 1
        return name

    def _add(self, f: CustomFilter) -> None:
        self._store()
        self._filters.append(f)
        self.list.addItem(f.name)
        self.list.setCurrentRow(len(self._filters) - 1)
        self.name.setFocus()
        self.name.selectAll()
        self._update_enabled()

    def _delete(self) -> None:
        i = self._current
        if not 0 <= i < len(self._filters):
            return
        self._current = -1  # nothing to store back
        del self._filters[i]
        self.list.takeItem(i)
        self._on_select(self.list.currentRow())
        self._update_enabled()

    def _update_enabled(self) -> None:
        has = bool(self._filters)
        self.editor.setEnabled(has)
        self.delete_btn.setEnabled(has)
        if not has:
            self.name.clear()
            self._clear_rows()
            self.count.clear()

    # ---------------------------------------------------------------- editor

    def _on_select(self, row: int) -> None:
        self._store()
        self._current = row
        if not 0 <= row < len(self._filters):
            return
        f = self._filters[row]
        self.name.setText(f.name)
        self.match.blockSignals(True)
        self.match.setCurrentIndex(0 if f.match_all else 1)
        self.match.blockSignals(False)
        self._clear_rows()
        for c in f.conditions:
            self._add_row(c)
        self._update_count()

    def _clear_rows(self) -> None:
        for r in self._rows:
            _discard(r)
        self._rows = []

    def _add_row(self, cond: Condition, focus: bool = False) -> None:
        r = ConditionRow(cond, self._snap)
        r.changed.connect(self._on_changed)
        r.removeRequested.connect(self._remove_row)
        self.rows_layout.insertWidget(len(self._rows), r)
        self._rows.append(r)
        if focus:
            r.value.setFocus()
            self._on_changed()

    def _remove_row(self, r: ConditionRow) -> None:
        self._rows.remove(r)
        _discard(r)
        self._on_changed()

    def _on_name(self, text: str) -> None:
        if 0 <= self._current < len(self._filters):
            self.list.item(self._current).setText(text)

    def _on_changed(self, *_args) -> None:
        self._recount.start()

    def _store(self) -> None:
        """Write the editor's state back into the current filter."""
        if not 0 <= self._current < len(self._filters):
            return
        f = self._filters[self._current]
        f.name = self.name.text().strip()
        f.match_all = bool(self.match.currentData())
        f.conditions = [r.condition() for r in self._rows]

    def _update_count(self) -> None:
        self._store()
        if self._snap is None or not 0 <= self._current < len(self._filters):
            self.count.clear()
            return
        current = self._filters[self._current]
        if missing := provides_queries([current]) - self._snap.provides.keys():
            self.count.setText(_("Counting…"))
            if self._resolve_provides is not None and (new := missing - self._asked):
                self._asked |= new
                self._resolve_provides(new, self._update_count)
            return
        pred = current.compile(self._snap)
        n = sum(1 for r in self._snap.rows if pred(r))
        self.count.setText(ngettext("{n} package matches", "{n} packages match", n).format(n=n))

    def _accept(self) -> None:
        self._store()
        names = [f.name for f in self._filters]
        problem = None
        if any(not n for n in names):
            problem = _("Every filter needs a name.")
        elif len(set(names)) != len(names):
            problem = _("Two filters have the same name.")
        if problem:
            QMessageBox.warning(self, _("Custom Filters"), problem)
            return
        self.accept()
