"""The search field and its mode, in the main toolbar."""
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QComboBox, QLineEdit, QSizePolicy

from ..core.search import MODE_LABELS, Mode
from ..i18n import _

DEBOUNCE_MS = 150  # typing goes on: search once it pauses
HISTORY_IDLE_MS = 1500  # a search left alone this long goes into the history


class SearchBar(QObject):
    """The two widgets (`mode_box`, `edit`) go into the toolbar side by side; this keeps their timers.

    `changed`: search again (the text paused, or the mode changed). `submitted`: Enter. `settled`: the results of a
    search have been left alone for a while, so it belongs in the history (`start_history` after showing them)."""

    changed = Signal()
    submitted = Signal()
    settled = Signal()

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self.mode_box = QComboBox()
        self.mode_box.addItems([MODE_LABELS[m] for m in Mode])
        self.mode_box.setToolTip(
            _("Name / Name + summary / Description: instant ranked search.\n"
              "Provides: packages providing a capability (libvulkan.so.1, python3dist(requests), webbrowser).\n"
              "File: owner of a file (/usr/bin/7z or just 7z; only the main files for packages not installed).\n\n"
              "Several words: all must match. ^start, end$, * and ? are wildcards."))
        self.mode_box.currentIndexChanged.connect(self.changed)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(_("Search (Ctrl+F)"))
        self.edit.setClearButtonEnabled(True)
        # shrinks before anything overflows into the toolbar's ">" menu (where Ctrl+F could not reach it)
        self.edit.setMinimumWidth(160)
        self.edit.setMaximumWidth(300)
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._icon = self.edit.addAction(QIcon.fromTheme("edit-find"), QLineEdit.ActionPosition.LeadingPosition)
        self.edit.textChanged.connect(self._update_icon)

        self._debounce = QTimer(self, singleShot=True, interval=DEBOUNCE_MS)
        self._debounce.timeout.connect(self.changed)
        self.edit.textChanged.connect(self._debounce.start)
        self.edit.returnPressed.connect(self.submitted)
        self._history = QTimer(self, singleShot=True, interval=HISTORY_IDLE_MS)
        self._history.timeout.connect(self.settled)

    def text(self) -> str:
        return self.edit.text().strip()

    def mode(self) -> Mode:
        return Mode(self.mode_box.currentIndex())

    def set_mode(self, mode: int) -> None:
        self.mode_box.setCurrentIndex(mode)

    def set_query(self, text: str, mode: int) -> None:
        """Show a search without running it: the caller does."""
        for w, setter in ((self.edit, lambda: self.edit.setText(text)),
                          (self.mode_box, lambda: self.mode_box.setCurrentIndex(mode))):
            w.blockSignals(True)
            setter()
            w.blockSignals(False)
        self._update_icon(text)

    def clear(self, quietly: bool = False) -> None:
        """Empty the field; `quietly` without searching again, for a caller that shows another list anyway."""
        if quietly:
            self.set_query("", self.mode_box.currentIndex())
        else:
            self.edit.clear()

    def focus(self) -> None:
        self.edit.setFocus()
        self.edit.selectAll()

    def cancel_pending(self) -> None:
        """The search is running now: no need for the one the last keystroke scheduled."""
        self._debounce.stop()

    def start_history(self) -> None:
        self._history.start()

    def stop_history(self) -> None:
        self._history.stop()

    def _update_icon(self, text: str) -> None:
        """A funnel while the search text filters the list, so it is not missed after switching views."""
        active = bool(text.strip())
        # the theme's own icon (monochrome in Breeze); themes without view-filter keep the magnifier
        self._icon.setIcon(QIcon.fromTheme("view-filter" if active and QIcon.hasThemeIcon("view-filter")
                                           else "edit-find"))
        self._icon.setToolTip(_("The list is filtered by the search text") if active else "")
