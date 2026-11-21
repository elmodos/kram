"""The session bus from Qt: showing a file in the desktop's file manager, and `QtBus` (kram.app.ports.Bus)."""
import os
from collections.abc import Callable

from PySide6.QtCore import QUrl
from PySide6.QtDBus import QDBus, QDBusConnection, QDBusMessage
from PySide6.QtGui import QDesktopServices

from ..app.ports import FILE_MANAGER, FILE_MANAGER_METHOD, FILE_MANAGER_PATH

DBUS_TIMEOUT_MS = 3000


def _show_items_over_dbus(uri: str) -> bool:
    """Ask the file manager to open the folder with the file selected (the freedesktop FileManager1 interface, which
    Dolphin, Nautilus, Nemo and others answer). False if nothing answered."""
    message = QDBusMessage.createMethodCall(FILE_MANAGER, FILE_MANAGER_PATH, FILE_MANAGER, FILE_MANAGER_METHOD)
    message.setArguments([[uri], ""])
    reply = QDBusConnection.sessionBus().call(message, QDBus.CallMode.Block, DBUS_TIMEOUT_MS)
    return reply.type() == QDBusMessage.MessageType.ReplyMessage


def show_in_file_manager(path: str, show_items: Callable[[str], bool] = _show_items_over_dbus,
                         open_url: Callable[[QUrl], object] = QDesktopServices.openUrl) -> None:
    """Select `path` in the file manager. A file manager that does not know the interface still gets the folder."""
    if not show_items(QUrl.fromLocalFile(path).toString()):
        open_url(QUrl.fromLocalFile(os.path.dirname(path) or "/"))


class QtBus:
    """kram.app.ports.Bus on QtDBus."""

    @staticmethod
    def has_owner(name: str) -> bool:
        interface = QDBusConnection.sessionBus().interface()
        return interface is not None and bool(interface.isServiceRegistered(name).value())

    def owner_pid(self, name: str) -> int | None:
        if not self.has_owner(name):
            return None
        return QDBusConnection.sessionBus().interface().servicePid(name).value() or None
