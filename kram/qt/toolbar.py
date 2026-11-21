"""The main window's toolbar and its styles (Settings → Toolbar, or right-click the toolbar)."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QToolBar

from ..app import preferences
from ..i18n import _

# the choices of the toolbar style setting (kram.app.preferences): button style and icon size (an invalid size means
# the style's default, which on Plasma follows System Settings)
TOOLBAR_STYLES = {
    "system": (Qt.ToolButtonStyle.ToolButtonFollowStyle, QSize()),
    "under": (Qt.ToolButtonStyle.ToolButtonTextUnderIcon, QSize(24, 24)),
    "beside": (Qt.ToolButtonStyle.ToolButtonTextBesideIcon, QSize(16, 16)),
    "icons": (Qt.ToolButtonStyle.ToolButtonIconOnly, QSize(22, 22)),
}
DEFAULT_STYLE = preferences.pref(preferences.TOOLBAR_STYLE).default


class MainToolBar(QToolBar):
    """Always there: it cannot be moved or hidden, so there is no way to lose it, only restyled. `styles`: the
    checkable style choices of the setting (each action's data is a style id)."""

    def __init__(self, styles: QActionGroup, parent=None):
        super().__init__(_("Main toolbar"), parent)
        self.setObjectName("main-toolbar")
        self.setMovable(False)
        self.toggleViewAction().setEnabled(False)
        self.styles = styles
        styles.triggered.connect(lambda a: self.set_style(a.data()))
        self.set_style(preferences.value(preferences.TOOLBAR_STYLE))

    def set_style(self, style_id: str) -> None:
        style_id = style_id if style_id in TOOLBAR_STYLES else DEFAULT_STYLE
        button, size = TOOLBAR_STYLES[style_id]
        self.setToolButtonStyle(button)
        self.setIconSize(size)
        for a in self.styles.actions():
            a.setChecked(a.data() == style_id)

    def style_id(self) -> str:
        return next((a.data() for a in self.styles.actions() if a.isChecked()), DEFAULT_STYLE)
