"""Runs one helper request (transaction or metadata refresh) and shows its progress (kram.app.progress)."""
import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
)

from ..app.progress import BUSY, WAITING, Bar, Progress, Stage, shows_download, shows_rpm
from ..core.settings import store as settings
from ..i18n import _
from ..ipc.client import HelperClient
from .qt_ui import QtUi

ERROR_COLOR = "#c03030"


class ProgressDialog(QDialog):
    def __init__(self, client: HelperClient, request: dict, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 460)
        self.client = client
        self.request = request
        self.progress = Progress(client, request, self, QtUi(self))

        lay = QVBoxLayout(self)
        self.title = QLabel(f"<b>{title}</b>")
        lay.addWidget(self.title)
        self.stage = QLabel(_(WAITING))
        self.stage.setWordWrap(True)
        lay.addWidget(self.stage)
        self.download_label = QLabel(_("Download"))
        self.download_bar = QProgressBar()
        self.rpm_label = QLabel(_("Installation"))
        self.rpm_bar = QProgressBar()
        for w in (self.download_label, self.download_bar, self.rpm_label, self.rpm_bar):
            lay.addWidget(w)
        self.rpm_label.setVisible(shows_rpm(request))
        self.rpm_bar.setVisible(shows_rpm(request))
        self.download_label.setVisible(shows_download(request))
        self.download_bar.setVisible(shows_download(request))
        self.download_bar.setRange(0, 0)  # busy until the first download reports its size

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        box = QGroupBox(_("Details"))
        QVBoxLayout(box).addWidget(self.log)
        lay.addWidget(box, 1)

        self.auto_close = QCheckBox(_("Close when finished successfully"))
        self.auto_close.setChecked(settings.get("progress/auto_close", False))
        lay.addWidget(self.auto_close)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        self.buttons.setEnabled(False)
        lay.addWidget(self.buttons)

    # the outcome, for the callers
    ok = property(lambda self: self.progress.ok)
    result = property(lambda self: self.progress.result)
    running = property(lambda self: self.progress.running)

    def exec(self) -> int:
        if not self.progress.start():
            QMessageBox.warning(self.parentWidget(), self.windowTitle(), _(BUSY))
            return QDialog.DialogCode.Rejected
        return super().exec()

    def done(self, result: int) -> None:
        if self.progress.running:  # no closing mid-transaction (Esc, window close)
            return
        settings.set("progress/auto_close", self.auto_close.isChecked())
        self.progress.stop()
        super().done(result)

    def _on_event(self, ev: dict) -> None:
        self.progress.on_event(ev)

    # ---------------------------------------------------------------- ProgressView

    def show_stage(self, stage: Stage) -> None:
        if stage.kind == "done":
            self.stage.setText(f"<b>{stage.text}</b>" + (" " + stage.detail if stage.detail else ""))
        elif stage.kind == "error":
            self.stage.setText(f"<span style='color:{ERROR_COLOR}'><b>{stage.text}</b> {html.escape(stage.detail)}"
                               "</span>")
            self.stage.setTextFormat(Qt.TextFormat.RichText)
        else:
            self.stage.setText(stage.text)

    @staticmethod
    def _set_bar(bar: QProgressBar, label: QLabel, value: Bar, text: str | None) -> None:
        bar.setRange(0, value.maximum)
        bar.setValue(value.value)
        if text is not None:
            label.setText(text)

    def show_download(self, bar: Bar, label: str | None) -> None:
        self._set_bar(self.download_bar, self.download_label, bar, label)

    def show_rpm(self, bar: Bar, label: str | None) -> None:
        self._set_bar(self.rpm_bar, self.rpm_label, bar, label)

    def append_log(self, line: str) -> None:
        self.log.appendPlainText(line)

    def request_done(self, ok: bool) -> None:
        self.buttons.setEnabled(True)
        if ok and self.auto_close.isChecked():
            self.accept()
