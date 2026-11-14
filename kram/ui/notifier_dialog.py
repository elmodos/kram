"""Settings → Update Notifications: the tray update checker (kram.notifier), Fedora's metadata timer it relies on,
and other programs' update notifiers that would show a second icon."""
import os
import signal
from pathlib import Path

from PySide6.QtCore import QEvent, QProcess, QSettings, QSize, Qt
from PySide6.QtDBus import QDBusConnection
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import APP_ID
from ..i18n import _, ngettext
from ..notifier import STALE_DAYS_DEFAULT, control
from .files import show_in_file_manager

TRAY_HOST = "org.kde.StatusNotifierWatcher"
STALE_DAYS_KEY = "update_checker/stale_days"  # read without Qt by kram.notifier.stale_days()
# icon names in the order to try (not every theme has them); checked with Breeze and Papirus, light and dark.
# Monochrome for the actions, the program's own colours for headings and programs.
FEDORA_ICONS = ("fedora-logo-icon", "distributor-logo", "system-software-update")
ON_ICONS = ("dialog-ok-apply",)  # emblem-ok-symbolic vanishes on a dark Papirus palette
OFF_ICONS = ("dialog-warning",)
TURN_ON_ICONS = ("media-playback-start",)
TURN_OFF_ICONS = ("system-shutdown",)
FILE_MANAGER_ICONS = ("document-open-folder",)  # not folder-*: colourful folders in Papirus
NOTIFIER_FALLBACK_ICONS = ("system-software-install",)
SMALL, LARGE = QSize(16, 16), QSize(32, 32)


def _dimmed(label: QLabel) -> QLabel:
    palette = label.palette()
    color = palette.color(QPalette.WindowText)
    color.setAlpha(170)
    palette.setColor(QPalette.WindowText, color)
    label.setPalette(palette)
    return label


