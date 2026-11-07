"""Help → About → What's New: the release notes, newest first."""
import html

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

from .. import __version__
from ..core.releases import Release
from ..i18n import _

e = html.escape


class WhatsNewDialog(QDialog):
    def __init__(self, releases: list[Release], parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("What's New in Kram"))
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)
        lay.addWidget(self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        parts = []
        for r in releases:
            current = f" <i>({e(_('this version'))})</i>" if r.version == __version__ else ""
            parts.append(f"<h3>{e(r.version)} — {e(r.date)}{current}</h3>")
            parts += [f"<p>{e(p)}</p>" for p in r.paragraphs]
            if r.items:
                parts.append("<ul>" + "".join(f"<li>{e(i)}</li>" for i in r.items) + "</ul>")
        self.text.setHtml("".join(parts) or f"<i>{e(_('The list of changes is not available.'))}</i>")
