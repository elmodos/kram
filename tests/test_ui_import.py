"""Every UI module imports and the painted icons render, without a display (also run by the RPM's %check)."""
import importlib
import os
import pkgutil

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

import kram.ui


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_ui_modules_import():
    for mod in pkgutil.iter_modules(kram.ui.__path__):
        importlib.import_module(f"kram.ui.{mod.name}")


def test_icons_render(app):
    from kram.core.marks import Action
    from kram.core.model import Origin, Status
    from kram.ui.icons import mark_icon, origin_icon, status_icon

    icons = [*map(status_icon, Status), *map(origin_icon, Origin), *map(mark_icon, Action)]
    for icon in icons:
        for scale in (1.0, 1.25, 2.0):
            pm = icon.pixmap(QSize(16, 16), scale)
            assert pm.width() == round(16 * scale)
            assert not pm.toImage().isNull()