def _text(text: str = "", dimmed: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return _dimmed(label) if dimmed else label


def _icon(names: tuple[str, ...]) -> QIcon:
    return next((QIcon.fromTheme(name) for name in names if QIcon.hasThemeIcon(name)), QIcon())


def _picture(names: tuple[str, ...], size: QSize) -> QLabel:
    label = QLabel()
    label.setFixedSize(size)
    label.setPixmap(_icon(names).pixmap(size))
    return label


def _beside(picture: QLabel, widget: QWidget, top: bool = False) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(picture, 0, Qt.AlignTop if top else Qt.AlignVCenter)
    row.addWidget(widget, 1)
    return row


def _tray_picture() -> QLabel:
    """The tray icon itself: installed in hicolor, or next to the package in a source checkout."""
    name = f"{APP_ID}-update-medium"
    source = Path(__file__).resolve().parents[2] / "data" / "icons" / f"{name}.svg"
    label = QLabel()
    label.setFixedSize(SMALL)
    label.setPixmap(QIcon.fromTheme(name, QIcon(str(source))).pixmap(SMALL))
    return label


def _bus_owner_pid(name: str) -> int | None:
    interface = QDBusConnection.sessionBus().interface()
    if interface is None or not interface.isServiceRegistered(name).value():
        return None
    return interface.servicePid(name).value() or None


class _NotifierRow(QWidget):
    """Another program's update notifier: what it does to ours, and turning it off or back on for this user."""

    def __init__(self, notifier: control.Notifier, parent: "NotifierDialog"):
        super().__init__()
        self.notifier = notifier
        self.dialog = parent
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        outer.addWidget(_picture(notifier.icons + NOTIFIER_FALLBACK_ICONS, LARGE), 0, Qt.AlignTop)
        lay = QVBoxLayout()
        outer.addLayout(lay, 1)
        self.state = _text()
        lay.addWidget(self.state)
        buttons = QHBoxLayout()
        self.toggle = QPushButton()
        self.toggle.clicked.connect(self._toggle)
        show = QPushButton(_icon(FILE_MANAGER_ICONS), _("Show in File Manager"))
        show.clicked.connect(self._show)
        buttons.addWidget(self.toggle)
        buttons.addWidget(show)
        buttons.addStretch(1)
        lay.addLayout(buttons)

    def refresh(self) -> None:
        name = self.notifier.name
        if self.notifier.turned_off():
            self.state.setText(_("{program}'s update notifier is turned off for you.").format(program=name))
            self.toggle.setText(_("Turn Back On"))
            self.toggle.setIcon(_icon(TURN_ON_ICONS))
            self.toggle.setToolTip(_("It starts again at your next login"))
        else:
            running = _bus_owner_pid(self.notifier.bus_name) is not None
            self.state.setText(
                (_("{program}'s update notifier is running.") if running else
                 _("{program}'s update notifier starts at login.")).format(program=name) + " " +
                _("It checks for updates too: you would see two icons, and PackageKit downloads its own copy of the "
                  "package information. Keep it and leave Kram's icon off, or turn it off."))
            self.toggle.setText(_("Turn Off"))
            self.toggle.setIcon(_icon(TURN_OFF_ICONS))
            self.toggle.setToolTip(_("Only for you: stops it now and at every login"))

    def _toggle(self) -> None:
        try:
            if self.notifier.turned_off():
                self.notifier.turn_on()
            else:
                self.notifier.turn_off()
                if pid := _bus_owner_pid(self.notifier.bus_name):
                    os.kill(pid, signal.SIGTERM)
        except OSError as e:
            QMessageBox.warning(self, _("Update Notifications"), str(e))
        self.refresh()

    def _show(self) -> None:
        override = self.notifier.override()
        show_in_file_manager(str(override if override and override.exists() else self.notifier.system_file()))


class NotifierDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Update Notifications"))
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        self.enabled = QCheckBox(_("Show an icon in the system tray when updates are available"))
        self.enabled.setChecked(control.checker_enabled())
        self.enabled.toggled.connect(self._set_enabled)
        lay.addLayout(_beside(_tray_picture(), self.enabled))
        lay.addWidget(_text(_("The icon is there only while updates are available. Kram downloads nothing in the "
                              "background: Fedora's own service refreshes the package information, Kram only reads "
                              "it, at login, hourly and after every installation."), dimmed=True))
        self.no_tray = QWidget()
        self.no_tray.setLayout(_beside(_picture(OFF_ICONS, SMALL), _text(_(
            "This session has no system tray for such icons (GNOME without the AppIndicator extension, LXDE), so "
            "the icon cannot appear.")), top=True))
        self.no_tray.layout().setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.no_tray)

        stale = QHBoxLayout()
        stale.addWidget(QLabel(_("Warn when the package information is older than:")))
        self.stale_days = QSpinBox()
        self.stale_days.setRange(1, 365)
        self.stale_days.valueChanged.connect(self._set_stale_days)
        self.stale_days.setValue(QSettings().value(STALE_DAYS_KEY, STALE_DAYS_DEFAULT, type=int))
        self._set_stale_days(self.stale_days.value())
        stale.addWidget(self.stale_days)
        stale.addStretch(1)
        self.stale_row = QWidget()
        self.stale_row.setLayout(stale)
        stale.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stale_row)

        self.fedora_heading = QWidget()
        self.fedora_heading.setLayout(_beside(_picture(FEDORA_ICONS, SMALL),
                                              QLabel("<b>" + _("Fedora's update check") + "</b>")))
        self.fedora_heading.layout().setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.fedora_heading)
        self.fedora_state = _text()
        self.fedora_state_icon = _picture((), SMALL)
        self.fedora_state_row = QWidget()
        self.fedora_state_row.setLayout(_beside(self.fedora_state_icon, self.fedora_state, top=True))
        self.fedora_state_row.layout().setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.fedora_state_row)
        self.fedora_button = QPushButton(_icon(TURN_ON_ICONS), _("Turn On Fedora's Update Check…"))
        self.fedora_button.setToolTip(_("Asks for your password"))
        self.fedora_button.clicked.connect(self._enable_fedora_timer)
        row = QHBoxLayout()
        row.addWidget(self.fedora_button)
        row.addStretch(1)
        lay.addLayout(row)
        self._systemctl = None

        self.rows = [_NotifierRow(n, self) for n in control.NOTIFIERS if n.system_file()]
        if self.rows:
            lay.addWidget(QLabel("<b>" + _("Other update notifiers") + "</b>"))
            for notifier_row in self.rows:
                lay.addWidget(notifier_row)

        lay.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.refresh()

    def event(self, event: QEvent) -> bool:
        # everything here can change outside Kram while the dialog is open: the user deletes the autostart file in
        # the file manager it showed, turns a timer on in a terminal, a tray host or a notifier starts
        if event.type() == QEvent.WindowActivate:
            self.refresh()
        return super().event(event)

    def refresh(self) -> None:
        if self.enabled.isChecked() != (enabled := control.checker_enabled()):
            self.enabled.blockSignals(True)
            self.enabled.setChecked(enabled)
            self.enabled.blockSignals(False)
        on = self.enabled.isChecked()
        interface = QDBusConnection.sessionBus().interface()
        has_tray = interface is not None and interface.isServiceRegistered(TRAY_HOST).value()
        self.no_tray.setVisible(not has_tray)
        self.stale_row.setEnabled(on)

        state = control.fedora_timer_state()
        for widget in (self.fedora_heading, self.fedora_state_row):
            widget.setVisible(state != "missing")
        self.fedora_state_icon.setPixmap(_icon(ON_ICONS if state == "enabled" else OFF_ICONS).pixmap(SMALL))
        self.fedora_button.setVisible(state == "disabled")
        self.fedora_button.setEnabled(self._systemctl is None)
        self.fedora_state.setText(
            _("On: dnf-makecache.timer refreshes the package information every few hours, when the computer is not "
              "on battery.") if state == "enabled" else
            _("Off: dnf-makecache.timer is disabled, so Kram only sees new updates after a Reload."))
        for notifier_row in self.rows:
            notifier_row.refresh()

    def _set_stale_days(self, days: int) -> None:
        self.stale_days.setSuffix(" " + ngettext("day", "days", days))
        QSettings().setValue(STALE_DAYS_KEY, days)

    def _set_enabled(self, on: bool) -> None:
        if error := control.set_checker_enabled(on):
            QMessageBox.warning(self, _("Update Notifications"), error)
            self.enabled.blockSignals(True)
            self.enabled.setChecked(control.checker_enabled())
            self.enabled.blockSignals(False)
        self.refresh()

    def _enable_fedora_timer(self) -> None:
        # asynchronous: systemd waits for the password in the desktop's polkit dialog
        self._systemctl = QProcess(self)
        self._systemctl.finished.connect(self._fedora_timer_done)
        self._systemctl.start("systemctl", ["enable", "--now", control.FEDORA_TIMER])
        self.refresh()

    def _fedora_timer_done(self, code: int, _status) -> None:
        process, self._systemctl = self._systemctl, None
        error = bytes(process.readAllStandardError()).decode(errors="replace").strip()
        process.deleteLater()
        if code != 0 and error:
            QMessageBox.warning(self, _("Update Notifications"), error)
        self.refresh()
