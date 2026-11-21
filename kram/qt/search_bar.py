"""The search field and its mode, in the main toolbar: the two widgets over kram.app.search.SearchController."""
from PySide6.QtCore import QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QComboBox, QLineEdit, QSizePolicy

from ..app.search import SearchController
from ..core.search import MODE_LABELS, Mode
from ..i18n import _
from .qt_loop import QtScheduler


class SearchBar(QObject):
    """The two widgets (`mode_box`, `edit`) go into the toolbar side by side. The window talks to the controller
    through the same names (`text`, `mode`, `set_query`, `changed`…)."""

    def __init__(self, parent: QObject, controller: SearchController | None = None):
        super().__init__(parent)
        self.controller = c = controller if controller is not None else SearchController(QtScheduler(self))
        self.changed, self.submitted, self.settled = c.changed, c.submitted, c.settled
        for name in ("text", "mode", "set_mode", "set_query", "clear", "cancel_pending", "start_history",
                     "stop_history"):
            setattr(self, name, getattr(c, name))

        self.mode_box = QComboBox()
        self.mode_box.addItems([MODE_LABELS[m] for m in Mode])
        self.mode_box.setToolTip(
            _("Name / Name + summary / Description: instant ranked search.\n"
              "Provides: packages providing a capability (libvulkan.so.1, python3dist(requests), webbrowser).\n"
              "File: owner of a file (/usr/bin/7z or just 7z; only the main files for packages not installed).\n\n"
              "Several words: all must match. ^start, end$, * and ? are wildcards."))
        self.mode_box.currentIndexChanged.connect(c.mode_chosen)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText(_("Search (Ctrl+F)"))
        self.edit.setClearButtonEnabled(True)
        # shrinks before anything overflows into the toolbar's ">" menu (where Ctrl+F could not reach it)
        self.edit.setMinimumWidth(160)
        self.edit.setMaximumWidth(300)
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._icon = self.edit.addAction(QIcon.fromTheme("edit-find"), QLineEdit.ActionPosition.LeadingPosition)
        self.edit.textChanged.connect(self._on_text)
        self.edit.returnPressed.connect(c.submit)
        c.shown.connect(self._show)

    def _on_text(self, text: str) -> None:
        self.controller.edited(text)
        self._update_icon()

    def _show(self, text: str, mode: Mode) -> None:
        for w, setter in ((self.edit, lambda: self.edit.setText(text)),
                          (self.mode_box, lambda: self.mode_box.setCurrentIndex(int(mode)))):
            w.blockSignals(True)
            setter()
            w.blockSignals(False)
        self._update_icon()

    def focus(self) -> None:
        self.edit.setFocus()
        self.edit.selectAll()

    def _update_icon(self) -> None:
        """A funnel while the search text filters the list."""
        active = self.controller.filtering
        # the theme's own icon (monochrome in Breeze); themes without view-filter keep the magnifier
        self._icon.setIcon(QIcon.fromTheme("view-filter" if active and QIcon.hasThemeIcon("view-filter")
                                           else "edit-find"))
        self._icon.setToolTip(_("The list is filtered by the search text") if active else "")
