"""The toolbar's "Fedora N" button (kram.app.upgrade): what moving to that release would do."""
import html
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..app.icons import INFO, STATE_ICONS
from ..app.progress import Bar
from ..app.upgrade import Finding, UpgradeCheck, have_text, intro
from ..core import distro, proc
from ..core.model import CatalogSnapshot
from ..i18n import _
from .icons import icon
from .qt_loop import post

LOG_HEIGHT = 150


class UpgradeDialog(QDialog):
    """Kept by the main window for the session, so a finished check is not repeated when it is opened again."""

    def __init__(self, target: int, running: int, running_eol: str, snapshot: CatalogSnapshot, dnf, parent=None):
        super().__init__(parent)
        self.target = target
        self.setWindowTitle(f"Fedora {target}")
        self.resize(760, 600)
        self.upgrade = UpgradeCheck(target, dnf, post, self)
        self._result_items: list[QTreeWidgetItem] = []

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>" + html.escape(_("Fedora {version} is available").format(version=target)) + "</b>"))
        info = QLabel(have_text(running, running_eol))
        info.setWordWrap(True)
        lay.addWidget(info)

        panel = QHBoxLayout()
        self.check = QPushButton(QIcon.fromTheme("security-high", QIcon.fromTheme("edit-find")), _("Check"))
        self.check.setDefault(True)  # the main action here
        self.check.clicked.connect(self.upgrade.start)
        panel.addWidget(self.check)
        self.cancel_button = QPushButton(QIcon.fromTheme("dialog-cancel"), _("Cancel"))
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(self.upgrade.cancel)
        self.cancel_button.hide()  # takes the place of Check while one runs
        panel.addWidget(self.cancel_button)
        width = max(self.check.sizeHint().width(), self.cancel_button.sizeHint().width())
        self.check.setMinimumWidth(width)  # the text beside them does not jump
        self.cancel_button.setMinimumWidth(width)
        self.status = QLabel(intro(target))
        self.status.setWordWrap(True)
        panel.addWidget(self.status, 1)
        lay.addLayout(panel)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.copr_item = QTreeWidgetItem(self.tree, [_("COPR projects: checking…")])
        self.copr_item.setIcon(0, icon(STATE_ICONS[INFO]))
        lay.addWidget(self.tree, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log.setFixedHeight(LOG_HEIGHT)
        self.log.hide()  # nothing to show before the first check
        lay.addWidget(self.log)

        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.hide()
        lay.addWidget(self.busy)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)  # no effect during a check, see done()
        bottom = QHBoxLayout()
        self.notes_button = self._link_button("documentinfo", _("Release notes"),
                                              distro.RELEASE_NOTES_URL.format(version=target))
        bottom.addWidget(self.notes_button)
        self.guide_button = self._link_button("help-contents", _("Upgrade guide"), distro.UPGRADE_GUIDE_URL)
        bottom.addWidget(self.guide_button)
        self.program = distro.upgrade_program(os.environ.get("XDG_CURRENT_DESKTOP", ""))
        self.open_program = None
        if self.program is not None:
            program_icon = QIcon.fromTheme(self.program.icon, QIcon.fromTheme("system-software-install"))
            self.open_program = QPushButton(program_icon, _("Open {program}").format(program=self.program.name))
            self.open_program.clicked.connect(lambda: proc.spawn_detached(self.program.argv))
            bottom.addWidget(self.open_program)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        lay.addLayout(bottom)

        self.upgrade.ask_copr(snapshot)

    @staticmethod
    def _link_button(icon_name: str, text: str, url: str) -> QPushButton:
        button = QPushButton(QIcon.fromTheme(icon_name, QIcon.fromTheme("help-about")), text)
        button.setAutoDefault(False)
        button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        return button

    def done(self, result: int) -> None:
        if not self.upgrade.running:  # Esc and the window's close button too: a check is left with Cancel
            super().done(result)

    # ---------------------------------------------------------------- UpgradeView

    @staticmethod
    def _fill(item: QTreeWidgetItem, finding: Finding) -> None:
        item.setText(0, finding.title)
        item.setIcon(0, icon(STATE_ICONS[finding.kind]))
        for line in finding.lines:
            QTreeWidgetItem(item, [line])
        if finding.lines:
            item.setExpanded(finding.expanded)

    def show_copr(self, finding: Finding, failed: Finding | None) -> None:
        self._fill(self.copr_item, finding)
        if failed is not None:
            self._fill(QTreeWidgetItem(self.tree), failed)

    def show_findings(self, findings: list[Finding]) -> None:
        for item in self._result_items:
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        self._result_items = []
        for finding in findings:
            item = QTreeWidgetItem(self.tree)
            self._fill(item, finding)
            self._result_items.append(item)

    def show_status(self, text: str) -> None:
        self.status.setText(text)

    def set_running(self, running: bool) -> None:
        self.check.setVisible(not running)
        self.close_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.cancel_button.setVisible(running)
        self.busy.setVisible(running)
        if running:
            self.log.clear()
            self.log.show()

    def set_cancelling(self) -> None:
        self.cancel_button.setEnabled(False)

    def show_progress(self, bar: Bar) -> None:
        self.busy.setRange(0, bar.maximum)
        self.busy.setValue(bar.value)

    def append_log(self, line: str) -> None:
        self.log.appendPlainText(line)
