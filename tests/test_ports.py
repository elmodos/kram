"""The Ui port's helpers, and the Qt implementation of its questions."""
import os

import pytest

from kram.app.ports import CANCEL, YES, Button, Question, RecordingUi, is_web_link, parse_filters


def test_only_web_links():
    assert is_web_link("https://example.org") and is_web_link("HTTP://example.org")
    assert not any(map(is_web_link, ["file:///etc/passwd", "smb://x", "javascript:alert(1)", "example.org", ""]))


def test_filters_in_qt_syntax():
    assert parse_filters("Text files (*.txt);;All files (*)") == [("Text files", ["*.txt"]), ("All files", ["*"])]
    assert parse_filters("RPM packages (*.rpm)") == [("RPM packages", ["*.rpm"])]


def test_recording_ui_answers_in_order():
    ui = RecordingUi(answers=["yes"])
    got = []
    ui.ask(Question("t", "q"), got.append)
    ui.ask(Question("t", "q"), got.append)
    assert got == ["yes", None] and ui.kinds() == ["ask", "ask"]


@pytest.fixture
def qt_app():
    pytest.importorskip("PySide6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_qt_ask_returns_the_button_pressed(qt_app, monkeypatch):
    from kram.qt import qt_ui

    shown = []

    def exec_(box):
        shown.append([b.text() for b in box.buttons()])
        box.buttons()[pressed[0]].click()
        return 0
    monkeypatch.setattr(qt_ui.QMessageBox, "exec", exec_)
    got = []
    pressed = [0]
    question = Question("Title", "Text", (Button("mark", "Mark", "accept"), CANCEL), default="mark")
    qt_ui.QtUi(None).ask(question, got.append)
    assert "Mark" in shown[0] and got[0] in ("mark", "cancel")
    clicked = got[0]
    pressed[0] = 1
    qt_ui.QtUi(None).ask(question, got.append)
    assert {clicked, got[1]} == {"mark", "cancel"}
    pressed[0] = 0
    qt_ui.QtUi(None).ask(Question("t", "q", (YES,)), got.append)
    assert got[2] == "yes"
