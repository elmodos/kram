"""The main window's toolbar and its styles (Settings → Toolbar, or right-click the toolbar)."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QToolBar

from ..i18n import _

# id, label, button style, icon size (an invalid size means the style's default, which on Plasma follows System
# Settings)
TOOLBAR_STYLES = [
    ("system", _("Follow System Settings"), Qt.ToolButtonStyle.ToolButtonFollowStyle, QSize()),
    ("under", _("Text Under Icons"), Qt.ToolButtonStyle.ToolButtonTextUnderIcon, QSize(24, 24)),
    ("beside", _("Compact: Text Beside Icons"), Qt.ToolButtonStyle.ToolButtonTextBesideIcon, QSize(16, 16)),
    ("icons", _("Icons Only"), Qt.ToolButtonStyle.ToolButtonIconOnly, QSize(22, 22)),
]
DEFAULT_STYLE = TOOLBAR_STYLES[0][0]


class MainToolBar(QToolBar):
    """Always there: it cannot be moved or hidden, so there is no way to lose it, only restyled."""

    def __init__(self, parent=None):
        super().__init__(_("Main toolbar"), parent)
        self.setObjectName("main-toolbar")
        self.setMovable(False)
        self.toggleViewAction().setEnabled(False)
        # the checkable style choices, for the Settings menu and the window's context menu
        self.styles = QActionGroup(self)
        for style_id, label, _button, _size in TOOLBAR_STYLES:
            a = self.styles.addAction(label)
            a.setCheckable(True)
            a.setData(style_id)
        self.styles.triggered.connect(lambda a: self.set_style(a.data()))
        self.set_style(DEFAULT_STYLE)

    def set_style(self, style_id: str) -> None:
        _id, _label, button, size = next((t for t in TOOLBAR_STYLES if t[0] == style_id), TOOLBAR_STYLES[0])
        self.setToolButtonStyle(button)
        self.setIconSize(size)
        for a in self.styles.actions():
            a.setChecked(a.data() == _id)

    def style_id(self) -> str:
        return next((a.data() for a in self.styles.actions() if a.isChecked()), DEFAULT_STYLE)
