"""One Kram per session: the D-Bus service the first Kram exports, and what the main window does with a request."""
import os
from types import SimpleNamespace

import pytest

from kram.app.parity import Feature  # noqa: E402  (the feature marks of the parity tests)

pytest.importorskip("PySide6.QtDBus")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kram import instance  # noqa: E402
from kram.app.browser import Browser  # noqa: E402
from kram.qt import (
    main_window,  # noqa: E402
    single_instance,  # noqa: E402
)


def test_service_passes_the_view_and_keeps_the_token(monkeypatch):
    monkeypatch.delenv("XDG_ACTIVATION_TOKEN", raising=False)
    seen = []
    service = single_instance.Service(seen.append)
    service.Activate("upgradable", "token-1")
    assert seen == ["upgradable"]
    assert os.environ["XDG_ACTIVATION_TOKEN"] == "token-1"  # Qt's Wayland backend uses it to raise the window
    service.Activate("", "")
    assert seen == ["upgradable", ""]


def _window(loaded: bool):
    """A stand-in for the main window: the real one loads the whole catalog."""
    calls = []
    browser = SimpleNamespace(
        filter=object() if loaded else None, _restore_filter=("status", "status:all"),
        sidebar=SimpleNamespace(select=lambda view, entry: calls.append(("select", view, entry))))
    window = SimpleNamespace(
        browser=browser, isMinimized=lambda: False, show=lambda: calls.append("show"),
        raise_=lambda: calls.append("raise"), activateWindow=lambda: calls.append("activate"))
    window.show_view = lambda view: Browser.show_view(browser, view)
    return calls, window


def test_upgradable_while_loading_is_selected_after_the_load():
    calls, window = _window(loaded=False)
    window.show_view(instance.UPGRADABLE)
    assert window.browser._restore_filter == ("status", "status:upgradable") and calls == []


@pytest.mark.feature(Feature.SINGLE_INSTANCE_TRAY, front="qt")
def test_upgradable_when_loaded_selects_it_now():
    calls, window = _window(loaded=True)
    window.show_view(instance.UPGRADABLE)
    window.show_view("")  # a plain `kram`: the filter stays
    assert calls == [("select", "status", "status:upgradable")]


def test_a_dialog_stays_open_and_comes_to_the_front(monkeypatch):
    calls, window = _window(loaded=True)
    dialog = SimpleNamespace(raise_=lambda: calls.append("dialog raise"),
                             activateWindow=lambda: calls.append("dialog activate"))
    monkeypatch.setattr(main_window, "QApplication", SimpleNamespace(activeModalWidget=lambda: dialog))
    main_window.MainWindow.activate_from_outside(window, instance.UPGRADABLE)
    assert calls == ["show", "raise", "dialog raise", "dialog activate"]  # no filter change, nothing closed
    calls.clear()
    monkeypatch.setattr(main_window, "QApplication", SimpleNamespace(activeModalWidget=lambda: None))
    main_window.MainWindow.activate_from_outside(window, instance.UPGRADABLE)
    assert calls == [("select", "status", "status:upgradable"), "show", "raise", "raise", "activate"]
