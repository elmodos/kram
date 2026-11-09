"""Settings → Package Cache: the size of each package cache and a button to clean it."""
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QGridLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from ..core.cache import PACKAGEKIT_BLOCKED, CacheReport, clean_user_cache, measure
from ..i18n import N_, _, ngettext
from .package_model import human_size

METADATA, USER, PACKAGEKIT = "dnf_metadata", "user", "packagekit"
# the field of CacheReport, which is also the helper's target (except USER, cleaned without the helper)
CACHES = (
    ("dnf_packages", N_("DNF: downloaded packages"), N_("Left by interrupted transactions and “download only”."),
     N_("Clean")),
    (METADATA, N_("DNF: repository metadata"), N_("What Kram and dnf know about the available packages."),
     N_("Download Again…")),
    (USER, N_("DNF: cache of your user"), N_("Written by dnf when it runs without root. Kram does not use it."),
     N_("Clean")),
    (PACKAGEKIT, N_("Discover / GNOME Software"), N_("Packages downloaded for offline updates and never removed."),
     N_("Clean")),
)


@dataclass
class _Row:
    title: QLabel
    description: QLabel
    size: QLabel
    files: QLabel
    button: QPushButton

    def set_visible(self, visible: bool) -> None:
        for widget in (self.title, self.description, self.size, self.files, self.button):
            widget.setVisible(visible)


class CacheDialog(QDialog):
    def __init__(self, dnf, clean_system: Callable[[str], object], parent=None):
        """`clean_system(target)` runs the helper's clean_cache and returns when it has finished."""
        super().__init__(parent)
        self.setWindowTitle(_("Package Cache"))
        self.setMinimumWidth(680)
        self._dnf = dnf
        self._clean_system = clean_system
        self.rows: dict[str, _Row] = {}

        lay = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setColumnStretch(0, 1)
        grid.setHorizontalSpacing(18)
        for i, (target, title, description, button) in enumerate(CACHES):
            row = self.rows[target] = _Row(QLabel(f"<b>{_(title)}</b>"), QLabel(_(description)), QLabel(), QLabel(),
                                           QPushButton(_(button)))
            row.description.setWordWrap(True)
            row.button.clicked.connect(lambda _checked=False, t=target: self._clean(t))
            grid.addWidget(row.title, i * 2, 0)
            grid.addWidget(row.description, i * 2 + 1, 0, 1, 3)
            grid.addWidget(row.size, i * 2, 1, Qt.AlignRight)
            grid.addWidget(row.files, i * 2, 2, Qt.AlignRight)
            grid.addWidget(row.button, i * 2, 3, 2, 1, Qt.AlignVCenter)
        lay.addLayout(grid)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.hide()
        lay.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        for row in self.rows.values():
            row.size.setText("…")
            row.files.clear()
            row.button.setEnabled(False)
        self._dnf.submit(measure, self._show, lambda e: self._show_note(
            _("Could not count the caches: {error}").format(error=e)))

    def _show(self, report: CacheReport) -> None:
        for target, row in self.rows.items():
            usage = getattr(report, target)
            row.set_visible(usage is not None)
            if usage is None:
                continue
            row.size.setText(human_size(usage.size))
            if target not in (METADATA, USER):  # a pile of small repodata files: the number says nothing
                row.files.setText(ngettext("{n} file", "{n} files", usage.files).format(n=usage.files))
            row.button.setEnabled(target == METADATA or usage.files > 0)
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
