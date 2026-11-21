"""What the icons mean, without drawing them: colours, labels, theme icon names and icon references.

Kram paints its status, mark and origin icons itself so that they read the same in any theme. The shapes are drawn
by each front end (`kram.qt.icons` for Qt); what they show, and in which colour, is decided here. An `IconRef` names
an icon without a toolkit: the package list and the sidebar return them, and each front end draws or looks up the
icon a reference names.

    ("status", Status)      the status box of a package
    ("mark", Action)        the box of a marked change
    ("locked", installed)   the box with a padlock: dnf's version lock holds the package
    ("origin", Origin)      the round origin badge
    ("advisory", level)     the dot of an update advisory; level None is an empty icon of the same size
    ("held", level)         a ring: an update the version lock holds back
    ("blocked",)            the red cross: the upgrade cannot be installed now
    ("all",)                the box with a grey dot: Status → All
    ("user",)               the box with a hammer: Status → Installed by the user
    ("marked",)             the purple box with a check: Status → Marked
    ("group", group_id)     a comps group's or environment's icon from the icon theme (`group_icon_names`)
    ("theme", names)        the first of these theme icon names the theme has
"""
from ..core.marks import Action
from ..core.model import ENVIRONMENT_PREFIX, Origin, Status
from ..i18n import _

IconRef = tuple

ORIGIN_LABEL = {
    Origin.FEDORA: "Fedora", Origin.COPR: "COPR", Origin.THIRD_PARTY: _("Third-party origin"),
    Origin.LOCAL: _("Local origin"), Origin.UNKNOWN: _("Unknown origin"),
}
# the badge's colour and letter
ORIGIN_STYLE = {
    Origin.FEDORA: ("#294172", "F"), Origin.COPR: ("#d4762c", "C"), Origin.THIRD_PARTY: ("#6b6b6b", "3"),
    Origin.LOCAL: ("#7a4fa0", "L"), Origin.UNKNOWN: ("#b03030", "?"),
}

# the background of a marked row (RGBA): translucent, so that it works on light and dark palettes
MARK_BACKGROUND = {
    Action.INSTALL: (90, 170, 60, 70), Action.REMOVE: (210, 60, 60, 80), Action.UPGRADE: (60, 130, 220, 70),
    Action.REINSTALL: (60, 130, 220, 50), Action.DOWNGRADE: (200, 150, 40, 70),
    Action.MARK_USER: (90, 170, 60, 35), Action.MARK_DEP: (90, 170, 60, 35),
}

# update advisories, by kram.core.model.ADVISORY_LEVELS: reds and oranges for security fixes by severity, blue for
# bug fixes, grey for the rest
ADVISORY_COLOR = {
    "critical": "#b3121b", "important": "#e0402a", "moderate": "#f08a1c", "low": "#e6c21e", "security": "#f08a1c",
    "bugfix": "#3a8ee6", "enhancement": "#909090", "other": "#909090",
}

# the icons of the Status view's entries: the same boxes as the package list's status column, so it reads as its
# legend
STATUS_FILTER_ICONS: dict[str, IconRef] = {
    "status:all": ("all",),
    "status:installed": ("status", Status.INSTALLED),
    "status:not-installed": ("status", Status.NOT_INSTALLED),
    "status:upgradable": ("status", Status.UPGRADABLE),
    "status:security": ("advisory", "important"),
    "status:bugfix": ("advisory", "bugfix"),
    "status:blocked": ("blocked",),
    "status:user": ("user",),
    "status:unneeded": ("status", Status.UNNEEDED),
    "status:orphan": ("status", Status.ORPHAN),
    "status:newer": ("status", Status.NEWER),
    "status:locked": ("locked", True),
    "status:marked": ("marked",),
}


def status_icon_ref(status: Status, locked: bool, installed: bool, mark: Action | None) -> IconRef:
    """The status column's icon: a mark shows over the status, a version lock in place of the status glyph."""
    if mark is not None:
        return ("mark", mark)
    return ("locked", installed) if locked else ("status", status)


# ---------------------------------------------------------------- comps group icons
# Comps metadata carries no icons, so a hand-made table maps the group ids that have an obvious freedesktop icon;
# every other group, including ones Fedora adds later, gets the generic one. Each id lists names in order of
# preference: the first the current theme has wins (Papirus has more application icons than Breeze).

_DESKTOP = ("user-desktop",)
_DEVELOPMENT = ("applications-development",)
_EDUCATION = ("applications-education",)
_MULTIMEDIA = ("applications-multimedia",)
_OFFICE = ("applications-office",)
_SCIENCE = ("applications-science",)
_SYSTEM = ("applications-system",)
_WINDOWS = ("preferences-system-windows",)

GROUPS: dict[str, tuple[str, ...]] = {
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
# environments ("<desktop>-desktop-environment" takes the icon of its "<desktop>-desktop" group)
ENVIRONMENTS: dict[str, tuple[str, ...]] = {
    "workstation-product-environment": ("fedora-logo-icon", "start-here-fedora", *_DESKTOP),
    "developer-workstation-environment": _DEVELOPMENT,
    "server-product-environment": ("network-server",),
    "cloud-server-environment": ("network-server",),
    "custom-environment": _SYSTEM,
    "i3-desktop-environment": _WINDOWS,
    "sway-desktop-environment": _WINDOWS,
    "miraclewm-desktop-environment": _WINDOWS,
}
GENERIC_GROUP = ("applications-other", "package-x-generic")
ALL_GROUPS = ("applications-all", "view-list-icons", *GENERIC_GROUP)


def group_icon_names(group_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The theme icon names for a comps group id or an environment's GroupInfo.key ("" is the "All groups" entry),
    in order of preference, and the names to fall back to when the theme has none of them."""
    if not group_id:
        return ALL_GROUPS, ()
    if group_id.startswith(ENVIRONMENT_PREFIX):
        env = group_id.removeprefix(ENVIRONMENT_PREFIX)
        return ENVIRONMENTS.get(env) or (*GROUPS.get(env.removesuffix("-environment"), ()), *_DESKTOP), ()
    return GROUPS.get(group_id, ()), GENERIC_GROUP


# the marks of the package file dialog's header lines and of the Fedora N dialog's findings: each kind is also the
# colour of its text (INFO: the palette's own). Theme icons, not symbols: a font without "ℹ" shows a plain "i"
OK, WARN, ERROR, INFO = "#2f7a1f", "#a86f1f", "#c03030", None
STATE_ICONS: dict[str | None, IconRef] = {
    OK: ("theme", ("data-success", "emblem-ok-symbolic")), WARN: ("theme", ("data-warning", "dialog-warning")),
    ERROR: ("theme", ("data-error", "dialog-error")), INFO: ("theme", ("data-information", "dialog-information"))}
