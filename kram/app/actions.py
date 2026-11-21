"""The main window's actions and menus as data: what each action is called, its icon, shortcuts and tooltip, which
menus hold it, and when it is enabled. Each front end builds its own actions and menus from this (Qt: QAction and
QMenu in kram.qt.actions; GTK: Gio.SimpleAction and Gio.Menu), and connects what they do.
"""
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from ..core.evr import evr_cmp
from ..core.filters import UPGRADES_FIXES, UPGRADES_SECURITY, UPGRADES_SECURITY_HIGH
from ..core.marks import Action, MarkSet, allowed_actions
from ..core.model import PkgRow
from ..i18n import _
from .icons import IconRef


@dataclass(frozen=True)
class ActionDef:
    id: str
    label: str                          # translated, with no mnemonic
    icon: str | IconRef | None = None   # a freedesktop icon name, or a painted icon (kram.app.icons.IconRef)
    shortcuts: tuple[str, ...] = ()     # "Ctrl+R", "F5", "Ins", "Del", "Alt+Left", "Ctrl+Shift+Z"
    tip: str = ""
    # "table": its shortcuts work only in the package list, so that Ctrl+C still copies text in the search field
    # and the detail tabs, and Del/Ins/Ctrl+Z keep their meaning in the search field
    scope: Literal["window", "table"] = "window"
    enabled: bool = True                # before `action_state` first says otherwise
    visible: bool = True


def _upgrades_of_kind() -> list[tuple[str, str, str]]:
    return [
        (UPGRADES_SECURITY, _("Mark Security Upgrades"),
         _("Mark the upgrades that fix a security issue, as dnf upgrade --security")),
        (UPGRADES_SECURITY_HIGH, _("Mark Critical and Important Security Upgrades"),
         _("Mark the upgrades that fix a security issue rated critical or important")),
        (UPGRADES_FIXES, _("Mark Security and Bug Fix Upgrades"),
         _("Mark the upgrades that fix a security issue or bugs, leaving out enhancements")),
    ]


def mark_upgrades_id(kind: str) -> str:
    return f"mark_upgrades.{kind}"


def mark_id(action: Action) -> str:
    return f"mark.{action.value}"


# the marks the Package menu offers, in its order
MARK_ACTIONS = (Action.INSTALL, Action.UPGRADE, Action.REINSTALL, Action.REMOVE, Action.MARK_USER, Action.MARK_DEP)


