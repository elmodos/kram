"""Repositories → Mirrors… (kram.app.mirrors): the mirrors of one repository with a speed test; choose one to pin the
repository to it, or go back to letting libdnf5 choose."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..app.mirrors import MirrorLine, Mirrors, dialog_title
from ..core.mirrors import MirrorSource
from ..core.model import RepoInfo
from ..i18n import _
from .qt_loop import post
from .qt_ui import QtUi

COL_MIRROR, COL_COUNTRY, COL_PROTOCOL, COL_RESPONSE, COL_SPEED, COL_NOTE = range(6)
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class MirrorsDialog(QDialog):
    def __init__(self, repo: RepoInfo, source: MirrorSource, fastestmirror: bool, parent=None, *, on_choice=None,
                 **network):
        """`on_choice(choice)` applies a choice while the dialog stays open; `set_state` then shows the new state.
        `network` replaces the fetching and the speed test, for the tests (see kram.app.mirrors.Mirrors)."""
        super().__init__(parent)
        self.mirrors = Mirrors(repo.id, source, fastestmirror, self, QtUi(self), post, on_choice=on_choice, **network)
        self.setWindowTitle(dialog_title(repo))
        self.resize(900, 540)

        lay = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        t = self.table = QTableWidget(0, 6)
        t.setHorizontalHeaderLabels([_("Mirror"), _("Country"), _("Protocol"), _("Response"), _("Speed"), _("Note")])
        t.verticalHeader().hide()
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = t.horizontalHeader()
        header.setSectionResizeMode(COL_MIRROR, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_NOTE, QHeaderView.ResizeMode.ResizeToContents)
        for col, width in ((COL_COUNTRY, 70), (COL_PROTOCOL, 70), (COL_RESPONSE, 90), (COL_SPEED, 100)):
            t.setColumnWidth(col, width)
        t.itemSelectionChanged.connect(self._update_buttons)
        t.itemDoubleClicked.connect(self._use_selected)
        lay.addWidget(t, 1)

        row = QHBoxLayout()
        # bound methods, not lambdas: see kram.qt.repos_dialog
        self.test_btn = QPushButton(QIcon.fromTheme("speedometer", QIcon.fromTheme("media-playback-start")),
                                    _("Test Speed"))
        self.test_btn.clicked.connect(self.mirrors.toggle_test)
        self.use_btn = QPushButton(QIcon.fromTheme("dialog-ok-apply", QIcon.fromTheme("dialog-ok")),
                                   _("Use Selected Mirror"))
        self.use_btn.clicked.connect(self._use_selected)
        self.automatic_btn = QPushButton(QIcon.fromTheme("view-refresh"), _("Automatic"))
        self.automatic_btn.clicked.connect(self.mirrors.use_automatic)
        for b in (self.test_btn, self.use_btn, self.automatic_btn):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        fastest = QHBoxLayout()
        self.fastest_label = QLabel()
        self.fastest_label.setWordWrap(True)
        self.fastest_btn = QPushButton()
        self.fastest_btn.clicked.connect(self.mirrors.toggle_fastest)
        fastest.addWidget(self.fastest_label, 1)
        fastest.addWidget(self.fastest_btn)
        lay.addLayout(fastest)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.mirrors.start()
        self._update_buttons()

    choice = property(lambda self: self.mirrors.choice)  # the choice being applied, until set_state

    def set_state(self, source: MirrorSource, fastestmirror: bool) -> None:
        """What is configured now: after a choice was applied, the dialog shows it."""
        self.mirrors.update(source, fastestmirror)
        self._update_buttons()

    # ---------------------------------------------------------------- MirrorsView

    def show_lines(self, lines: list[MirrorLine]) -> None:
        t = self.table
        selected = self._selected_url()
        t.setRowCount(len(lines))
        dim = self.palette().placeholderText()
        for i, ln in enumerate(lines):
            cells = [(ln.name, None), (ln.country, None), (ln.protocol, None), (ln.response, RIGHT),
                     (ln.speed, RIGHT), (ln.note, None)]
            for col, (text, align) in enumerate(cells):
                item = QTableWidgetItem(text)
                if align is not None:
                    item.setTextAlignment(align)
                if col == COL_MIRROR:
                    item.setData(Qt.ItemDataRole.UserRole, ln.mirror.url)
                    item.setToolTip(ln.mirror.url)
                if ln.current:
                    font = QFont(item.font())
                    font.setBold(True)
                    item.setFont(font)
                if ln.failed:
                    item.setForeground(dim)
                t.setItem(i, col, item)
            if ln.mirror.url == selected:
                t.selectRow(i)
        self._update_buttons()

    def show_status(self, text: str) -> None:
        self.status.setText(text)

    def set_testing(self, on: bool) -> None:
        self.test_btn.setText(_("Stop Test") if on else _("Test Speed"))
        self._update_buttons()

    def show_fastest(self, text: str, button: str) -> None:
        self.fastest_label.setText(text)
        self.fastest_btn.setText(button)

    # ---------------------------------------------------------------- the buttons

    def _selected_url(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), COL_MIRROR).data(Qt.ItemDataRole.UserRole) if rows else None

    def _use_selected(self, *_args) -> None:
        self.mirrors.use(self._selected_url())

    def _update_buttons(self) -> None:
        state = self.mirrors.buttons(self._selected_url())
        self.test_btn.setEnabled(state.test or self.mirrors.testing)
        for button, action in ((self.use_btn, state.use), (self.automatic_btn, state.automatic)):
            button.setEnabled(action.enabled)
            button.setToolTip(action.tooltip)

    def done(self, result: int) -> None:
        self.mirrors.close()  # a test that is still running stops with the dialog
        super().done(result)

