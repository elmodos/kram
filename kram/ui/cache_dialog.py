"""Settings → Package Cache: the size of each package cache and a button to clean it."""
import html
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.cache import PACKAGEKIT_BLOCKED, CacheReport, clean_user_cache, measure
from ..i18n import N_, _, ngettext
from .package_model import human_size

METADATA, USER, PACKAGEKIT = "dnf_metadata", "user", "packagekit"
ICON_SIZE = QSize(32, 32)
PREFERRED_WIDTH = 820  # the description of every row fits on one line
MINIMUM_HEIGHT = 120  # about one row
# the field of CacheReport, which is also the helper's target (except USER, cleaned without the helper); icon names
# in the order to try: not every theme has them, and a system with GNOME Software has no Discover logo
CACHES = (
    ("dnf_packages", ("package-x-generic",), N_("DNF: downloaded packages"),
     N_("Left by interrupted transactions and “download only”."), N_("Clean")),
    (METADATA, ("application-x-sqlite3", "text-x-generic"), N_("DNF: repository metadata"),
     N_("What Kram and dnf know about the available packages."), N_("Download Again…")),
    (USER, ("user-identity", "system-users"), N_("DNF: cache of your user"),
     N_("Written by dnf when it runs without root. Kram does not use it."), N_("Clean")),
    (PACKAGEKIT, ("plasmadiscover", "system-software-install"), N_("Discover / GNOME Software"),
     N_("Packages downloaded for offline updates and never removed."), N_("Clean")),
)


def _dimmed(label: QLabel) -> QLabel:
    palette = label.palette()
    color = palette.color(QPalette.WindowText)
    color.setAlpha(170)
    palette.setColor(QPalette.WindowText, color)
    label.setPalette(palette)
    return label


def _themed_icon(names: tuple[str, ...]) -> QIcon:
    return next((QIcon.fromTheme(name) for name in names if QIcon.hasThemeIcon(name)), QIcon())


class _RowsArea(QScrollArea):
    """The list of caches: as wide as the window, its text wraps, and only the height scrolls."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

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


class CacheDialog(QDialog):
    def __init__(self, dnf, clean_system: Callable[[str], object], parent=None):
        """`clean_system(target)` runs the helper's clean_cache and returns when it has finished."""
        super().__init__(parent)
        self.setWindowTitle(_("Package Cache"))
        self._dnf = dnf
        self._clean_system = clean_system
        self.rows: dict[str, _Row] = {}

        lay = QVBoxLayout(self)
        content = QWidget()
        content.setAutoFillBackground(True)
        content.setBackgroundRole(QPalette.Base)
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        for target, icons, title, description, button in CACHES:
            row = self.rows[target] = self._build_row(icons, _(title), _(description), _(button))
            row.button.clicked.connect(lambda _checked=False, t=target: self._clean(t))
            column.addWidget(row.separator)
            column.addWidget(row.frame)
        # the same width in every row, whatever the longest label is in this language
        width = max(row.button.sizeHint().width() for row in self.rows.values())
        for row in self.rows.values():
            row.button.setFixedWidth(width)
        column.addStretch(1)
        self.scroll = _RowsArea()
        self.scroll.setWidget(content)
        lay.addWidget(self.scroll, 1)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.hide()
        lay.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._show_separators()
        self.refresh()

    def _build_row(self, icons: tuple[str, ...], title: str, description: str, button: str) -> _Row:
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Plain)
        separator.setStyleSheet("color: palette(midlight);")

        frame = QWidget()
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(14)
        picture = QLabel()
        picture.setPixmap(_themed_icon(icons).pixmap(ICON_SIZE, self.devicePixelRatioF()))
        picture.setFixedSize(ICON_SIZE)
        lay.addWidget(picture, 0, Qt.AlignVCenter)

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
        path.setTextInteractionFlags(Qt.TextBrowserInteraction)  # a link that can also be selected and copied
        path.setOpenExternalLinks(True)
        path.setToolTip(_("Open in the file manager"))
        text.addWidget(path)
        lay.addLayout(text, 1)

        numbers = QVBoxLayout()
        numbers.setSpacing(2)
        size, files = QLabel(), _dimmed(QLabel())
        for label in (size, files):
            label.setAlignment(Qt.AlignRight)
            numbers.addWidget(label)
        lay.addLayout(numbers)

        push = QPushButton(button)
        lay.addWidget(push, 0, Qt.AlignVCenter)
        return _Row(frame, separator, path, size, files, push)

    def _show_separators(self) -> None:
        """A line between visible rows only: none above the first one, whichever that is."""
        first = True
        for row in self.rows.values():
            row.separator.setVisible(not first and not row.frame.isHidden())
            first = first and row.frame.isHidden()

    def refresh(self) -> None:
        for row in self.rows.values():
            row.size.setText("…")
            row.files.clear()
            row.button.setEnabled(False)
        self._dnf.submit(measure, self._show, lambda e: self._show_note(
            _("Could not count the caches: {error}").format(error=e)))

    def _show(self, report: CacheReport) -> None:
        locations = report.locations()
        for target, row in self.rows.items():
            usage = getattr(report, target)
            row.frame.setHidden(usage is None)
            if usage is None:
                continue
            shown, folder = locations[target]
            row.path.setText(f"<a href='{html.escape(QUrl.fromLocalFile(folder).toString(), quote=True)}'>"
                             f"{html.escape(shown)}</a>")
            row.size.setText(f"<b>{human_size(usage.size)}</b>")
            if target not in (METADATA, USER):  # a pile of small repodata files: the number says nothing
                row.files.setText(ngettext("{n} file", "{n} files", usage.files).format(n=usage.files))
            row.button.setEnabled(target == METADATA or usage.files > 0)
        self._show_separators()
        self.scroll.updateGeometry()  # the numbers changed how narrow the rows can get
        blocked = report.packagekit_blocker if report.packagekit is not None else None
        if blocked:
            self.rows[PACKAGEKIT].button.setEnabled(False)
            self._show_note(_(PACKAGEKIT_BLOCKED[blocked]))
        else:
            self.note.hide()

    def _show_note(self, text: str) -> None:
        self.note.setText("⚠ " + text)
        self.note.show()

    def _clean(self, target: str) -> None:
        if target == USER:
            self.rows[USER].button.setEnabled(False)
            self._dnf.submit(clean_user_cache, lambda _result: self.refresh(), self._user_clean_failed)
            return
        if target == METADATA and QMessageBox.question(
                self, _("Download metadata again"),
                _("Delete the repository metadata and download it again?\n\nThis needs the internet and can take a few "
                  "minutes. If the download fails, the available packages disappear from Kram until a Reload "
                  "succeeds.")) != QMessageBox.Yes:
            return
        self._clean_system(target)
        self.refresh()

    def _user_clean_failed(self, error: BaseException) -> None:
        self.refresh()
        QMessageBox.warning(self, _("Package Cache"), _("Could not clean the cache: {error}").format(error=error))
