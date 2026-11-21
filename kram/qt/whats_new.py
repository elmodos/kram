"""Help → About → What's New: the release notes, newest first (kram.app.whats_new)."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from ..app.whats_new import whats_new_doc
from ..core.releases import Release
from ..i18n import _
from .doc_html import to_html


class WhatsNewDialog(QDialog):
    def __init__(self, releases: list[Release], parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("What's New in Kram"))
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)
        lay.addWidget(self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.text.setHtml(to_html(whats_new_doc(releases)))
