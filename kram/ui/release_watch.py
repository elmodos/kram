"""Settings → Watch Fedora Releases: on Reload, ask Fedora's Bodhi service whether a new release is out, and offer
it with a toolbar button until the system has reached it."""
import json

from PySide6.QtCore import QObject, QSettings, QUrl
from PySide6.QtGui import QAction, QIcon
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply

from ..core import distro
from ..i18n import _
from .upgrade_dialog import api_request

RELEASE_CHECK_TIMEOUT_MS = 15000


class ReleaseWatcher(QObject):
    """`act_watch` is the setting; `act_upgrade` the toolbar button, which the window connects to its dialog."""

    def __init__(self, parent: QObject):
        super().__init__(parent)
        self.running = distro.running_release()
        self._net = QNetworkAccessManager(self)

        self.act_watch = QAction(_("Watch Fedora Releases"), self, checkable=True)
        self.act_watch.setToolTip(_("On Reload, ask Fedora's Bodhi service whether a new release is out"))
        self.act_watch.setStatusTip(self.act_watch.toolTip())
        self.act_watch.setVisible(self.running is not None)
        self.act_watch.toggled.connect(self._on_watch)

        self.act_upgrade = QAction(QIcon.fromTheme("fedora-logo-icon", QIcon.fromTheme("system-upgrade")),
                                   "Fedora", self)
        self.act_upgrade.setToolTip(_("A new Fedora release"))
        self.act_upgrade.setStatusTip(self.act_upgrade.toolTip())
        self.act_upgrade.setEnabled(False)
        self.act_upgrade.setVisible(False)

    def restore(self) -> None:
        self.act_watch.setChecked(QSettings().value("distro/watch", True, type=bool))
        self.update_button()

    def _on_watch(self, on: bool) -> None:
        QSettings().setValue("distro/watch", on)
        self.update_button()

    def target(self) -> int | None:
        """The release the button offers, from the last check. Gone once the system has reached it."""
        target = QSettings().value("distro/target", 0, type=int)
        running = self.running
        if running is None or not self.act_watch.isChecked():
            return None
        return target if running < target <= running + distro.MAX_RELEASE_JUMP else None

    def running_eol(self) -> str:
        """The end of life of the running release, from the last check: "" when not known."""
        return QSettings().value("distro/running_eol", "")

    def update_button(self) -> None:
        target = self.target()
        self.act_upgrade.setVisible(target is not None)
        if target is not None:
            self.act_upgrade.setText(f"Fedora {target}")
            tip = _("Fedora {new} is available, you have {old}").format(new=target, old=self.running)
            self.act_upgrade.setToolTip(tip)
            self.act_upgrade.setStatusTip(tip)

    def check(self) -> None:
        """Ask Bodhi, when watching; the button follows the answer. No network is no news."""
        if self.running is None or not self.act_watch.isChecked():
            return
        reply = self._net.get(api_request(QUrl(distro.BODHI_RELEASES_URL), RELEASE_CHECK_TIMEOUT_MS))
        reply.finished.connect(lambda: self._on_reply(reply))

    def _on_reply(self, reply: QNetworkReply) -> None:
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            return  # the last result stays
        try:
            releases = distro.parse_releases(json.loads(bytes(reply.readAll())))
        except ValueError:
            return
        if not releases:
            return
        target = distro.choose_target(self.running, releases)
        settings = QSettings()
        settings.setValue("distro/target", target.version if target else 0)
        settings.setValue("distro/running_eol", next((r.eol for r in releases if r.version == self.running), ""))
        self.update_button()
