"""Settings → Update Notifications (kram.app.notifier)."""
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import APP_ID
from ..app import preferences
from ..app.notifier import (
    FEDORA_ICONS,
    FILE_MANAGER_ICONS,
    NOTIFIER_FALLBACK_ICONS,
    OFF_ICONS,
    TURN_ON_ICONS,
    Notifications,
    NotificationsState,
    NotifierLine,
    notifier_file,
)
from ..i18n import _
from ..notifier import control
from .files import QtBus, show_in_file_manager
from .qt_loop import post
from .qt_ui import QtUi

SMALL, LARGE = QSize(16, 16), QSize(32, 32)


def _dimmed(label: QLabel) -> QLabel:
    palette = label.palette()
    color = palette.color(QPalette.ColorRole.WindowText)
    color.setAlpha(170)
    palette.setColor(QPalette.ColorRole.WindowText, color)
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
    row.addWidget(picture, 0, Qt.AlignmentFlag.AlignTop if top else Qt.AlignmentFlag.AlignVCenter)
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


bus = QtBus()  # kram.app.ports.Bus; tests put a FakeBus here


class _NotifierRow(QWidget):
    """Another program's update notifier: what it does to ours, and turning it off or back on for this user."""

    def __init__(self, notifier: control.Notifier, notifications: Notifications):
        super().__init__()
        self.notifier = notifier
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        outer.addWidget(_picture(notifier.icons + NOTIFIER_FALLBACK_ICONS, LARGE), 0, Qt.AlignmentFlag.AlignTop)
        lay = QVBoxLayout()
        outer.addLayout(lay, 1)
        self.state = _text()
        lay.addWidget(self.state)
        buttons = QHBoxLayout()
        self.toggle = QPushButton()
        self.toggle.clicked.connect(lambda: notifications.toggle(notifier))
        show = QPushButton(_icon(FILE_MANAGER_ICONS), _("Show in File Manager"))
        show.clicked.connect(lambda: show_in_file_manager(notifier_file(notifier)))
        buttons.addWidget(self.toggle)
        buttons.addWidget(show)
        buttons.addStretch(1)
        lay.addLayout(buttons)

    def show_line(self, line: NotifierLine) -> None:
        self.state.setText(line.text)
        self.toggle.setText(line.toggle_text)
        self.toggle.setIcon(_icon(line.toggle_icons))
        self.toggle.setToolTip(line.toggle_tip)


class NotifierDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.notifications = Notifications(self, QtUi(self), bus, post)
        self.setWindowTitle(_("Update Notifications"))
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        self.enabled = QCheckBox(_("Show an icon in the system tray when updates are available"))
        self.enabled.toggled.connect(self.notifications.set_enabled)
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
        stale_pref = preferences.pref(preferences.STALE_DAYS)
        stale.addWidget(QLabel(stale_pref.label))
        self.stale_days = QSpinBox()
        self.stale_days.setRange(*stale_pref.range)
        self.stale_days.valueChanged.connect(self._set_stale_days)
        self.stale_days.setValue(preferences.value(stale_pref))
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
        self.fedora_button.clicked.connect(self.notifications.enable_fedora_timer)
        row = QHBoxLayout()
        row.addWidget(self.fedora_button)
        row.addStretch(1)
        lay.addLayout(row)

        self.rows = [_NotifierRow(n, self.notifications) for n in self.notifications.notifiers]
        if self.rows:
            lay.addWidget(QLabel("<b>" + _("Other update notifiers") + "</b>"))
            for notifier_row in self.rows:
                lay.addWidget(notifier_row)

        lay.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.notifications.refresh()

    def event(self, event: QEvent) -> bool:
        # everything here can change outside Kram while the dialog is open: the user deletes the autostart file in
        # the file manager it showed, turns a timer on in a terminal, a tray host or a notifier starts
        if event.type() == QEvent.Type.WindowActivate:
            self.notifications.refresh()
        return super().event(event)

    def _set_stale_days(self, days: int) -> None:
        self.stale_days.setSuffix(preferences.days_suffix(days))
        self.notifications.set_stale_days(days)

    def done(self, result: int) -> None:
        self.notifications.close()
        super().done(result)

    # ---------------------------------------------------------------- NotificationsView

    def show_state(self, state: NotificationsState) -> None:
        if self.enabled.isChecked() != state.enabled:
            self.enabled.blockSignals(True)
            self.enabled.setChecked(state.enabled)
            self.enabled.blockSignals(False)
        self.no_tray.setVisible(not state.has_tray)
        self.stale_row.setEnabled(state.enabled)
        for widget in (self.fedora_heading, self.fedora_state_row):
            widget.setVisible(state.timer != "missing")
        self.fedora_state_icon.setPixmap(_icon(state.timer_icons).pixmap(SMALL))
        self.fedora_button.setVisible(state.timer == "disabled")
        self.fedora_button.setEnabled(state.can_enable_timer)
        self.fedora_state.setText(state.timer_text)
        for row, line in zip(self.rows, state.notifiers, strict=True):
            row.show_line(line)
