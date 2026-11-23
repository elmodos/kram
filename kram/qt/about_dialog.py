"""Help → About: the version, the toolkit and the licence; What's New opens over it, and About stays open behind."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout

from ..core import releases
from ..i18n import _
from .whats_new import WhatsNewDialog


class AboutDialog(QDialog):
    def __init__(self, html: str, icon: QPixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("About Kram"))
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        picture = QLabel()
        picture.setPixmap(icon)
        picture.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(picture)
        self.text = QLabel(html)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setOpenExternalLinks(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        row.addWidget(self.text, 1)
        row.setSpacing(18)
        lay.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.whats_new_btn = buttons.addButton(_("What's New"), QDialogButtonBox.ButtonRole.ActionRole)
        self.whats_new_btn.clicked.connect(self.show_whats_new)  # a bound method: see kram.qt.repos_dialog
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def show_whats_new(self) -> None:
        """Over About, which stays open: closing What's New goes back to it."""
        dlg = WhatsNewDialog(releases.load(), self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.open()
