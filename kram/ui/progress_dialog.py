"""Runs one helper request (transaction or metadata refresh) and shows its progress."""
import html
from datetime import datetime

from PySide6.QtCore import QSettings, Qt
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

from ..i18n import N_, _, ngettext
from ..ipc.client import HelperClient
from .package_model import human_size

STEP_TEXT = {"install": N_("Installing {nevra}"), "remove": N_("Removing {nevra}"),
             "script": N_("Running scriptlet {script} of {nevra}")}
# keys of the helper's "log" events (see kram_helper.log); unknown keys fall back to the English text
HELPER_MESSAGES = {
    "loading_repos": N_("Loading repositories…"),
    "refreshing": N_("Refreshing repository metadata…"),
    "mirror_failure": N_("Mirror unavailable: {url}: {error}"),
    "script_error": N_("Scriptlet {script} of {nevra} failed with exit code {code}"),
    "key_imported": N_("Imported key {key_id}"),
}


class ProgressDialog(QDialog):
    def __init__(self, client: HelperClient, request: dict, title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 460)
        self.client = client
        self.request = request
        self.ok = False
        self.running = True
        self._downloads: dict[int, tuple[float, float]] = {}  # id -> (done, total)

        lay = QVBoxLayout(self)
        self.title = QLabel(f"<b>{title}</b>")
        lay.addWidget(self.title)
        self.stage = QLabel(_("Waiting for authentication…"))
        self.stage.setWordWrap(True)
        lay.addWidget(self.stage)
        self.download_label = QLabel(_("Download"))
        self.download_bar = QProgressBar()
        self.rpm_label = QLabel(_("Installation"))
        self.rpm_bar = QProgressBar()
        for w in (self.download_label, self.download_bar, self.rpm_label, self.rpm_bar):
            lay.addWidget(w)
        self.rpm_label.setVisible(request.get("op") == "transaction")
        self.rpm_bar.setVisible(request.get("op") == "transaction")
        self.download_bar.setRange(0, 0)  # busy until the first download reports its size

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        box = QGroupBox(_("Details"))
        QVBoxLayout(box).addWidget(self.log)
        lay.addWidget(box, 1)

        self.auto_close = QCheckBox(_("Close when finished successfully"))
        self.auto_close.setChecked(QSettings().value("progress/auto_close", False, type=bool))
        lay.addWidget(self.auto_close)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.buttons.rejected.connect(self.reject)
        self.buttons.setEnabled(False)
        lay.addWidget(self.buttons)

        client.event.connect(self._on_event)
        client.failed.connect(self._on_failed)

    def exec(self) -> int:
        self.client.request(self.request)
        return super().exec()

    def done(self, result: int) -> None:
        if self.running:  # no closing mid-transaction (Esc, window close)
            return
        QSettings().setValue("progress/auto_close", self.auto_close.isChecked())
        self.client.event.disconnect(self._on_event)
        self.client.failed.disconnect(self._on_failed)
        super().done(result)

    def _append(self, text: str) -> None:
        self.log.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    def _on_event(self, ev: dict) -> None:
        kind = ev.get("event")
        if kind == "log":
            self._append(self._log_text(ev))
        elif kind == "resolved":
            n = len(ev["items"])
            self.stage.setText(ngettext("The transaction has {n} package. Downloading…",
                                        "The transaction has {n} packages. Downloading…", n).format(n=n))
            for item in ev["items"]:
                self._append(f"{item['action']:>10}  {item['nevra']}")
        elif kind == "download":
            self._on_download(ev)
        elif kind == "rpm":
            self._on_rpm(ev)
        elif kind == "question":
            self._on_question(ev)
        elif kind == "done":
            self._finish(ev)

    @staticmethod
    def _log_text(ev: dict) -> str:
        template = HELPER_MESSAGES.get(ev.get("key"))
        if template is None:
            return ev.get("text", "")
        try:
            return _(template).format(**ev.get("params", {}))
        except (KeyError, IndexError):  # a translation with wrong placeholders must not break the log
            return ev.get("text", "")

    def _on_download(self, ev: dict) -> None:
        i = ev["id"]
        if "name" in ev:
            self._append(_("Downloading {name}").format(name=ev["name"]))
        if ev.get("end"):
            done, total = self._downloads.get(i, (0, 0))
            self._downloads[i] = (total, total)
            if not ev.get("ok"):
                self._append(_("Download failed: {error}").format(error=ev.get("msg")))
        else:
            self._downloads[i] = (ev.get("done", 0), ev.get("total", 0))
        done = sum(d for d, _ in self._downloads.values())
        total = sum(t for _, t in self._downloads.values())
        if total > 0:
            self.download_bar.setRange(0, 1000)
            self.download_bar.setValue(int(1000 * done / total))
            self.download_label.setText(_("Downloaded {done} of {total}").format(done=human_size(int(done)),
                                                                                  total=human_size(int(total))))

    def _on_rpm(self, ev: dict) -> None:
        step = ev.get("step")
        self.download_bar.setRange(0, 1000)
        self.download_bar.setValue(1000)
        if step == "prepare":
            self.stage.setText(_("Preparing the rpm transaction…"))
        elif step == "element":
            self.rpm_bar.setRange(0, max(ev["count"], 1))
            self.rpm_bar.setValue(ev["index"])
            self.rpm_label.setText(_("Package {index} of {count}").format(index=ev["index"], count=ev["count"]))
        elif step in STEP_TEXT:
            text = _(STEP_TEXT[step]).format(nevra=ev["nevra"], script=ev.get("script", ""))
            self.stage.setText(text)
            if step != "script" and ev.get("done") == 0:
                self._append(text)

    def _on_question(self, ev: dict) -> None:
        if ev.get("kind") != "gpg_key":
            self.client.answer(ev["id"], False)
            return
        when = datetime.fromtimestamp(ev["timestamp"]).strftime("%Y-%m-%d") if ev.get("timestamp") else "?"
        text = _("Import the OpenPGP key used to verify packages?\n\n"
                 "User: {user}\nFingerprint: {fingerprint}\nCreated: {created}\nFrom: {url}").format(
            user=", ".join(ev.get("user_ids", [])), fingerprint=ev.get("fingerprint"), created=when, url=ev.get("url"))
        yes = QMessageBox.question(self, _("Import key"), text) == QMessageBox.Yes
        self._append((_("Key {key_id}: importing") if yes else _("Key {key_id}: rejected")).format(key_id=ev.get("key_id")))
        self.client.answer(ev["id"], yes)

    def _finish(self, ev: dict) -> None:
        self.running = False
        self.ok = bool(ev.get("ok"))
        self.buttons.setEnabled(True)
        if self.ok:
            self.download_bar.setRange(0, 1)
            self.download_bar.setValue(1)
            self.rpm_bar.setRange(0, 1)
            self.rpm_bar.setValue(1)
            self.stage.setText(f"<b>{_('Done.')}</b>" + (" " + _("Packages downloaded.") if ev.get("download_only") else ""))
            self._append(_("Done."))
            if self.auto_close.isChecked():
                self.accept()
        else:
            self._show_error(ev.get("error", _("unknown error")), ev.get("details") or [])

    def _on_failed(self, message: str) -> None:
        self.running = False
        self.buttons.setEnabled(True)
        self._show_error(message, [])

    def _show_error(self, message: str, details: list[str]) -> None:
        first = html.escape((message.splitlines() or [_("unknown error")])[0])
        self.stage.setText(f"<span style='color:#c03030'><b>{_('Error:')}</b> {first}</span>")
        self.stage.setTextFormat(Qt.RichText)
        self._append(_("ERROR: {message}").format(message=message))
        for d in details:
            self._append("  " + d)
