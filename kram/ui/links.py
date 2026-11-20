"""Links in text Kram shows: only web addresses are handed to the desktop."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

WEB_SCHEMES = ("http", "https")


def open_web_link(url: QUrl) -> bool:
    """Open `url` in the browser, if it is a web address. A package's URL tag comes from whoever built the file, so
    a file:, smb: or custom-handler link is not opened: one click would run whatever handles it."""
    if url.scheme().lower() not in WEB_SCHEMES:
        return False
    return QDesktopServices.openUrl(url)
