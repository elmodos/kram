"""Settings → Cleanup: the size of each package cache and a button to clean it; rpm's leftover configuration files."""
import html
import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPalette, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.cache import PACKAGEKIT_BLOCKED, CacheReport, clean_user_cache, measure
from ..core.leftovers import Kind, Leftover, LeftoverReport, classify, diff
from ..core.leftovers import scan as scan_leftovers
from ..i18n import N_, _, ngettext
from .files import show_in_file_manager
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


class CacheDialog(QDialog):
    def __init__(self, dnf, clean_system: Callable[[str], object], parent=None, *,
                 helper: Callable[[dict, str], dict | None] | None = None):
        """`clean_system(target)` runs the helper's clean_cache and returns when it has finished; `helper(request,
        title)` runs any other request and returns its final event, None if it failed."""
        super().__init__(parent)
        self.setWindowTitle(_("Cleanup"))
        self._dnf = dnf
        self._clean_system = clean_system
        self._helper = helper
        self.rows: dict[str, _Row] = {}
        self.leftovers = LeftoverReport([], 0)

        lay = QVBoxLayout(self)
        content = QWidget()
        content.setAutoFillBackground(True)
        content.setBackgroundRole(QPalette.ColorRole.Base)
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
        self.refresh()
        self.refresh_leftovers()

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
                  "succeeds.")) != QMessageBox.StandardButton.Yes:
            return
        self._clean_system(target)
        self.refresh()

    def _user_clean_failed(self, error: BaseException) -> None:
        self.refresh()
        QMessageBox.warning(self, _("Cleanup"), _("Could not clean the cache: {error}").format(error=error))

    # ---------------------------------------------------------------- leftover configuration files

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
        picture.setPixmap(_themed_icon(("document-properties", "preferences-other")).pixmap(
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
        self.search_root_btn.clicked.connect(self._search_as_root)
        self.delete_unused_btn = QPushButton(QIcon.fromTheme("edit-delete"), _("Delete Unused…"))
        self.delete_unused_btn.setToolTip(_("Delete the copies of files that no longer exist"))
        self.delete_unused_btn.clicked.connect(self._delete_unused)
        for b in (self.search_root_btn, self.delete_unused_btn):
            buttons.addWidget(b)
        lay.addLayout(buttons)
        outer.addWidget(frame)
        return box

    def refresh_leftovers(self) -> None:
        self.leftovers_status.setText(_("Searching…"))
        self.search_root_btn.hide()
        self.delete_unused_btn.setEnabled(False)
        self._dnf.submit(scan_leftovers, self._show_leftovers, lambda e: self.leftovers_status.setText(
            _("Could not search: {error}").format(error=e)))

    def _show_leftovers(self, report: LeftoverReport) -> None:
        self.leftovers = report
        while (item := self._leftover_column.takeAt(0)) is not None:
            if item.widget():
                item.widget().deleteLater()
        for leftover in report.files:
            self._leftover_column.addWidget(self._build_leftover_row(leftover))
        n = len(report.files)
        status = (ngettext("{n} file found.", "{n} files found.", n).format(n=n) if n
                  else _("Nothing found."))
        if report.unreadable:
            status += " " + ngettext("{n} folder only root can read was not searched.",
                                     "{n} folders only root can read were not searched.",
                                     report.unreadable).format(n=report.unreadable)
        self.leftovers_status.setText(status)
        self.search_root_btn.setVisible(bool(report.unreadable) and self._helper is not None)
        self.delete_unused_btn.setEnabled(self._helper is not None and any(f.kind is Kind.ORPHAN for f in report.files))
        self.scroll.updateGeometry()

    @staticmethod
    def describe(leftover: Leftover) -> str:
        package = leftover.package
        if leftover.kind is Kind.ORPHAN:
            return _("A copy of a file that no longer exists. Nothing uses it.")
        if leftover.kind is Kind.NEW:
            text = (_("The new default of {package}, not applied because the file had been changed.") if package
                    else _("A package's new default, not applied because the file had been changed."))
            return text.format(package=package) + " " + _("Compare and take over what you need, then delete it.")
        text = (_("Your earlier version, put aside by {package}.") if package
                else _("Your earlier version, put aside by a package."))
        return text.format(package=package) + " " + _("Compare and take over your changes, then delete it.")

    def _build_leftover_row(self, leftover: Leftover) -> QWidget:
        frame = QWidget()
        lay = QHBoxLayout(frame)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(14)
        icons = ("dialog-information",) if leftover.kind is Kind.NEW else ("text-x-generic", "document-new")
        picture = QLabel()
        picture.setPixmap(_themed_icon(icons).pixmap(ICON_SIZE, self.devicePixelRatioF()))
        picture.setFixedSize(ICON_SIZE)
        lay.addWidget(picture, 0, Qt.AlignmentFlag.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(2)
        path = QLabel(f"<a href='#'>{html.escape(leftover.path)}</a>")
        path.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        path.setToolTip(_("Show in File Manager"))
        path.linkActivated.connect(lambda _link, p=leftover.path: show_in_file_manager(p))
        text.addWidget(path)
        details = _dimmed(QLabel(self.describe(leftover)))
        details.setWordWrap(True)
        text.addWidget(details)
        lay.addLayout(text, 1)
        when = _dimmed(QLabel(time.strftime("%x", time.localtime(leftover.mtime)) + "\n" + human_size(leftover.size)))
        when.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(when)
        compare = QPushButton(_("Compare"))
        if leftover.kind is Kind.ORPHAN:
            compare.setEnabled(False)
            compare.setToolTip(_("There is no current file to compare it with."))
        elif not leftover.comparable:
            compare.setEnabled(False)
            compare.setToolTip(_("Only root can read it. In a terminal: {command}").format(
                command=f"sudo diff -u {leftover.current} {leftover.path}"))
        compare.clicked.connect(lambda: self._compare(leftover))
        delete = QPushButton(QIcon.fromTheme("edit-delete"), _("Delete…"))
        delete.setEnabled(self._helper is not None)
        delete.clicked.connect(lambda: self._delete([leftover]))
        for b in (compare, delete):
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        frame.setObjectName(leftover.path)  # found again by tests
        return frame

    def _compare(self, leftover: Leftover) -> None:
        try:
            text = diff(leftover)
        except OSError as e:
            QMessageBox.warning(self, _("Compare"), _("Could not read the files: {error}").format(error=e.strerror))
            return
        _DiffDialog(leftover, text or _("The files are the same."), self).exec()

    def _delete_unused(self) -> None:
        self._delete([f for f in self.leftovers.files if f.kind is Kind.ORPHAN])

    def _delete(self, files: list[Leftover]) -> None:
        if not files or self._helper is None:
            return
        if len(files) == 1:
            question = _("Delete {path}?").format(path=files[0].path)
        else:
            question = ngettext("Delete {n} file?", "Delete {n} files?", len(files)).format(n=len(files))
        box = QMessageBox(QMessageBox.Icon.Question, _("Delete leftover files"), question, parent=self)
        lines = ["\n".join(f.path for f in files)] if len(files) > 1 else []
        if any(f.kind is Kind.NEW for f in files):
            lines.append(_("The new default settings in it are lost: compare first to take over what you need."))
        elif any(f.kind is Kind.SAVED for f in files):
            lines.append(_("Your changes in it are lost, unless the current file has them too."))
        box.setInformativeText("\n\n".join(lines))
        delete = box.addButton(_("Delete"), QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is not delete:
            return
        title = ngettext("Deleting {n} file", "Deleting {n} files", len(files)).format(n=len(files))
        if self._helper({"op": "remove_leftovers", "paths": [f.path for f in files]}, title) is not None:
            gone = {f.path for f in files}
            self._show_leftovers(LeftoverReport([f for f in self.leftovers.files if f.path not in gone],
                                                self.leftovers.unreadable))
        else:
            self.refresh_leftovers()  # part of them may be gone

    def _search_as_root(self) -> None:
        result = self._helper({"op": "find_leftovers"}, _("Searching for leftover files")) if self._helper else None
        if result is not None:
            self._dnf.submit(lambda: classify(result.get("files", []), result.get("unreadable", 0)),
                             self._show_leftovers)


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
