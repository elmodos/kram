"""Settings → Update Notifications for GTK (kram.app.notifier): a preferences dialog of rows."""
from pathlib import Path

from gi.repository import Adw, Gdk, Gtk

from ... import APP_ID
from ...app import preferences
from ...app.notifier import (
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
from ...i18n import _
from ...notifier import control
from ..icons import first_themed
from ..loop import post
from ..ui_port import GioBus, GtkUi

bus = GioBus()  # kram.app.ports.Bus; tests put a FakeBus here


def _image(names: tuple[str, ...], size: int = 16) -> Gtk.Image:
    return Gtk.Image(icon_name=first_themed(names) or "", pixel_size=size)


def _button(label: str, icons: tuple[str, ...]) -> Gtk.Button:
    content = Adw.ButtonContent(label=label, icon_name=first_themed(icons) or "")
    return Gtk.Button(child=content, valign=Gtk.Align.CENTER)


def _tray_image() -> Gtk.Image:
    """The tray icon itself: installed in hicolor, or next to the package in a source checkout."""
    name = f"{APP_ID}-update-medium"
    display = Gdk.Display.get_default()
    if display is not None and Gtk.IconTheme.get_for_display(display).has_icon(name):
        return Gtk.Image(icon_name=name, pixel_size=16)
    source = Path(__file__).resolve().parents[3] / "data" / "icons" / f"{name}.svg"
    return Gtk.Image(file=str(source), pixel_size=16) if source.exists() else Gtk.Image()


class _NotifierRow(Adw.ActionRow):
    """Another program's update notifier: what it does to ours, and turning it off or back on for this user."""

    def __init__(self, notifier: control.Notifier, notifications: Notifications, ui: GtkUi):
        super().__init__(title=notifier.name, subtitle_lines=0)
        self.notifier = notifier
        self.add_prefix(_image(notifier.icons + NOTIFIER_FALLBACK_ICONS, 32))
        self.toggle = Gtk.Button(valign=Gtk.Align.CENTER)
        self.toggle.connect("clicked", lambda _b: notifications.toggle(notifier))
        show = Gtk.Button(icon_name=first_themed(FILE_MANAGER_ICONS) or "folder-open-symbolic",
                          valign=Gtk.Align.CENTER, tooltip_text=_("Show in File Manager"))
        show.connect("clicked", lambda _b: ui.show_in_file_manager(notifier_file(notifier)))
        self.add_suffix(self.toggle)
        self.add_suffix(show)

    def show_line(self, line: NotifierLine) -> None:
        self.set_subtitle(line.text)
        self.toggle.set_child(Adw.ButtonContent(label=line.toggle_text, icon_name=first_themed(line.toggle_icons) or ""))
        self.toggle.set_tooltip_text(line.toggle_tip)


class NotifierDialog(Adw.PreferencesDialog):
    def __init__(self):
        super().__init__(title=_("Update Notifications"), content_width=620, search_enabled=False)
        self.ui = GtkUi(self)
        self.notifications = Notifications(self, self.ui, bus, post)
        page = Adw.PreferencesPage()
        self.add(page)

        tray = Adw.PreferencesGroup(description=_(
            "The icon is there only while updates are available. Kram downloads nothing in the background: Fedora's "
            "own service refreshes the package information, Kram only reads it, at login, hourly and after every "
            "installation."))
        page.add(tray)
        self.enabled = Adw.SwitchRow(title=_("Show an icon in the system tray when updates are available"),
                                     title_lines=0)
        self.enabled.add_prefix(_tray_image())
        self._enabled_handler = self.enabled.connect("notify::active",
                                                     lambda r, _p: self.notifications.set_enabled(r.get_active()))
        tray.add(self.enabled)
        self.no_tray = Adw.ActionRow(title=_(
            "This session has no system tray for such icons (GNOME without the AppIndicator extension, LXDE), so "
            "the icon cannot appear."), title_lines=0)
        self.no_tray.add_prefix(_image(OFF_ICONS))
        tray.add(self.no_tray)
        stale_pref = preferences.pref(preferences.STALE_DAYS)
        self.stale_days = Adw.SpinRow.new_with_range(*stale_pref.range, 1)
        self.stale_days.set_title(stale_pref.label)
        self.stale_days.set_title_lines(0)
        self.stale_days.set_value(preferences.value(stale_pref))
        self.stale_days.connect("notify::value", lambda r, _p: self._set_stale_days(int(r.get_value())))
        self._set_stale_days(int(self.stale_days.get_value()))
        tray.add(self.stale_days)

        self.fedora = Adw.PreferencesGroup(title=_("Fedora's update check"))
        page.add(self.fedora)
        self.fedora_state = Adw.ActionRow(subtitle_lines=0)
        self.fedora_state.add_prefix(_image(FEDORA_ICONS, 32))
        self.fedora_state_icon = Gtk.Image(pixel_size=16)
        self.fedora_state.add_suffix(self.fedora_state_icon)
        self.fedora_button = _button(_("Turn On Fedora's Update Check…"), TURN_ON_ICONS)
        self.fedora_button.set_tooltip_text(_("Asks for your password"))
        self.fedora_button.connect("clicked", lambda _b: self.notifications.enable_fedora_timer())
        self.fedora_state.add_suffix(self.fedora_button)
        self.fedora.add(self.fedora_state)

        self.rows = [_NotifierRow(n, self.notifications, self.ui) for n in self.notifications.notifiers]
        if self.rows:
            others = Adw.PreferencesGroup(title=_("Other update notifiers"))
            page.add(others)
            for row in self.rows:
                others.add(row)

        # everything here can change outside Kram while the dialog is open: the user deletes the autostart file in
        # the file manager it showed, turns a timer on in a terminal, a tray host or a notifier starts
        self._focus = Gtk.EventControllerFocus()
        self._focus.connect("enter", lambda _c: self.notifications.refresh())
        self.add_controller(self._focus)
        self.connect("closed", lambda _d: self.notifications.close())
        self.notifications.refresh()

    def _set_stale_days(self, days: int) -> None:
        self.stale_days.set_subtitle(preferences.days_suffix(days).strip())
        self.notifications.set_stale_days(days)

    # ---------------------------------------------------------------- NotificationsView

    def show_state(self, state: NotificationsState) -> None:
        if self.enabled.get_active() != state.enabled:
            self.enabled.handler_block(self._enabled_handler)
            self.enabled.set_active(state.enabled)
            self.enabled.handler_unblock(self._enabled_handler)
        self.no_tray.set_visible(not state.has_tray)
        self.stale_days.set_sensitive(state.enabled)
        self.fedora.set_visible(state.timer != "missing")
        self.fedora_state.set_subtitle(state.timer_text)
        self.fedora_state_icon.set_from_icon_name(first_themed(state.timer_icons) or "")
        self.fedora_state_icon.set_visible(state.timer != "disabled")
        self.fedora_button.set_visible(state.timer == "disabled")
        self.fedora_button.set_sensitive(state.can_enable_timer)
        for row, line in zip(self.rows, state.notifiers, strict=True):
            row.show_line(line)