def action_defs() -> list[ActionDef]:
    """Every action of the main window. A function: the texts are translated when it is called."""
    defs = [
        ActionDef("reload", _("Reload"), "view-refresh", ("Ctrl+R", "F5"),  # F5: what browsers and file managers use
                  _("Refresh repository metadata and reload the catalog (needs a password)")),
        ActionDef("reload_cache", _("Reload from cache"), "view-refresh", ("Ctrl+Shift+R",),
                  _("Reload the catalog from the local cache, without network or password")),
        # its icon follows whether there is anything to upgrade (Qt: update-medium / update-none)
        ActionDef("mark_upgrades", _("Mark All Upgrades"), None, ("Ctrl+U",),
                  _("Mark every package that has a newer version for upgrade"), enabled=False),
        # the other ways to mark upgrades, by their advisories (the arrow next to the toolbar button, Edit menu);
        # upgrades from repositories without advisories (RPM Fusion, COPR, most third-party ones) are not among them
        *(ActionDef(mark_upgrades_id(kind), text, tip=tip) for kind, text, tip in _upgrades_of_kind()),
        ActionDef("mark_unneeded", _("Mark Unneeded Dependencies for Removal"), "edit-delete",
                  tip=_("Mark for removal the dependencies nothing needs any more, as dnf autoremove does"),
                  enabled=False),
        ActionDef("apply", _("Apply"), "dialog-ok-apply", ("Ctrl+P",), _("Review and apply the marked changes"),
                  enabled=False),
        ActionDef("unmark_all", _("Unmark All"), "edit-clear", ("Ctrl+Shift+Z",), _("Discard all marked changes"),
                  enabled=False),
        ActionDef("properties", _("Properties"), "document-properties"),
        ActionDef("repos", _("Repositories"), "configure", tip=_("Enable or disable software repositories"),
                  enabled=False),
        ActionDef("filters", _("Custom Filters…"), "view-filter",
                  tip=_("Create and edit your own filters for the sidebar"), enabled=False),
        ActionDef("new_filter", _("New Filter from Current View…"), "list-add",
                  tip=_("A custom filter with the current sidebar selection and search"), enabled=False),
        ActionDef("copr", _("COPR"), "folder-cloud", tip=_("Manage COPR projects: community repositories"),
                  enabled=False),
        ActionDef("cache", _("Cleanup…"), "edit-clear-all",
                  tip=_("Clean the package caches and remove leftover configuration files"), enabled=False),
        ActionDef("notifications", _("Update Notifications…"), "preferences-desktop-notification",
                  tip=_("An icon in the system tray when updates are available")),
        ActionDef("find", _("Find"), "edit-find", ("Ctrl+F",)),
        ActionDef("back", _("Back"), "go-previous", ("Alt+Left",),
                  _("Go back to the previous package (after following a dependency)")),
        ActionDef("save_marks", _("Save Markings As…"), "document-save-as", ("Ctrl+S",),
                  _("Save the marked changes to a text file"), enabled=False),
        ActionDef("read_marks", _("Read Markings…"), "document-open", ("Ctrl+O",),
                  _("Mark the changes listed in a saved markings file"), enabled=False),
        ActionDef("export_csv", _("Export List as CSV…"), "document-export",
                  tip=_("Save the packages listed now, in their order, to a CSV file"), enabled=False),
        ActionDef("history", _("Transaction History…"), "view-history", ("Ctrl+H",),
                  _("What dnf installed, upgraded and removed, and when; undo a transaction"), enabled=False),
        ActionDef("open_file", _("Open Package File…"), "document-open",
                  tip=_("Install a downloaded .rpm file (you can also drop it on the window)"), enabled=False),
        ActionDef("quit", _("Quit"), "application-exit", ("Ctrl+Q",)),
        ActionDef("about", _("About Kram"), "help-about"),
        ActionDef("copy_name", _("Copy Name"), "edit-copy", ("Ctrl+C",), scope="table"),
        ActionDef("copy_nevra", _("Copy name-version-release.arch"), "edit-copy", ("Ctrl+Shift+C",), scope="table"),
    ]
    marks = {
        Action.INSTALL: (_("Mark for Installation"), "list-add", ("Ins",)),
        Action.UPGRADE: (_("Mark for Upgrade"), "go-up", ()),
        Action.REINSTALL: (_("Mark for Reinstallation"), "view-refresh", ()),
        Action.REMOVE: (_("Mark for Removal"), "list-remove", ("Del",)),
        Action.MARK_USER: (_("Mark as Installed by User"), "user-identity", ()),
        Action.MARK_DEP: (_("Mark as Dependency"), "link", ()),
    }
    defs += [ActionDef(mark_id(a), text, icon, keys, text, scope="table")
             for a, (text, icon, keys) in ((a, marks[a]) for a in MARK_ACTIONS)]
    defs += [
        # dnf's version lock: changed at once through the helper, not marked for Apply (it installs nothing)
        ActionDef("lock", _("Lock Version"), "object-locked", scope="table",
                  tip=_("Keep the installed version: upgrades leave it out until it is unlocked (needs a password)")),
        ActionDef("unlock", _("Unlock Version"), "object-unlocked", scope="table",
                  tip=_("Remove the version lock: the package gets upgrades again (needs a password)")),
        ActionDef("show_in_history", _("Show in History"), "view-history", scope="table",
                  tip=_("The transactions that changed this package"), enabled=False),
        # only there for an upgrade that cannot be installed now, with the cross the list shows for it
        ActionDef("why_blocked", _("Why It Cannot Be Upgraded"), ("blocked",), scope="table",
                  tip=_("Show on the Dependencies tab why the new version cannot be installed now"), visible=False),
        ActionDef("unmark", _("Unmark"), "edit-undo", ("Ctrl+Z",), _("Unmark the selected packages"), scope="table"),
    ]
    return defs


# the table-scoped actions whose shortcuts the package list takes, in the order Qt adds them to it
TABLE_SHORTCUT_ACTIONS = ("copy_name", "copy_nevra", *map(mark_id, MARK_ACTIONS), "unmark")


# ---------------------------------------------------------------- menus

@dataclass(frozen=True)
class MenuItem:
    """One entry: an action (by id), a submenu, a separator, or the preferences of a section (kram.app.preferences)
    that the front end's toolkit has: a checkable entry per bool, a submenu of choices per choice."""
    action: str | None = None
    submenu: "Menu | None" = None
    separator: bool = False
    prefs: str | None = None


@dataclass(frozen=True)
class Menu:
    """`title`: translated; the menu bar's titles carry Qt's "&" before the mnemonic letter (GTK: "_"). `id` names
    a menu a front end fills or treats specially: "downgrade" is filled when it opens (`downgrade_menu`)."""
    title: str
    items: tuple[MenuItem, ...] = ()
    id: str = ""
    icon: str | None = None


SEPARATOR = MenuItem(separator=True)


def _items(*entries: "str | Menu | MenuItem") -> tuple[MenuItem, ...]:
    return tuple(e if isinstance(e, MenuItem) else MenuItem(submenu=e) if isinstance(e, Menu) else MenuItem(e)
                 for e in entries)


def mark_upgrades_menu() -> Menu:
    """The arrow next to the toolbar's Mark All Upgrades, and Edit → Mark Upgrades."""
    return Menu(_("Mark Upgrades"), _items("mark_upgrades", SEPARATOR,
                                           *(mark_upgrades_id(kind) for kind, _t, _tip in _upgrades_of_kind())),
                id="mark_upgrades")


def downgrade_submenu() -> Menu:
    return Menu(_("Downgrade to Version"), id="downgrade", icon="go-down")


