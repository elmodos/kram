"""'Apply changes' preview (kram.app.apply_review): everything the transaction will do, dependencies included,
before anything runs."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..app.apply_review import (
    ApplyReview,
    ChangeSection,
    Recommendations,
    RecRow,
    Resolver,
    change_sections,
)
from ..app.doc import Span
from ..core.model import TransactionPreview
from ..i18n import _
from .doc_html import spans_html
from .group_icons import group_icon

ERROR_STYLE = "color: #c03030; font-weight: bold"


def _fit_columns(tree: QTreeWidget, flexible: int = 0) -> None:
    """Column `flexible` takes the spare width as the window resizes, and gives up room first when it is short;
    the others fit their contents."""
    header = tree.header()
    header.setStretchLastSection(False)
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(flexible, QHeaderView.ResizeMode.Stretch)


class ChangesTree(QTreeWidget):
    """Every package a transaction touches, grouped by what happens to it."""

    def __init__(self, basearch: str = "x86_64", parent=None):
        super().__init__(parent)
        self._basearch = basearch
        self.setHeaderLabels([_("Package"), _("Version"), _("Repository"), _("Size")])
        # the name is what the user reads; a long version ("1:9.18.51^git20261003.d0a87358-2 → …") gives way instead
        _fit_columns(self, flexible=1)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # keeps both ends of "old → new"

    def fill(self, preview: TransactionPreview) -> None:
        self.show_sections(change_sections(preview, self._basearch))

    def show_sections(self, sections: list[ChangeSection]) -> None:
        self.clear()
        bold = QFont(self.font())
        bold.setBold(True)
        for section in sections:
            top = QTreeWidgetItem([section.title])
            top.setFont(0, bold)
            if section.color:
                top.setForeground(0, QBrush(QColor(section.color)))
            for r in section.rows:
                if section.groups:
                    row = QTreeWidgetItem(top, [r.name])
                    row.setIcon(0, group_icon(r.group_id))
                    row.setToolTip(0, r.group_id)
                    continue
                row = QTreeWidgetItem(top, [r.name, r.version, r.repo, r.size])
                row.setToolTip(1, r.version)  # in full, whatever is left of it on screen
                if r.warning:
                    row.setIcon(0, QIcon.fromTheme("dialog-warning"))
                    row.setToolTip(0, r.warning)
            self.addTopLevelItem(top)
            if section.groups:
                for item in (top, *(top.child(n) for n in range(top.childCount()))):
                    item.setFirstColumnSpanned(True)  # spanned only once in the tree; names must not widen the column
            else:
                top.setFirstColumnSpanned(True)  # a group title must not widen the name column
            top.setExpanded(True)


class RecommendationsList(QWidget):
    """The recommendations (kram.app.apply_review.Recommendations) with a checkbox each; `toggled` after the user
    changed one, for the owner to resolve again and `fill` the list with the result."""
    toggled = Signal()

    def __init__(self, exclude: set[str] | Recommendations, parent=None):
        super().__init__(parent)
        self.model = exclude if isinstance(exclude, Recommendations) else Recommendations(exclude)
        # a label over a plain list, like the changes above: a group box frame nests badly in some styles
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        hint = QLabel("<b>{}</b> {}".format(
            _("Recommended packages."),
            _("Not required, but suggested by the packages being installed. Uncheck what you do not want.")))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Recommended package"), _("Recommended by"), _("Adds")])
        _fit_columns(self.tree)
        self.tree.itemChanged.connect(self._on_changed)
        lay.addWidget(self.tree)

    @property
    def exclude(self) -> set[str]:
        return self.model.exclude

    def fill(self, preview: TransactionPreview) -> None:
        self.show_rows(*self.model.rows(preview))

    def show_rows(self, direct: list[RecRow], nested: list[RecRow]) -> None:
        tree = self.tree
        nested_open = any(tree.topLevelItem(i).childCount() and tree.topLevelItem(i).isExpanded()
                          for i in range(tree.topLevelItemCount()))
        tree.blockSignals(True)
        tree.clear()
        for row in direct:
            tree.addTopLevelItem(self._item(row))
        if nested:
            parent = QTreeWidgetItem([self.model.nested_title(len(nested))])
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for row in nested:
                parent.addChild(self._item(row))
            tree.addTopLevelItem(parent)
            parent.setExpanded(nested_open or not direct)
        tree.blockSignals(False)

    @staticmethod
    def _item(row: RecRow) -> QTreeWidgetItem:
        item = QTreeWidgetItem([row.label, row.by, row.adds])
        item.setData(0, Qt.ItemDataRole.UserRole, row.rec)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked if row.rec.checked else Qt.CheckState.Unchecked)
        item.setToolTip(0, row.tip)
        return item

    def _on_changed(self, item: QTreeWidgetItem, column: int) -> None:
        rec = item.data(0, Qt.ItemDataRole.UserRole)
        if rec is None or column != 0:
            return
        self.model.set_checked(rec, item.checkState(0) == Qt.CheckState.Checked)
        self.toggled.emit()


class ApplyDialog(QDialog):
    def __init__(self, preview: TransactionPreview, request: dict, basearch: str = "x86_64", parent=None,
                 resolve: Resolver | None = None):
        super().__init__(parent)
        self.setWindowTitle(_("Apply changes"))
        self.resize(820, 680)
        self.review = ApplyReview(preview, request, basearch, self, resolve)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>{}</b> {}".format(_("The following changes will be made."), _("Review the list before applying."))))

        # marked changes the resolver left out (see TransactionPreview.skipped): above the list, so it is not missed
        self.skipped_label = QLabel()
        self.skipped_label.setWordWrap(True)
        self.skipped_label.setStyleSheet(ERROR_STYLE)
        lay.addWidget(self.skipped_label)
        self.skipped_text = QPlainTextEdit()
        self.skipped_text.setReadOnly(True)
        self.skipped_text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.skipped_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.skipped_text.setFixedHeight(110)
        lay.addWidget(self.skipped_text)

        self.tree = ChangesTree(basearch)
        self.recs_box = RecommendationsList(self.review.recs)
        self.recs_box.toggled.connect(self.review.recs_changed)
        self.recs = self.recs_box.tree

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.tree)
        split.addWidget(self.recs_box)
        split.setChildrenCollapsible(False)
        split.setSizes([360, 240])
        lay.addWidget(split, 1)

        self.sizes = QLabel()
        lay.addWidget(self.sizes)
        # groups whose packages are already in place: why the list has no packages (see groups_only_note)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        lay.addWidget(self.note)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(ERROR_STYLE)
        lay.addWidget(self.warning)
        # not enough free space: Apply stays off
        self.space = QLabel()
        self.space.setWordWrap(True)
        self.space.setStyleSheet(ERROR_STYLE)
        self.space.setVisible(False)
        lay.addWidget(self.space)

        self.cmd = QPlainTextEdit()
        self.cmd.setReadOnly(True)
        self.cmd.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.cmd.setFixedHeight(80)
        box = QGroupBox(_("Equivalent command"))
        QVBoxLayout(box).addWidget(self.cmd)
        lay.addWidget(box)

        self.download_only = QCheckBox(_("Download packages only"))
        self.download_only.toggled.connect(self.review.set_download_only)
        lay.addWidget(self.download_only)

        buttons = QDialogButtonBox()
        self.ok = buttons.addButton(_("Apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        self.ok.setDefault(True)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.review.start()
        self.recs_box.setVisible(bool(preview.recommendations))

    @property
    def request(self) -> dict:
        """With the recommendations the user unchecked."""
        return self.review.request

    def done(self, result: int) -> None:
        self.review.close()  # deleted after use: results that arrive later are dropped
        super().done(result)

    # ---------------------------------------------------------------- ApplyReviewView

    def show_preview(self, preview, sections, recs) -> None:
        self.tree.show_sections(sections)
        self.recs_box.show_rows(*recs)

    def show_texts(self, sizes: list[Span], note: str, warning: str, skipped_title: str, skipped: str) -> None:
        self.sizes.setText(spans_html(sizes))
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.warning.setText(warning)
        self.warning.setVisible(bool(warning))
        self.skipped_label.setText(skipped_title)
        self.skipped_label.setVisible(bool(skipped_title))
        self.skipped_text.setPlainText(skipped)
        self.skipped_text.setVisible(bool(skipped))

    def show_space(self, text: str) -> None:
        self.space.setText(text)
        self.space.setVisible(bool(text))

    def show_command(self, text: str) -> None:
        self.cmd.setPlainText(text)

    def set_can_apply(self, on: bool) -> None:
        self.ok.setEnabled(on)

    def set_resolving(self, busy: bool, text: str | None = None) -> None:
        self.recs.setEnabled(not busy)
        if text is not None:
            self.sizes.setText(text)
