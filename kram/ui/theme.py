"""Look at home on GNOME: Qt has no GNOME style and the Fusion that Qt falls back to keeps a light palette in a dark
session, so under GNOME Kram uses Fusion with the libadwaita colours and follows the session's light/dark setting."""
import os
from collections.abc import Mapping

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

R = QPalette.ColorRole

# libadwaita's palette (the colour values of its named colours, flattened over the window background)
LIGHT = {
    R.Window: "#fafafb", R.WindowText: "#2e2e32",
    R.Base: "#ffffff", R.AlternateBase: "#f6f5f4", R.Text: "#1e1e1e",
    R.Button: "#ebebed", R.ButtonText: "#2e2e32",
    R.ToolTipBase: "#2e2e32", R.ToolTipText: "#ffffff",
    R.Highlight: "#3584e4", R.HighlightedText: "#ffffff",
    R.Link: "#1c71d8", R.LinkVisited: "#813d9c", R.BrightText: "#ffffff",
    R.PlaceholderText: "#8a8a8d",
    R.Light: "#ffffff", R.Midlight: "#f2f2f3", R.Mid: "#cdcdd0", R.Dark: "#a8a8ac", R.Shadow: "#77767b",
}
DARK = {
    R.Window: "#242424", R.WindowText: "#ffffff",
    R.Base: "#1e1e1e", R.AlternateBase: "#262626", R.Text: "#ffffff",
    R.Button: "#383838", R.ButtonText: "#ffffff",
    R.ToolTipBase: "#000000", R.ToolTipText: "#ffffff",
    R.Highlight: "#3584e4", R.HighlightedText: "#ffffff",
    R.Link: "#78aeed", R.LinkVisited: "#dc8add", R.BrightText: "#ffffff",
    R.PlaceholderText: "#8d8d8f",
    R.Light: "#4a4a4a", R.Midlight: "#404040", R.Mid: "#303030", R.Dark: "#171717", R.Shadow: "#000000",
}
DISABLED = {  # text roles only: half-way to the background
    False: {R.WindowText: "#9c9c9f", R.Text: "#9c9c9f", R.ButtonText: "#9c9c9f"},
    True: {R.WindowText: "#7d7d7f", R.Text: "#7d7d7f", R.ButtonText: "#7d7d7f"},
}


def palette(dark: bool) -> QPalette:
    result = QPalette()
    for role, colour in (DARK if dark else LIGHT).items():
        result.setColor(role, QColor(colour))
    for role, colour in DISABLED[dark].items():
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor(colour))
    return result


def wanted(environ: Mapping[str, str] = os.environ) -> bool:
    """A GNOME session whose user has not picked a Qt look: `QT_STYLE_OVERRIDE` or a platform theme such as qt6ct
    or Kvantum's means they did, and that is left alone."""
    desktops = environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    return "gnome" in desktops and not environ.get("QT_STYLE_OVERRIDE") and not environ.get("QT_QPA_PLATFORMTHEME")


def prepare() -> bool:
    """Before the QApplication exists: without a platform theme Qt does not ask the desktop for light or dark (it
    reports Unknown), so under GNOME the portal one is switched on. True when the rest of this module should run."""
    if not wanted():
        return False
    os.environ["QT_QPA_PLATFORMTHEME"] = "xdgdesktopportal"
    return True


def install(app: QApplication) -> None:
    """After prepare() said yes."""
    from PySide6.QtCore import Qt

    app.setStyle("Fusion")
    hints = app.styleHints()

    def apply(*_) -> None:
        app.setPalette(palette(hints.colorScheme() == Qt.ColorScheme.Dark))

    apply()
    hints.colorSchemeChanged.connect(apply)
