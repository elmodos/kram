"""The Qt implementation of kram.app.ports.Ui: message boxes, file dialogs, links, the clipboard.

Qt's dialogs are modal and block in exec(): every continuation is called before the method returns. That is
allowed by the port and keeps Qt's behaviour exactly as it was before the port existed.
"""
import weakref
from collections.abc import Callable

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from ..app.ports import STANDARD, Question
from .files import show_in_file_manager
from .links import open_web_link

_ICONS = {"question": QMessageBox.Icon.Question, "info": QMessageBox.Icon.Information,
          "warning": QMessageBox.Icon.Warning, "error": QMessageBox.Icon.Critical, "none": QMessageBox.Icon.NoIcon}
_STANDARD_BUTTONS = {"yes": QMessageBox.StandardButton.Yes, "no": QMessageBox.StandardButton.No,
                     "ok": QMessageBox.StandardButton.Ok, "cancel": QMessageBox.StandardButton.Cancel,
                     "close": QMessageBox.StandardButton.Close}
_ROLES = {"accept": QMessageBox.ButtonRole.AcceptRole, "reject": QMessageBox.ButtonRole.RejectRole,
          "action": QMessageBox.ButtonRole.ActionRole, "destructive": QMessageBox.ButtonRole.DestructiveRole}


class QtUi:
    """Dialogs belong to `parent`; `status(text, ms)` shows a status bar message (the window's), if given."""

    def __init__(self, parent: QWidget | None, status: Callable[[str, int], None] | None = None):
        # weakly: a dialog keeps the logic that keeps this, and a dialog in a reference cycle is freed by the garbage
        # collector at a random moment (see kram.app.ports.view_ref)
        self._parent_ref = weakref.ref(parent) if parent is not None else None
        self._status = status

    @property
    def _parent(self) -> QWidget | None:
        return self._parent_ref() if self._parent_ref is not None else None

    def _message(self, icon: QMessageBox.Icon, title: str, text: str, informative: str, details: str) -> None:
        if not informative and not details:  # Qt's static functions: the tests stub them
            {QMessageBox.Icon.Information: QMessageBox.information, QMessageBox.Icon.Warning: QMessageBox.warning,
             QMessageBox.Icon.Critical: QMessageBox.critical}[icon](self._parent, title, text)
            return
        box = QMessageBox(icon, title, text, QMessageBox.StandardButton.Ok, self._parent)
        if informative:
            box.setInformativeText(informative)
        if details:
            box.setDetailedText(details)
        box.exec()
        box.deleteLater()

    def info(self, title: str, text: str, informative: str = "", details: str = "") -> None:
        self._message(QMessageBox.Icon.Information, title, text, informative, details)

    def warn(self, title: str, text: str, informative: str = "", details: str = "") -> None:
        self._message(QMessageBox.Icon.Warning, title, text, informative, details)

    def error(self, title: str, text: str, informative: str = "", details: str = "") -> None:
        self._message(QMessageBox.Icon.Critical, title, text, informative, details)

    def status(self, text: str, timeout_ms: int = 0) -> None:
        if self._status is not None:
            self._status(text, timeout_ms)

    def ask(self, question: Question, done: Callable[[str | None], None]) -> None:
        box = QMessageBox(_ICONS[question.icon], question.title, question.text, parent=self._parent)
        if question.informative:
            box.setInformativeText(question.informative)
        if question.details:
            box.setDetailedText(question.details)
        buttons = {}
        for button in question.buttons:
            if button.label == "" and button.id in STANDARD:
                buttons[button.id] = box.addButton(_STANDARD_BUTTONS[button.id])
            else:
                buttons[button.id] = box.addButton(button.label, _ROLES[button.role])
        if question.default in buttons:
            box.setDefaultButton(buttons[question.default])
        box.exec()
        clicked = box.clickedButton()
        box.deleteLater()
        done(next((i for i, b in buttons.items() if b is clicked), None))

    def choose_open_file(self, title: str, start_dir: str, filters: str, done: Callable[[str | None], None]) -> None:
        path, _filter = QFileDialog.getOpenFileName(self._parent, title, start_dir, filters)
        done(path or None)

    def choose_save_file(self, title: str, start_path: str, filters: str,
                         done: Callable[[str | None], None]) -> None:
        path, _filter = QFileDialog.getSaveFileName(self._parent, title, start_path, filters)
        done(path or None)

    def open_web_link(self, url: str) -> bool:
        return open_web_link(QUrl(url))

    def show_in_file_manager(self, path: str) -> None:
        show_in_file_manager(path)

    def copy_text(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    def is_modal_open(self) -> bool:
        return QApplication.activeModalWidget() is not None
