"""The toolbar's "Fedora N" button over kram.app.release_watch."""
from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QIcon

from ..app import release_watch
from .qt_loop import post


class ReleaseWatcher(release_watch.ReleaseWatcher):
    """`act_upgrade` is the toolbar button, which the window connects to its dialog; the window calls
    `update_button` when the setting changes."""

    def __init__(self, parent: QObject):
        super().__init__(post)
        first, fallback = release_watch.BUTTON_ICONS
        self.act_upgrade = QAction(QIcon.fromTheme(first, QIcon.fromTheme(fallback)), "Fedora", parent)
        self.act_upgrade.setEnabled(False)
        self.update_button()
        self.changed.connect(self.update_button)

    def update_button(self) -> None:
        button = self.button()
        self.act_upgrade.setVisible(button.visible)
        self.act_upgrade.setText(button.text)
        self.act_upgrade.setToolTip(button.tooltip)
        self.act_upgrade.setStatusTip(button.tooltip)
