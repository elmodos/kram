"""Under GNOME Kram paints itself with the libadwaita palette, light or dark as the session is."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from kram.ui import theme  # noqa: E402


@pytest.mark.parametrize("desktop", ["GNOME", "ubuntu:GNOME", "gnome"])
def test_gnome_sessions_are_themed(desktop):
    assert theme.wanted({"XDG_CURRENT_DESKTOP": desktop})


@pytest.mark.parametrize("desktop", ["KDE", "XFCE", "COSMIC", "", "X-Cinnamon"])
def test_other_desktops_keep_their_own_look(desktop):
    assert not theme.wanted({"XDG_CURRENT_DESKTOP": desktop})


@pytest.mark.parametrize("name", ["QT_STYLE_OVERRIDE", "QT_QPA_PLATFORMTHEME"])
def test_the_users_own_qt_choice_is_left_alone(name):
    assert not theme.wanted({"XDG_CURRENT_DESKTOP": "GNOME", name: "kvantum"})


def test_the_two_palettes_differ_in_the_background():
    QApplication.instance() or QApplication([])
    light, dark = theme.palette(False), theme.palette(True)
    assert light.color(QPalette.ColorRole.Base).lightness() > 200
    assert dark.color(QPalette.ColorRole.Base).lightness() < 60
    assert light.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text) != light.color(QPalette.ColorRole.Text)
