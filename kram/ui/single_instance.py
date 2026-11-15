"""Qt's side of kram.instance: hand a request over to the Kram already running, or serve requests as the first one."""
import os
from collections.abc import Callable

from PySide6.QtCore import ClassInfo, QObject, Slot
from PySide6.QtDBus import QDBus, QDBusConnection, QDBusMessage

from ..instance import BUS_NAME, CALL_TIMEOUT_MS, INTERFACE, METHOD, PATH


def hand_over(view: str) -> bool:
    """True when another Kram took the request (this one should exit); False when this one is the first."""
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected() or bus.registerService(BUS_NAME):
        return False
    message = QDBusMessage.createMethodCall(BUS_NAME, PATH, INTERFACE, METHOD)
    message.setArguments([view, os.environ.pop("XDG_ACTIVATION_TOKEN", "")])
    reply = bus.call(message, QDBus.Block, CALL_TIMEOUT_MS)
    return reply.type() == QDBusMessage.ReplyMessage  # no answer (a hung Kram): better a second window than none


@ClassInfo({"D-Bus Interface": INTERFACE})
class Service(QObject):
    """What the first Kram exports; `activate(view)` is the main window's."""

    def __init__(self, activate: Callable[[str], None]):
        super().__init__()
        self._activate = activate

    @Slot(str, str)
    def Activate(self, view: str, token: str) -> None:  # noqa: N802 (the D-Bus method name)
        if token:  # Qt's Wayland backend takes it from here on the next activation request
            os.environ["XDG_ACTIVATION_TOKEN"] = token
        self._activate(view)


def serve(activate: Callable[[str], None]) -> Service | None:
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    service = Service(activate)
    bus.registerObject(PATH, service, QDBusConnection.ExportAllSlots)
    return service
