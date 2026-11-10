"""Showing a file in the desktop's file manager."""
import os
from collections.abc import Callable

from PySide6.QtCore import QUrl
from PySide6.QtDBus import QDBus, QDBusConnection, QDBusMessage
from PySide6.QtGui import QDesktopServices

FILE_MANAGER = "org.freedesktop.FileManager1"
DBUS_TIMEOUT_MS = 3000


def _show_items_over_dbus(uri: str) -> bool:
    """Ask the file manager to open the folder with the file selected (the freedesktop FileManager1 interface, which
    Dolphin, Nautilus, Nemo and others answer). False if nothing answered."""
    message = QDBusMessage.createMethodCall(FILE_MANAGER, "/org/freedesktop/FileManager1", FILE_MANAGER, "ShowItems")
    message.setArguments([[uri], ""])
    reply = QDBusConnection.sessionBus().call(message, QDBus.Block, DBUS_TIMEOUT_MS)
    return reply.type() == QDBusMessage.ReplyMessage


def show_in_file_manager(path: str, show_items: Callable[[str], bool] = _show_items_over_dbus,
                         open_url: Callable[[QUrl], object] = QDesktopServices.openUrl) -> None:
    """Select `path` in the file manager. A file manager that does not know the interface still gets the folder."""
    if not show_items(QUrl.fromLocalFile(path).toString()):
        open_url(QUrl.fromLocalFile(os.path.dirname(path) or "/"))
