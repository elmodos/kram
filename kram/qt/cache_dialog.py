"""Settings → Cleanup (kram.app.cache): the package caches and rpm's leftover configuration files."""
import html
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPalette, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..app.cache import CACHES, LEFTOVERS_ICONS, CacheLine, Cleanup, LeftoverLine, RunHelper, describe
from ..core.leftovers import Leftover
from ..i18n import _
from .files import show_in_file_manager
from .qt_ui import QtUi

ICON_SIZE = QSize(32, 32)
PREFERRED_WIDTH = 820  # the description of every row fits on one line
MINIMUM_HEIGHT = 120  # about one row


def _dimmed(label: QLabel) -> QLabel:
    palette = label.palette()
    color = palette.color(QPalette.ColorRole.WindowText)
    color.setAlpha(170)
    palette.setColor(QPalette.ColorRole.WindowText, color)
    label.setPalette(palette)
    return label


def _themed_icon(names: tuple[str, ...]) -> QIcon:
    return next((QIcon.fromTheme(name) for name in names if QIcon.hasThemeIcon(name)), QIcon())


class _RowsArea(QScrollArea):
    """The list of caches: as wide as the window, its text wraps, and only the height scrolls."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def sizeHint(self) -> QSize:  # every row in full when the dialog opens; the default is a fixed guess
        height = self.widget().layout().totalHeightForWidth(PREFERRED_WIDTH)
        return QSize(PREFERRED_WIDTH, height + 2 * self.frameWidth())

    def minimumSizeHint(self) -> QSize:
        """Not narrower than the rows can get once their text wraps: nothing scrolls sideways."""
        return QSize(self.widget().minimumSizeHint().width() + self.verticalScrollBar().sizeHint().width()
                     + 2 * self.frameWidth(), MINIMUM_HEIGHT)


@dataclass
class _Row:
    frame: QWidget
    separator: QFrame
    path: QLabel
    size: QLabel
    files: QLabel
    button: QPushButton


@dataclass
class _Row:
    frame: QWidget
    separator: QFrame
    path: QLabel
    size: QLabel
    files: QLabel
    button: QPushButton


class CacheDialog(QDialog):
    describe = staticmethod(describe)

    def __init__(self, dnf, clean_system, parent=None, *, helper: RunHelper | None = None):
        """`clean_system(target, done)` runs the helper's clean_cache; `helper(request, title, done)` any other
        request (kram.app.cache.Cleanup)."""
        super().__init__(parent)
        self.setWindowTitle(_("Cleanup"))
        self.cleanup = Cleanup(dnf, self, QtUi(self), clean_system, helper)
        self.rows: dict[str, _Row] = {}

        lay = QVBoxLayout(self)
        content = QWidget()
        content.setAutoFillBackground(True)
        content.setBackgroundRole(QPalette.ColorRole.Base)
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        for target, icons, title, description, button in CACHES:
            row = self.rows[target] = self._build_row(icons, _(title), _(description), _(button))
            row.button.clicked.connect(lambda _checked=False, t=target: self.cleanup.clean(t))
            column.addWidget(row.separator)
            column.addWidget(row.frame)
        # the same width in every row, whatever the longest label is in this language
        width = max(row.button.sizeHint().width() for row in self.rows.values())
        for row in self.rows.values():
            row.button.setFixedWidth(width)
        column.addWidget(self._build_leftovers_header())
        self.leftover_rows = QWidget()
        self._leftover_column = QVBoxLayout(self.leftover_rows)
        self._leftover_column.setContentsMargins(0, 0, 0, 0)
        self._leftover_column.setSpacing(0)
        column.addWidget(self.leftover_rows)
        column.addStretch(1)
        self.scroll = _RowsArea()
        self.scroll.setWidget(content)
        lay.addWidget(self.scroll, 1)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.hide()
        lay.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._show_separators()
        self.cleanup.start()

    @property
    def leftovers(self):
        return self.cleanup.leftovers

    def _build_row(self, icons: tuple[str, ...], title: str, description: str, button: str) -> _Row:
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Plain)
        separator.setStyleSheet("color: palette(midlight);")

        frame = QWidget()
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(14)
        picture = QLabel()
        picture.setPixmap(_themed_icon(icons).pixmap(ICON_SIZE, self.devicePixelRatioF()))
        picture.setFixedSize(ICON_SIZE)
        lay.addWidget(picture, 0, Qt.AlignmentFlag.AlignVCenter)

        text = QVBoxLayout()
        text.setSpacing(2)
        heading = QLabel(f"<b>{title}</b>")
        heading.setWordWrap(True)
        text.addWidget(heading)
        details = _dimmed(QLabel(description))
        details.setWordWrap(True)
        text.addWidget(details)
        path = QLabel()
        path.setWordWrap(True)
        # a link that can also be selected and copied
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        path.setOpenExternalLinks(True)
        path.setToolTip(_("Open in the file manager"))
        text.addWidget(path)
        lay.addLayout(text, 1)

        numbers = QVBoxLayout()
        numbers.setSpacing(2)
        size, files = QLabel(), _dimmed(QLabel())
        for label in (size, files):
            label.setAlignment(Qt.AlignmentFlag.AlignRight)
            numbers.addWidget(label)
        lay.addLayout(numbers)

        push = QPushButton(button)
        lay.addWidget(push, 0, Qt.AlignmentFlag.AlignVCenter)
        return _Row(frame, separator, path, size, files, push)

    def _show_separators(self) -> None:
        """A line between visible rows only: none above the first one, whichever that is."""
        first = True
        for row in self.rows.values():
            row.separator.setVisible(not first and not row.frame.isHidden())
            first = first and row.frame.isHidden()

    def _show_separators(self) -> None:
        """A line between visible rows only: none above the first one, whichever that is."""
        first = True
        for row in self.rows.values():
            row.separator.setVisible(not first and not row.frame.isHidden())
            first = first and row.frame.isHidden()

    def done(self, result: int) -> None:
        self.cleanup.close()  # deleted after use: results that arrive later are dropped
        super().done(result)

    def _build_leftovers_header(self) -> QWidget:
        box = QWidget()
        outer = QVBoxLayout(box)
        outer.setContentsMargins(0, 18, 0, 0)
        outer.setSpacing(0)
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setStyleSheet("color: palette(mid);")
        outer.addWidget(line)
        frame = QWidget()
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(14)
        picture = QLabel()
        picture.setPixmap(_themed_icon(LEFTOVERS_ICONS).pixmap(
            ICON_SIZE, self.devicePixelRatioF()))
        picture.setFixedSize(ICON_SIZE)
        lay.addWidget(picture, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        heading = QLabel(f"<b>{_('Leftover configuration files')}</b>")
        text.addWidget(heading)
        about = _dimmed(QLabel(_("Copies rpm keeps when you had changed a package's configuration file: your earlier "
                                 "version (.rpmsave) or the package's new default it did not apply (.rpmnew).")))
        about.setWordWrap(True)
        text.addWidget(about)
        self.leftovers_status = QLabel()
        self.leftovers_status.setWordWrap(True)
        text.addWidget(self.leftovers_status)
        lay.addLayout(text, 1)
        buttons = QVBoxLayout()
        buttons.setSpacing(6)
        self.search_root_btn = QPushButton(QIcon.fromTheme("edit-find"), _("Search All Folders…"))
        self.search_root_btn.setToolTip(_("Also search the folders only root can read"))
        self.search_root_btn.clicked.connect(self.cleanup.search_as_root)
        self.delete_unused_btn = QPushButton(QIcon.fromTheme("edit-delete"), _("Delete Unused…"))
        self.delete_unused_btn.setToolTip(_("Delete the copies of files that no longer exist"))
        self.delete_unused_btn.clicked.connect(self.cleanup.delete_unused)
        for b in (self.search_root_btn, self.delete_unused_btn):
            buttons.addWidget(b)
        lay.addLayout(buttons)
        outer.addWidget(frame)
        return box

    def _build_leftover_row(self, line: LeftoverLine) -> QWidget:
        leftover = line.leftover
        frame = QWidget()
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(14)
        picture = QLabel()
        picture.setPixmap(_themed_icon(line.icons).pixmap(ICON_SIZE, self.devicePixelRatioF()))
        picture.setFixedSize(ICON_SIZE)
        lay.addWidget(picture, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        path = QLabel(f"<a href='#'>{html.escape(leftover.path)}</a>")
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        path.setToolTip(_("Show in File Manager"))
        path.linkActivated.connect(lambda _link, p=leftover.path: show_in_file_manager(p))
        text.addWidget(path)
        details = _dimmed(QLabel(line.description))
        details.setWordWrap(True)
        text.addWidget(details)
        lay.addLayout(text, 1)
        when = _dimmed(QLabel(line.when))
        when.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(when)
        compare = QPushButton(_("Compare"))
        compare.setEnabled(line.can_compare)
        compare.setToolTip(line.compare_tip)
        compare.clicked.connect(lambda: self.cleanup.compare(leftover))
        delete = QPushButton(QIcon.fromTheme("edit-delete"), _("Delete…"))
        delete.setEnabled(line.can_delete)
        delete.clicked.connect(lambda: self.cleanup.delete([leftover]))
        for b in (compare, delete):
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        frame.setObjectName(leftover.path)  # found again by tests
        return frame

    # ---------------------------------------------------------------- CleanupView

    def show_measuring(self) -> None:
        for row in self.rows.values():
            row.size.setText("…")
            row.files.clear()
            row.button.setEnabled(False)

    def show_caches(self, lines: list[CacheLine]) -> None:
        for line in lines:
            row = self.rows[line.target]
            row.frame.setHidden(not line.shown)
            if not line.shown:
                continue
            row.path.setText(f"<a href='{html.escape(QUrl.fromLocalFile(line.folder).toString(), quote=True)}'>"
                             f"{html.escape(line.path)}</a>")
            row.size.setText(f"<b>{line.size}</b>")
            if line.files:
                row.files.setText(line.files)
            row.button.setEnabled(line.can_clean)
        self._show_separators()
        self.scroll.updateGeometry()  # the numbers changed how narrow the rows can get

    def set_clean_enabled(self, target: str, on: bool) -> None:
        self.rows[target].button.setEnabled(on)

    def show_note(self, text: str | None) -> None:
        if text:
            self.note.setText("⚠ " + text)
        self.note.setVisible(bool(text))

    def show_leftovers_status(self, text: str) -> None:
        """Searching, or the search failed: nothing to act on meanwhile."""
        self.leftovers_status.setText(text)
        self.search_root_btn.hide()
        self.delete_unused_btn.setEnabled(False)

    def show_leftovers(self, lines: list[LeftoverLine], status: str, can_search_root: bool,
                       can_delete_unused: bool) -> None:
        while (item := self._leftover_column.takeAt(0)) is not None:
            if item.widget():
                item.widget().deleteLater()
        for line in lines:
            self._leftover_column.addWidget(self._build_leftover_row(line))
        self.leftovers_status.setText(status)
        self.search_root_btn.setVisible(can_search_root)
        self.delete_unused_btn.setEnabled(can_delete_unused)
        self.scroll.updateGeometry()

    def show_diff(self, leftover: Leftover, text: str) -> None:
        _DiffDialog(leftover, text, self).exec()


class _DiffHighlighter(QSyntaxHighlighter):
    def __init__(self, document, palette: QPalette):
        super().__init__(document)
        dark = palette.color(QPalette.ColorRole.Base).lightness() < 128
        self._formats = {}
        for prefix, light_color, dark_color in (("+", "#1b7a1b", "#7fd67f"), ("-", "#b02020", "#ff8a8a"),
                                                ("@", "#5a5aa0", "#a0a0ff")):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(dark_color if dark else light_color))
            self._formats[prefix] = fmt

    def highlightBlock(self, text: str) -> None:
        if text.startswith(("+++", "---")):
            return
        if fmt := self._formats.get(text[:1]):
            self.setFormat(0, len(text), fmt)


class _DiffDialog(QDialog):
    def __init__(self, leftover: Leftover, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Compare"))
        self.resize(900, 640)
        lay = QVBoxLayout(self)
        intro = QLabel(_("Lines with “-” are in the current file {current}; lines with “+” only in {path}.").format(
            current=leftover.current, path=leftover.path))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.view = QPlainTextEdit(text)
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._highlighter = _DiffHighlighter(self.view.document(), self.view.palette())
        lay.addWidget(self.view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
