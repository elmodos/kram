"""In a GNOME session Kram follows the light/dark setting with libadwaita's colours, unless the user picked a Qt look."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kram.ui import theme  # noqa: E402


@pytest.mark.parametrize("desktop", ["GNOME", "ubuntu:GNOME", "GNOME-Classic:GNOME"])
def test_gnome_sessions_are_followed(desktop):
    assert theme.wanted({"XDG_CURRENT_DESKTOP": desktop})


@pytest.mark.parametrize("desktop", ["KDE", "XFCE", "COSMIC", "X-Cinnamon", ""])
def test_other_desktops_keep_their_own_look(desktop):
    assert not theme.wanted({"XDG_CURRENT_DESKTOP": desktop})


@pytest.mark.parametrize("name, value", [("QT_STYLE_OVERRIDE", "kvantum"), ("QT_QPA_PLATFORMTHEME", "qt6ct")])
def test_the_users_own_qt_look_is_left_alone(name, value):
    assert not theme.wanted({"XDG_CURRENT_DESKTOP": "GNOME", name: value})


def test_light_and_dark_palettes():
    QApplication.instance() or QApplication([])
    light, dark = theme.palette(False), theme.palette(True)
    assert light.color(QPalette.ColorRole.Base).lightness() > 200
    assert dark.color(QPalette.ColorRole.Base).lightness() < 60
    for p in (light, dark):
        assert p.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text) != p.color(QPalette.ColorRole.Text)


def test_the_portal_theme_is_on_only_while_the_application_is_created(monkeypatch):
    """Qt reads the platform theme once; programs Kram starts later must not inherit it."""
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.delenv("QT_STYLE_OVERRIDE", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORMTHEME", raising=False)
    assert theme.prepare()
    assert os.environ["QT_QPA_PLATFORMTHEME"] == "xdgdesktopportal"
    app = QApplication.instance() or QApplication([])
    style = app.style().name()
    try:
        theme.install(app)
        assert "QT_QPA_PLATFORMTHEME" not in os.environ
        assert app.style().name().lower() == "fusion"
    finally:  # the style and palette are the whole process's: put them back for the other tests
        app.setStyle(style)
        app.setPalette(QPalette())


def test_nothing_happens_on_other_desktops(monkeypatch):
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.delenv("QT_QPA_PLATFORMTHEME", raising=False)
    assert not theme.prepare()
    assert "QT_QPA_PLATFORMTHEME" not in os.environ
