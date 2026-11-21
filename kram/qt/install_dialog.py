"""Installing one package file, gdebi-style (kram.app.install): what it is, what installing it changes, and the
button that does it.

Self-contained (it gets the catalog, its dnf thread and the helper client), so it also works without the main
window (`kram file.rpm`). Marks in the main window are not part of it."""
import html
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QTextDocumentFragment
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QStyle,
    QTabWidget,
    QTextBrowser,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..app.apply_review import ChangeSection, RecRow
from ..app.doc import Doc, Span
from ..app.icons import ERROR, STATE_ICONS
from ..app.install import INDENT, Install, InstallButton, Note
from ..core.worker import DnfWorker
from ..i18n import _
from .apply_dialog import ChangesTree, RecommendationsList
from .doc_html import spans_html, to_html
from .icons import icon
from .links import open_web_link
from .progress_dialog import ProgressDialog
from .qt_loop import post

e = html.escape


def _browser() -> QTextBrowser:
    b = QTextBrowser()
    b.setOpenLinks(False)
    b.anchorClicked.connect(open_web_link)
    return b


def _plain() -> QPlainTextEdit:
    t = QPlainTextEdit()
    t.setReadOnly(True)
    t.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
    return t


class InstallDialog(QDialog):
    def __init__(self, path: str, catalog, dnf: DnfWorker, helper, basearch: str = "x86_64", marks: int = 0,
                 parent=None, load_catalog: bool = False):
        super().__init__(parent)
        self.setWindowTitle(_("Install Package File"))
        self.resize(880, 760)
        self.helper = helper
        self.install_logic = Install(path, catalog, dnf, post, self, busy=lambda: helper.busy, basearch=basearch,
                                     marks=marks, load_catalog=load_catalog)

        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        file_icon = QLabel()
        file_icon.setPixmap(QIcon.fromTheme("application-x-rpm", QIcon.fromTheme("package-x-generic")).pixmap(48, 48))
        file_icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        head.addWidget(file_icon)
        text = QVBoxLayout()
        self.title = QLabel()
        font = QFont(self.title.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.4)
        self.title.setFont(font)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.title.setWordWrap(True)  # a long name and version must not widen the dialog
        self.subtitle = QLabel()
        self.subtitle.setWordWrap(True)
        self.subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.notes = QWidget()
        self._notes_layout = QVBoxLayout(self.notes)
        self._notes_layout.setContentsMargins(0, 0, 0, 0)
        self._notes_layout.setSpacing(2)
        for w in (self.title, self.subtitle, self.notes):
            text.addWidget(w)
        head.addLayout(text, 1)
        lay.addLayout(head)

        self.tabs = QTabWidget()
        self.desc = _browser()
        self.details = _browser()
        self.changes = ChangesTree()
        self.deps = _browser()
        deps = QSplitter(Qt.Orientation.Vertical)
        changes_box = QWidget()
        box_lay = QVBoxLayout(changes_box)
        box_lay.setContentsMargins(0, 0, 0, 0)
        box_lay.addWidget(QLabel("<b>{}</b>".format(_("What installing it changes"))))
        box_lay.addWidget(self.changes)
        deps.addWidget(changes_box)
        deps.addWidget(self.deps)
        deps.setChildrenCollapsible(False)
        deps.setSizes([300, 200])
        self.files = _plain()
        self.changelog = _browser()
        self.scripts = _plain()
        for widget, title in [(self.desc, _("Description")), (self.details, _("Details")),
                              (deps, _("Dependencies")), (self.files, _("Files")),
                              (self.changelog, _("Changelog")), (self.scripts, _("Scripts"))]:
            self.tabs.addTab(widget, title)

        self.recs = RecommendationsList(self.install_logic.recs)
        self.recs.toggled.connect(self.install_logic.recs_changed)
        self.recs.setVisible(False)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.tabs)
        split.addWidget(self.recs)
        split.setChildrenCollapsible(False)
        split.setSizes([420, 200])
        lay.addWidget(split, 1)

        self.sizes = QLabel()
        self.sizes.setWordWrap(True)
        self.sizes.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.sizes)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(f"color: {ERROR}; font-weight: bold")
        self.warning.setVisible(False)
        lay.addWidget(self.warning)
        self.cmd = QLineEdit()
        self.cmd.setReadOnly(True)
        self.cmd.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.cmd_box = QGroupBox(_("Equivalent command"))
        QVBoxLayout(self.cmd_box).addWidget(self.cmd)
        self.cmd_box.setVisible(False)
        lay.addWidget(self.cmd_box)

        bottom = QHBoxLayout()
        self.status = QLabel()  # what runs now; the buttons wait for it
        bottom.addWidget(self.status, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.install = buttons.addButton(_("Install"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.install.setIcon(QIcon.fromTheme("list-add"))
        self.install.setDefault(True)
        buttons.accepted.connect(self.install_logic.install)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        lay.addLayout(bottom)

        self.install_logic.start()

    # the logic's state, for the window and the tests
    @property
    def rpm(self):
        return self.install_logic.rpm

    @property
    def changed_system(self) -> bool:
        return self.install_logic.changed_system

    def notes_text(self) -> str:
        """The header's lines as plain text (for tests)."""
        labels = self.notes.findChildren(QLabel)
        return "\n".join(QTextDocumentFragment.fromHtml(lb.text()).toPlainText() for lb in labels if lb.text())

    def done(self, result: int) -> None:
        self.install_logic.close()
        super().done(result)

    # ---------------------------------------------------------------- InstallView

    def show_title(self, name: str, version: str, summary: str) -> None:
        if version:
            self.title.setText(f"{e(name)} <span style='font-weight:normal'>{e(version)}</span>")
        else:
            self.title.setText(e(name))
        self.subtitle.setText(e(summary))

    def show_notes(self, notes: list[Note]) -> None:
        lay = self._notes_layout
        while lay.count():
            row = lay.takeAt(0).widget()
            row.setParent(None)  # gone from findChildren now, not at the next event loop
            row.deleteLater()
        size = self.style().pixelMetric(QStyle.PixelMetric.PM_SmallIconSize)
        for n in notes:
            row = QWidget()
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            mark = QLabel()
            mark.setFixedWidth(size)
            mark.setAlignment(Qt.AlignmentFlag.AlignTop)
            if n.kind != INDENT:
                mark.setPixmap(icon(STATE_ICONS[n.kind]).pixmap(size, size))
            label = QLabel(spans_html(n.spans))
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_lay.addWidget(mark)
            row_lay.addWidget(label, 1)
            lay.addWidget(row)

    def show_sizes(self, spans: list[Span]) -> None:
        self.sizes.setText(spans_html(spans))
        self.sizes.setVisible(bool(spans))

    def show_warning(self, text: str) -> None:
        self.warning.setText(text)
        self.warning.setVisible(bool(text))

    def show_command(self, text: str | None) -> None:
        self.cmd_box.setVisible(text is not None)
        if text is not None:
            self.cmd.setText(text)
            self.cmd.setCursorPosition(0)

    def show_button(self, button: InstallButton) -> None:
        self.install.setText(button.text)
        self.install.setIcon(QIcon.fromTheme(button.icon))
        self.install.setVisible(button.visible)
        self.install.setEnabled(button.enabled)

    def show_status(self, text: str) -> None:
        self.status.setText(text)

    def show_file(self, description: Doc, details: Doc, changelog: Doc, scripts: str) -> None:
        self.desc.setHtml(to_html(description))
        self.details.setHtml(to_html(details))
        self.changelog.setHtml(to_html(changelog))
        self.scripts.setPlainText(scripts)

    def show_deps(self, doc: Doc) -> None:
        self.deps.setHtml(to_html(doc))

    def show_files(self, text: str) -> None:
        self.files.setPlainText(text)

    def show_changes(self, sections: list[ChangeSection], problems: list[str]) -> None:
        self.changes.show_sections(sections)
        for line in problems:
            item = QTreeWidgetItem([line])
            self.changes.addTopLevelItem(item)
            item.setFirstColumnSpanned(True)

    def show_recs(self, rows: tuple[list[RecRow], list[RecRow]], visible: bool) -> None:
        self.recs.show_rows(*rows)
        self.recs.setVisible(visible)

    def set_recs_enabled(self, on: bool) -> None:
        self.recs.tree.setEnabled(on)

    def run_transaction(self, request: dict, title: str, done: Callable[[bool], None]) -> None:
        progress = ProgressDialog(self.helper, request, title, self)
        progress.exec()
        ok = progress.ok
        progress.deleteLater()  # with its whole log
        done(ok)

    def close_installed(self) -> None:
        self.accept()
