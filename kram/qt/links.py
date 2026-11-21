"""Links in text Kram shows: only web addresses are handed to the desktop (kram.app.ports.is_web_link)."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from ..app.ports import is_web_link


def open_web_link(url: QUrl) -> bool:
    """Open `url` in the browser, if it is a web address."""
    if not is_web_link(url.toString()):
        return False
    return QDesktopServices.openUrl(url)
