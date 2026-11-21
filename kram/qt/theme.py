"""A convenience for GNOME: Kram follows the session's light/dark setting, in libadwaita's colours.

Qt has no GNOME style. Without a platform theme it does not even ask the desktop for light or dark, and its Fusion
style stays light in a dark session. So in a GNOME session Kram turns on Qt's portal platform theme (which reads the
setting and reports its changes), uses Fusion and gives it a light or dark palette after libadwaita's.

A user who picked a Qt look (`QT_STYLE_OVERRIDE`, or a platform theme such as qt6ct) keeps it; other desktops are
not touched.
"""
import os
from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

PLATFORM_THEME = "QT_QPA_PLATFORMTHEME"
R = QPalette.ColorRole

# libadwaita's named colours (1.6+), the translucent ones flattened over the window background
LIGHT = {
    R.Window: "#fafafb", R.WindowText: "#2e2e32",
    R.Base: "#ffffff", R.AlternateBase: "#f6f6f7", R.Text: "#1e1e20",
    R.Button: "#ebebed", R.ButtonText: "#2e2e32",
    R.ToolTipBase: "#2e2e32", R.ToolTipText: "#ffffff",
    R.Highlight: "#3584e4", R.HighlightedText: "#ffffff",
    R.Link: "#1c71d8", R.LinkVisited: "#813d9c", R.BrightText: "#ffffff",
    R.PlaceholderText: "#8a8a8d",
    R.Light: "#ffffff", R.Midlight: "#f2f2f3", R.Mid: "#cdcdd0", R.Dark: "#a8a8ac", R.Shadow: "#77767b",
}
DARK = {
    R.Window: "#222226", R.WindowText: "#ffffff",
    R.Base: "#1d1d20", R.AlternateBase: "#252529", R.Text: "#ffffff",
    R.Button: "#38383c", R.ButtonText: "#ffffff",
    R.ToolTipBase: "#000000", R.ToolTipText: "#ffffff",
    R.Highlight: "#3584e4", R.HighlightedText: "#ffffff",
    R.Link: "#78aeed", R.LinkVisited: "#dc8add", R.BrightText: "#ffffff",
    R.PlaceholderText: "#8d8d90",
    R.Light: "#4a4a4e", R.Midlight: "#404044", R.Mid: "#303034", R.Dark: "#161619", R.Shadow: "#000000",
}
# disabled text, half-way to the background
DISABLED = {False: "#9c9c9f", True: "#7d7d80"}


def palette(dark: bool) -> QPalette:
    result = QPalette()
    for role, colour in (DARK if dark else LIGHT).items():
        result.setColor(role, QColor(colour))
    for role in (R.WindowText, R.Text, R.ButtonText):
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor(DISABLED[dark]))
    return result


def wanted(environ: Mapping[str, str] = os.environ) -> bool:
    """A GNOME session (also "ubuntu:GNOME" and the like) where the user has not picked a Qt look."""
    desktops = environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    return "gnome" in desktops and not environ.get("QT_STYLE_OVERRIDE") and not environ.get(PLATFORM_THEME)


def prepare() -> bool:
    """Call before the QApplication exists: Qt picks its platform theme when the application is created. True when
    install() should follow."""
    if not wanted():
        return False
    os.environ[PLATFORM_THEME] = "xdgdesktopportal"
    return True


def install(app: QApplication) -> None:
    """Fusion with the palette that matches the session now, and again whenever the setting changes."""
    # read when the application was created; programs Kram starts (a browser, a file manager) get their own
    os.environ.pop(PLATFORM_THEME, None)
    app.setStyle("Fusion")
    hints = app.styleHints()

    def follow(*_) -> None:
        app.setPalette(palette(hints.colorScheme() == Qt.ColorScheme.Dark))

    follow()
    hints.colorSchemeChanged.connect(follow)