def package_menu_items() -> tuple[MenuItem, ...]:
    """The Package menu, the package list's context menu and the status icon's menu."""
    return _items(*map(mark_id, MARK_ACTIONS), downgrade_submenu(), SEPARATOR, "lock", "unlock", SEPARATOR,
                  "unmark", SEPARATOR, "show_in_history", "why_blocked")


def package_menu() -> Menu:
    return Menu(_("&Package"), package_menu_items())


def table_menu() -> Menu:
    """The package list's context menu."""
    return Menu("", (*package_menu_items(), SEPARATOR, *_items("copy_name", "copy_nevra")))


def menu_bar() -> tuple[Menu, ...]:
    return (
        Menu(_("&File"), _items("open_file", SEPARATOR, "reload", "reload_cache", SEPARATOR, "read_marks",
                                "save_marks", "export_csv", SEPARATOR, "history", SEPARATOR, "quit")),
        Menu(_("&Edit"), _items(mark_upgrades_menu(), "mark_unneeded", SEPARATOR, "unmark_all", "apply", SEPARATOR,
                                "copy_name", "copy_nevra", SEPARATOR, "find")),
        Menu(_("&Package"), (*package_menu_items(), *_items(SEPARATOR, "properties", "back"))),
        Menu(_("&Settings"), _items("repos", "copr", "cache", "notifications", SEPARATOR, "filters", "new_filter",
                                    SEPARATOR, MenuItem(prefs="settings"))),
        Menu(_("&Help"), _items("about")),
    )


def walk(items: Iterable[MenuItem]) -> Iterable[MenuItem]:
    """Every item of a menu structure, submenus' items included."""
    for item in items:
        yield item
        if item.submenu is not None:
            yield from walk(item.submenu.items)


# ---------------------------------------------------------------- dynamic menus

@dataclass(frozen=True)
class DynamicItem:
    """An entry of a menu built when it opens: its own label and icon, and what it runs."""
    label: str
    run: Callable[[], None] | None = None
    icon: str | IconRef | None = None
    enabled: bool = True
    tip: str = ""


def downgrade_items(row: PkgRow | None, details, choose: Callable[[str], None]) -> list[DynamicItem]:
    """Package → Downgrade to Version for the selected `row`: its older versions in the repositories, from its
    `details` (None while they load). `choose(evr)` marks the downgrade."""
    if row is None or details is None:
        return [DynamicItem(_("(loading…)"), enabled=False)]
    installed = {v.evr for v in details.versions if v.installed}
    older = [v for v in details.versions if not v.installed and not v.locked_out and v.evr not in installed
             and evr_cmp(v.evr, row.installed_evr) < 0]
    if not older:
        return [DynamicItem(_("No older versions in the repositories"), enabled=False)]
    return [DynamicItem(f"{v.evr}  ({v.repo_id})", lambda evr=v.evr: choose(evr)) for v in older]


# ---------------------------------------------------------------- when they are enabled

@dataclass
class ActionState:
    enabled: dict[str, bool] = field(default_factory=dict)
    visible: dict[str, bool] = field(default_factory=dict)


def action_state(rows: list[PkgRow], *, catalog: bool, n_upgradable: int, marks: MarkSet,
                 blocked: Mapping[tuple[str, str], str], busy: bool, upgrades_of_kind: Mapping[str, bool],
                 unneeded: bool, can_open_file: bool) -> ActionState:
    """Which actions are enabled (and the one that comes and goes, shown) for the selected `rows`. `catalog`: one
    is loaded; `busy`: a helper request runs or the marks are being resolved for review, and nothing else may start
    meanwhile. "downgrade" is the Downgrade submenu, "mark_upgrades_menu" the Mark Upgrades one, "upgrade" the
    button of a new Fedora release."""
    allowed: set[Action] = set()
    for r in rows:
        allowed.update(allowed_actions(r))
    free = not busy
    n = len(marks)
    single = len(rows) == 1
    enabled = {
        # no marking while the marks are resolved: a removal would be checked against the list being reviewed
        **{mark_id(a): a in allowed and free for a in MARK_ACTIONS},
        "downgrade": single and rows[0].installed and free,
        "unmark": any(r.key in marks for r in rows) and free,
        "lock": free and any(r.installed and not r.locked for r in rows),
        "unlock": free and any(r.locked for r in rows),
        "apply": n > 0 and free,
        "unmark_all": n > 0,
        "save_marks": n > 0,
        "read_marks": catalog,
        "export_csv": catalog,
        "history": catalog,
        "show_in_history": catalog and single,
        **dict.fromkeys(("repos", "copr", "cache", "filters", "new_filter", "upgrade"), catalog),
        "open_file": can_open_file,
        "mark_upgrades": catalog and n_upgradable > 0,
        "mark_upgrades_menu": catalog and n_upgradable > 0,
        **{mark_upgrades_id(kind): bool(upgrades_of_kind.get(kind)) for kind, _t, _tip in _upgrades_of_kind()},
        "mark_unneeded": unneeded,
    }
    visible = {"why_blocked": single and rows[0].key in blocked}
    return ActionState(enabled, visible)
