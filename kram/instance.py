"""One Kram window per session. The first Kram owns the bus name APP_ID; a second one (a menu launch, the tray
icon) hands its request to it over D-Bus and exits. The tray icon calls Activate directly when Kram runs.

    Activate(view: s, token: s)   view: "" or "upgradable"; token: an XDG activation token ("" if none), which
                                  lets a Wayland compositor give the window focus

This module is only the contract, with no D-Bus library: the Qt side is kram.qt.single_instance, the tray calls it
over Gio.
"""
from . import APP_ID

BUS_NAME = INTERFACE = APP_ID
PATH = "/"
METHOD = "Activate"
UPGRADABLE = "upgradable"
CALL_TIMEOUT_MS = 3000
