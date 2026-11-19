"""The desktop the user is running now, as packages: removing one of them can end the session. No Qt."""
import os
from functools import cache

SESSION_DIRS = ("/usr/share/wayland-sessions", "/usr/share/xsessions")
# XDG_CURRENT_DESKTOP -> the package a session of it cannot run without, when the session file is not found
DESKTOP_PACKAGES = {
    "kde": ("plasma-workspace",),
    "gnome": ("gnome-shell",),
    "xfce": ("xfce4-session",),
    "x-cinnamon": ("cinnamon",),
    "cinnamon": ("cinnamon",),
    "mate": ("mate-session-manager",),
    "lxqt": ("lxqt-session",),
    "lxde": ("lxsession",),
    "budgie": ("budgie-desktop",),
    "sway": ("sway",),
    "i3": ("i3",),
    "cosmic": ("cosmic-session",),
    "hyprland": ("hyprland",),
    "phosh": ("phosh",),
    "enlightenment": ("enlightenment",),
}


def session_files(env: dict[str, str]) -> list[str]:
    """The .desktop files the display manager may have started this session from."""
    found = []
    for var in ("DESKTOP_SESSION", "XDG_SESSION_DESKTOP"):
        value = env.get(var, "")
        if not value:
            continue
        if value.startswith("/"):  # SDDM: the path without ".desktop"
            found += [value if value.endswith(".desktop") else value + ".desktop"]
        else:
            found += [os.path.join(d, value + ".desktop") for d in SESSION_DIRS]
            found += [os.path.join(d, value.lower() + ".desktop") for d in SESSION_DIRS]
    return [f for f in dict.fromkeys(found) if os.path.isfile(f)]


def file_owners(paths: list[str]) -> set[str]:
    """The names of the installed packages that own these files."""
    import rpm

    ts = rpm.TransactionSet()
    names = set()
    for path in paths:
        for header in ts.dbMatch("basenames", path):
            names.add(header[rpm.RPMTAG_NAME])
    return names


def session_packages(env: dict[str, str] | None = None) -> tuple[str, set[str]]:
    """(the desktop's name, the packages it runs on): the owner of the session file, and the desktop's main
    package. ("", set()) outside a desktop session."""
    env = dict(os.environ) if env is None else env
    desktop = env.get("XDG_CURRENT_DESKTOP", "")
    try:
        names = file_owners(session_files(env))
    except Exception:  # noqa: BLE001 - no rpm database to read: the table below still applies
        names = set()
    for part in desktop.split(":"):
        names.update(DESKTOP_PACKAGES.get(part.lower(), ()))
    return desktop.split(":")[0] if names else "", names


@cache
def current_session() -> tuple[str, frozenset[str]]:
    """session_packages() of this process, read once."""
    desktop, names = session_packages()
    return desktop, frozenset(names)
