"""Comps group icons from the system icon theme.

Comps metadata carries no icons, so a hand-made table maps the group ids that have an obvious freedesktop icon;
every other group, including ones Fedora adds later, gets the generic one. Each id lists names in order of
preference: the first the current theme has wins (Papirus has more application icons than Breeze).
"""
from functools import cache

from PySide6.QtGui import QIcon

_DESKTOP = ("user-desktop",)
_DEVELOPMENT = ("applications-development",)
_EDUCATION = ("applications-education",)
_MULTIMEDIA = ("applications-multimedia",)
_OFFICE = ("applications-office",)
_SCIENCE = ("applications-science",)
_SYSTEM = ("applications-system",)
_WINDOWS = ("preferences-system-windows",)

_GROUPS: dict[str, tuple[str, ...]] = {
    # desktops and window managers
    "budgie-desktop": _DESKTOP,
    "cinnamon-desktop": _DESKTOP,
    "cosmic-desktop": _DESKTOP,
    "gnome-desktop": _DESKTOP,
    "kde-desktop": ("start-here-kde-plasma", "start-here-kde", *_DESKTOP),
    "lxde-desktop": _DESKTOP,
    "lxqt-desktop": _DESKTOP,
    "mate-desktop": _DESKTOP,
    "sugar-desktop": _DESKTOP,
    "xfce-desktop": _DESKTOP,
    "kde-apps": ("kde", "start-here-kde"),
    "compiz": _WINDOWS,
    "swaywm-extended": _WINDOWS,
    "window-managers": _WINDOWS,
    # development
    "c-development": _DEVELOPMENT,
    "d-development": _DEVELOPMENT,
    "development-tools": _DEVELOPMENT,
    "java-development": _DEVELOPMENT,
    "kde-software-development": _DEVELOPMENT,
    "kf6-software-development": _DEVELOPMENT,
    "rpm-development-tools": _DEVELOPMENT,
    "x-software-development": _DEVELOPMENT,
    # applications
    "audio": ("audio-x-generic", *_MULTIMEDIA),
    "authoring-and-publishing": _OFFICE,
    "design-suite": ("applications-graphics",),
    "editors": ("accessories-text-editor",),
    "education": _EDUCATION,
    "kde-education": _EDUCATION,
    "python-classroom": _EDUCATION,
    "electronic-lab": ("applications-electronics", "applications-engineering"),
    "engineering-and-scientific": _SCIENCE,
    "python-science": _SCIENCE,
    "games": ("applications-games",),
    "graphics": ("applications-graphics",),
    "graphical-internet": ("applications-internet",),
    "kde-media": _MULTIMEDIA,
    "sound-and-video": _MULTIMEDIA,
    "vlc": ("vlc", *_MULTIMEDIA),
    "kde-office": _OFFICE,
    "libreoffice": ("libreoffice-startcenter", "libreoffice-main", *_OFFICE),
    "office": _OFFICE,
    "kde-pim": ("kontact", *_OFFICE),
    "text-internet": ("utilities-terminal",),
    # system
    "admin-tools": _SYSTEM,
    "system-tools": _SYSTEM,
    "desktop-accessibility": ("preferences-desktop-accessibility",),
    "domain-client": ("network-workgroup",),
    "fonts": ("preferences-desktop-font",),
    "hardware-support": ("computer",),
    "input-methods": ("preferences-desktop-keyboard",),
    "network-server": ("network-server",),
    "printing": ("printer",),
    "security-lab": ("security-high",),
    "virtualization": ("virt-manager", "computer"),
}
_GENERIC = ("applications-other", "package-x-generic")
_ALL = ("applications-all", "view-list-icons", *_GENERIC)


def _themed(names: tuple[str, ...]) -> QIcon:
    for name in names:
        if QIcon.hasThemeIcon(name):
            return QIcon.fromTheme(name)
    return QIcon()


@cache
def group_icon(group_id: str) -> QIcon:
    """The themed icon for a comps group id; "" is the "All groups" entry."""
    if not group_id:
        return _themed(_ALL)
    icon = _themed(_GROUPS.get(group_id, ()))
    return _themed(_GENERIC) if icon.isNull() else icon
