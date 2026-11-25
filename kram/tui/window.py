"""The main window of the terminal front end: a view of kram.app.browser.Browser (docs/TUI_SPEC.md §7), as
kram.gtk.window.MainWindow is. It wires the sidebar (kram.tui.sidebar), the package list (kram.tui.package_list),
the details (kram.tui.details) and the top line (§5.4) to the Browser; the app (kram.tui.app) lays out the panels
and decides who gets a key.

The helper is the terminal's own client (kram.tui.root, §11): it gets root before the first request, and the
progress of every request is the dialog of kram.tui.dialogs.progress (§10.2).

The changes are reviewed in the Apply changes dialog (kram.tui.dialogs.apply, §10.1) and run in the progress dialog;
Browser does the rest of the flow (the conflicts offer, the form when nothing can be done, the reload, closing Kram
when the transaction removed kram-tui), as it does for the GUIs.

The COPR dialog (kram.tui.dialogs.copr, §10.6) stays open while its changes run, as the Repositories dialog does;
the Transaction History (kram.tui.dialogs.history, §10.7) reads the history again after every new catalog while it
is open, and a package chosen in it is selected in the list once it has closed.

A package file is installed in the Install package file dialog (kram.tui.dialogs.install, §10.8), opened from
File → Open Package File… (a path line, in the folder of the last file, which the GUIs remember too) or from the path
of an `.rpm` pasted into the window: a terminal turns a file dropped on it into its path, pasted, so this is how a
drop arrives (INSTALL_FILE_DROP). Settings → Cleanup… is the dialog of kram.tui.dialogs.cache (§10.9); what it
cleans or deletes runs over it.

The Repositories dialog (kram.tui.dialogs.repos, §10.4) and the Mirrors dialog over it (kram.tui.dialogs.mirrors,
§10.5) stay open while what is done from them runs: while each is open, every new catalog gives it the new state,
as the GUIs' windows do.

Settings → Custom Filters…, New Filter from Current View and `e` on a custom filter open the Custom Filters dialog
(kram.tui.dialogs.filters, §10.10); Update Notifications… is kram.tui.dialogs.notifier (§10.11) and Columns… is
kram.tui.dialogs.columns (§10.18), saved as the list follows it. As in the GUIs, a Reload asks Bodhi whether a new
Fedora release is out (kram.app.release_watch): the top line says so, and `r` opens the Fedora N dialog
(kram.tui.dialogs.upgrade, §10.12), whose check is kept for the session.

Marking (§7.5) is the GUIs': `space` and a click on the status cell are the status click (the likely mark, or the
row's menu, as the setting says), a double click is the likely mark, and the keys of kram.tui.keymap run the Package
menu's actions.

The actions of kram.app.actions run here, by id (`run_action`), whether from the menu, a context menu or a key: what
each runs is what the GUIs connect to it (kram.gtk.window._connect_actions). Whether one is enabled comes from
`Browser.update_actions` (`apply_actions`), and the menu says why one is not (`disabled_reason`).
"""
import json
import os
import shlex
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlparse

from rich.text import Text

from .. import instance
from ..app import preferences
from ..app.actions import (
    MARK_ACTIONS,
    ActionDef,
    ActionState,
    DynamicItem,
    action_defs,
    mark_id,
    mark_upgrades_id,
    mark_upgrades_menu,
    package_menu_items,
)
from ..app.browser import STATUS_MESSAGE_MS, UPGRADE_KINDS, Browser, ReposChoice
from ..app.custom_filters import CustomFilters
from ..app.details import DETAILS_TAB_KEY
from ..app.doc import Doc, para
from ..app.marking import group_menu
from ..app.mirrors import MirrorChoice
from ..app.package_list import Sort
from ..app.progress import BUSY
from ..app.release_watch import ReleaseWatcher
from ..app.status import error_text, metadata_age, missing_repos
from ..app.upgrade import UpgradeCheck
from ..core.marks import Action
from ..core.model import CatalogSnapshot, GroupInfo, PkgRow, TransactionPreview
from ..core.settings import store as settings
from ..i18n import _, ngettext
from ..notifier import stale_days
from . import loop
from .details import Details
from .dialogs.about import AboutDialog
from .dialogs.apply import ApplyDialog
from .dialogs.cache import CacheDialog
from .dialogs.columns import ColumnsDialog
from .dialogs.copr import CoprDialog
from .dialogs.filters import FiltersDialog
from .dialogs.history import HistoryDialog
from .dialogs.install import InstallDialog
from .dialogs.mirrors import MirrorsDialog
from .dialogs.notifier import NotifierDialog
from .dialogs.progress import ProgressDialog
from .dialogs.repos import ReposDialog
from .dialogs.upgrade import UpgradeDialog, UpgradeState
from .menu import menu_title, open_table_menu
from .package_list import Columns, PackageTable, column_label
from .palette import role
from .root import RootAccess, TuiHelperClient, is_root
from .search import open_search
from .sidebar import Sidebar
from .widgets import ChoiceList

FRONT_PACKAGE = "kram-tui"
INSTALL_DIR_KEY = "install/dir"  # the folder of the last package file opened, shared with the GUIs
# Browser says this while the catalog load waits for the system repo lock (Browser._waiting_for_lock)
LOCK_STATUS = "Waiting for another package manager to finish…"


def pasted_rpm(text: str) -> str | None:
    """The package file a paste names: one path of an existing `.rpm`, as terminals paste a dropped file: plain,
    quoted or with its spaces escaped (shell words), or as a `file://` URL. None for anything else."""
    text = text.strip()
    if not text or "\n" in text:
        return None
    try:
        words = shlex.split(text)
    except ValueError:  # an unmatched quote: not a shell word, maybe a path with an apostrophe
        words = [text]
    if len(words) != 1:
        words = [text]  # a path with spaces nobody quoted
    path = words[0]
    if path.startswith("file:"):
        url = urlparse(path)
        if url.netloc not in ("", "localhost"):
            return None
        path = unquote(url.path)
    path = os.path.expanduser(path)
    if not path.endswith(".rpm") or not Path(path).is_file():
        return None
    return os.path.abspath(path)


def downloads_dir() -> str:
    """Where Open Package File starts the first time, as the GUIs do: the user's downloads, else home."""
    home = Path.home()
    try:
        for line in (home / ".config/user-dirs.dirs").read_text().splitlines():
            if line.startswith("XDG_DOWNLOAD_DIR="):
                folder = Path(line.partition("=")[2].strip().strip('"').replace("$HOME", str(home)))
                if folder.is_dir():
                    return str(folder)
    except OSError:
        pass
    return str(home / "Downloads") if (home / "Downloads").is_dir() else str(home)


class MainWindow:
    """`app`: the KramApp, whose screen shows `list` in its Packages panel and whose top line this fills."""

    def __init__(self, app):
        self.app = app
        self.ui = app.ui
        self.details = Details(self, app.glyphs, id="details", classes="panel")
        self.scheduler = loop.TuiScheduler()
        self.root = RootAccess(app, self.ui)
        self.browser = b = Browser(self, self.ui, self.scheduler, self.details, loop.post,
                                   helper=TuiHelperClient(loop.post, self.root), front_package=FRONT_PACKAGE)
        # the user's filters, edited in the Custom Filters dialog (§10.10)
        b.custom_filters = CustomFilters(b.sidebar, b.catalog, b.dnf, lambda: b.snapshot, self.ui, self._edit_filters)
        self.sidebar = Sidebar(self, app.glyphs, id="sidebar", classes="panel")
        self.list = PackageTable(b.packages, self, app.glyphs, app.utf8, id="list")
        self.list.on_current = lambda _pos: b.current_changed(self.list.current_row())
        self.list.on_selection = b.update_actions
        self.list.show_sort(b.packages.sort_column)  # the sort the list starts with
        self.waiting_for_lock = False
        self.defs: dict[str, ActionDef] = {d.id: d for d in action_defs()}
        self.actions: ActionState | None = None  # from Browser.update_actions; None until it first says
        self.reload_enabled = self.apply_enabled = False
        # Fedora N (§5.4, §10.12): on Reload Bodhi is asked whether a new release is out, as in the GUIs; the top
        # line says so while the setting watches, and the check of the dialog is kept for the session
        self.releases = ReleaseWatcher(loop.post)
        self.releases.changed.connect(self.show_release)
        b.refreshed.connect(self.releases.check)
        preferences.changed.connect(self._pref_changed)
        self._watching_prefs = True
        self.upgrade: tuple[UpgradeState, UpgradeCheck] | None = None
        self.catalog_shown: CatalogSnapshot | None = None  # the right of the top line is about it

    def start(self) -> None:
        """Once the app runs (its loop takes what the worker posts): the settings, then the catalog."""
        b = self.browser
        b.restore_settings()
        b.custom_filters.restore()
        try:
            columns = json.loads(preferences.value(preferences.TUI_COLUMNS))
        except (TypeError, ValueError):
            columns = {}
        self.list.set_columns(Columns.from_dict(columns))
        self.top.set_root(is_root())
        self.details.select_name(settings.get(DETAILS_TAB_KEY, "description"))
        if self.app.upgradable:
            b.show_view(instance.UPGRADABLE)
        b.reload()

    def shutdown(self) -> None:
        self.browser.shutdown()

    def detach(self) -> None:
        """The app has ended: the settings' signal outlives it, and must not reach this window any more."""
        if self._watching_prefs:
            self._watching_prefs = False
            preferences.changed.disconnect(self._pref_changed)

    def _pref_changed(self, key: str) -> None:
        if key == preferences.WATCH_RELEASES:  # SETTINGS_WATCH_RELEASES: the notice follows it at once
            self.show_release()

    @property
    def top(self):
        return self.app.top_line

    # ---------------------------------------------------------------- BrowserView: the package list

    def current_key(self) -> tuple[str, str] | None:
        row = self.list.current_row()
        return row.key if row is not None else None

    def select_key(self, key: tuple[str, str], scroll: bool = True) -> bool:
        pos = self.browser.packages.position_of(key)
        if pos is None:
            return False
        self.list.select(pos, scroll=True)  # never left out of sight, which is all `scroll` asks in Qt
        return True

    def select_first(self, to_top: bool) -> None:
        if len(self.browser.packages):
            self.list.select(0)
            if to_top:
                self.list.scroll_to_top()

    def selected_rows(self) -> list[PkgRow]:
        packages = self.browser.packages
        return [packages.row(p) for p in self.list.selected_positions()]

    def show_sort(self, sort: Sort | None) -> None:
        self.list.show_sort(sort)

    def set_empty(self, doc: Doc) -> None:
        self.waiting_for_lock = False
        self.list.set_empty(doc)

    def focus_list(self) -> None:
        self.list.focus()

    # ---------------------------------------------------------------- BrowserView: the top line and the actions

    def set_status(self, text: str) -> None:
        self.top.set_status(text)
        if text == _(LOCK_STATUS) and self.browser.snapshot is None:
            # §7.1: the load waits for another package manager; Esc quits meanwhile
            self.list.set_empty(Doc([para(_("Another package manager is running: waiting"))]),
                                [("esc", _("quit"))])
            self.waiting_for_lock = True

    def status_text(self) -> str:
        return self.top.status.plain

    def show_catalog(self, snap: CatalogSnapshot) -> None:
        self.waiting_for_lock = False
        self.catalog_shown = snap
        self._show_right()

    def show_release(self) -> None:
        """ReleaseWatcher.changed, the setting: the notice of a new Fedora release (RELEASE_BUTTON). Bodhi's answer
        may come after Kram has ended: there is no top line then."""
        if self.app.screen_stack:
            self._show_right()

    def _show_right(self) -> None:
        """The right of the top line: what is wrong with the catalog, that a new Fedora release is out, then the
        catalog's age; dropped from the right when narrow, so the age goes first."""
        warn = self.app.glyphs.warning + " "
        parts = []
        if (snap := self.catalog_shown) is not None:
            age = snap.metadata_age
            if age is not None and (days := age // 86400) >= stale_days():
                parts.append(Text(warn + ngettext("The package information is {days} day old",
                                                  "The package information is {days} days old",
                                                  days).format(days=days), role("danger", bar=True)))
            if (missing := missing_repos(snap)) is not None:
                parts.append(Text(warn + missing[0], role("danger", bar=True)))
        if (target := self.releases.target()) is not None:
            # TRANSLATORS: on the top line of the terminal front end; the key that opens its dialog follows
            notice = Text(_("Fedora {version} is out").format(version=target) + ": ", role("info", bar=True))
            notice.append("r", role("key", bar=True))
            parts.append(notice)
        if snap is not None:
            parts.append(Text(metadata_age(snap.metadata_age), role("muted", bar=True)))
        self.top.set_right(parts)

    def show_counts(self, snap: CatalogSnapshot, shown: int, to_install: int, to_remove: int,
                    ms: float | None) -> None:
        """The left of the top line: the filter or the search, its rows, the marks."""
        b = self.browser
        label = b.filter.label if b.filter is not None else ""
        text = b.search.text()
        # an entry of Search results is labelled with its search already
        if text and (b.filter is None or b.filter.query != (text, int(b.search.mode()))):
            label = _("“{text}” in {filter}").format(text=text, filter=label)
        line = Text(label)
        line.append(f"  {shown}", role("muted", bar=True))
        if n := len(b.packages.marks):
            line.append("  ")
            line.append(ngettext("{n} change marked", "{n} changes marked", n).format(n=n), role("marked", bar=True))
        self.top.set_status(line)

    def show_error(self, error: BaseException) -> None:
        self.top.set_status(error_text(error))

    def apply_actions(self, state: ActionState, catalog: bool, busy: bool) -> None:
        self.actions = state  # the menus (§7.7) and the keys (§6.5) read it when used
        self.app.refresh_bindings()  # the footer shows Apply and Mark All Upgrades only while they are on

    def set_reload_enabled(self, on: bool) -> None:
        self.reload_enabled = on

    def set_apply_enabled(self, on: bool) -> None:
        self.apply_enabled = on

    # ---------------------------------------------------------------- BrowserView: dialogs

    def review_changes(self, preview: TransactionPreview, request: dict, basearch: str, resolve,
                       done: Callable[[dict | None], None]) -> None:
        """The Apply changes dialog (§10.1); `done` from its dismissal, so that the progress dialog the transaction
        opens comes after it (kram.tui.root)."""
        self.app.push_screen(ApplyDialog(preview, request, basearch, resolve), done)

    def run_helper(self, request: dict, title: str, done: Callable[[dict | None], None]) -> None:
        """The request with its progress dialog, shown by the root flow: at once, or when the authentication has
        something to say (kram.tui.root)."""
        dialog = ProgressDialog(self.browser.helper, request, title, lambda ok, result: done(result if ok else None),
                                self.ui, self.root)
        if not dialog.start():
            self.ui.warn(title, _(BUSY))
            done(None)
            return
        self.root.present(dialog)

    def show_repos(self, data, done: Callable[[ReposChoice | None], None]) -> None:
        """The Repositories dialog; `done(choice)` from its dismissal, so that the progress dialog of Apply comes
        after it. A removal or a mirror change made from it reloads the catalog: the dialog then shows the new
        state."""
        b = self.browser
        dialog = ReposDialog(data, self.ui, on_remove=b.remove_repos, on_mirrors=b.open_mirrors)
        shown = [True]

        def refresh(snap) -> None:
            b.repos_data(snap, lambda new: shown[0] and dialog.set_data(new))

        def closed(choice: ReposChoice | None) -> None:
            shown[0] = False  # data read for it later is dropped
            b.catalog_loaded.disconnect(refresh)
            done(choice)
        b.catalog_loaded.connect(refresh)
        self.app.push_screen(dialog, closed)

    def show_mirrors(self, repo, source, fastestmirror: bool, apply: Callable[[MirrorChoice], None]) -> None:
        """Over the Repositories dialog, which stays open under it; a choice is applied while this one stays open
        too, and the reload shows it the new state."""
        b = self.browser
        dialog = MirrorsDialog(repo, source, fastestmirror, self.ui, on_choice=apply)

        def refresh(snap) -> None:
            if (state := b.mirror_state(snap, repo.id)) is not None:
                dialog.set_state(*state)
        b.catalog_loaded.connect(refresh)
        self.app.push_screen(dialog, lambda _result: b.catalog_loaded.disconnect(refresh))

    def quit(self) -> None:
        self.app.request_quit()

    # ---------------------------------------------------------------- COPR and the history (§10.6, §10.7)

    def open_copr(self) -> None:
        """The COPR dialog (kram.gtk.window.open_copr): a change made from it runs over it and reloads the catalog,
        after which it shows the new state; Packages closes it and shows the project's packages."""
        b = self.browser
        if not b.snapshot or b.busy():
            return
        dialog = CoprDialog(self.ui, lambda request, title: b.run_helper_and_reload(request, title))
        shown = [True]

        def refresh(snap) -> None:
            b.dnf.submit(b.catalog.repo_package_counts, lambda counts: shown[0] and dialog.set_catalog(snap, counts),
                         lambda _e: None)  # the dialog keeps the counts it has

        def closed(repo_id: str | None) -> None:
            shown[0] = False  # counts read for it later are dropped
            b.catalog_loaded.disconnect(refresh)
            if repo_id:
                b.show_repo_packages(repo_id)
        refresh(b.snapshot)
        b.catalog_loaded.connect(refresh)  # after enabling, disabling or removing a project
        self.app.push_screen(dialog, closed)

    def open_history(self, name: str | None = None) -> None:
        """File → Transaction History; with a package's name, filtered by it (Package → Show in History). A package
        chosen in it closes it and is selected in the list (kram.gtk.window._show_from_history)."""
        b = self.browser
        if b.snapshot is None:
            return
        dialog = HistoryDialog(b.dnf, b.catalog, self.scheduler, name=name or "")
        dialog.on_undo = lambda tid: b.undo_transaction(tid, dialog.rows_of(tid), dialog.close_history)

        def refresh(snap) -> None:  # after Apply (an undo of groups runs from over it) the new transaction shows
            dialog.reload()
            dialog.set_marking(True, b.busy())

        def closed(key: tuple[str, str] | None) -> None:
            b.catalog_loaded.disconnect(refresh)
            if key is not None:
                b.navigate(key)
                self.focus_list()
        b.catalog_loaded.connect(refresh)
        dialog.set_marking(True, b.busy())
        self.app.push_screen(dialog, closed)

    def show_in_history(self) -> None:
        rows = self.selected_rows()
        if len(rows) == 1:
            self.open_history(rows[0].name)

    # ---------------------------------------------------------------- a package file and Cleanup (§10.8, §10.9)

    def open_package_file(self, path: str | None = None) -> None:
        """File → Open Package File… (kram.gtk.window.open_package_file): a path line in the folder of the last
        file; with `path` (a paste), that file at once."""
        if not self.browser.can_open_file():
            return
        if path:
            self.install_file(path)
            return

        def chosen(path: str | None) -> None:
            # from the path line's dismissal, which may still be on the screens: no can_open_file again
            if path:
                settings.set(INSTALL_DIR_KEY, str(Path(path).parent))
                self.install_file(path)
        self.ui.choose_open_file(_("Open package file"), settings.get(INSTALL_DIR_KEY, downloads_dir()),
                                 _("RPM packages (*.rpm)"), chosen)

    def install_file(self, path: str) -> None:
        """The Install package file dialog over the window; a change it made reloads the catalog."""
        b = self.browser
        if b.snapshot is None:
            return

        def run(request: dict, title: str, done: Callable[[bool], None]) -> None:
            b.run_helper(request, title, lambda result: done(result is not None))

        def closed(changed: bool | None) -> None:
            if changed:
                b.reload()
            b.update_actions()
        dialog = InstallDialog(path, b.catalog, b.dnf, busy=lambda: b.helper.busy, run=run,
                               basearch=b.snapshot.basearch, marks=len(b.packages.marks))
        self.app.push_screen(dialog, closed)

    def paste(self, text: str) -> bool:
        """A paste into the window (INSTALL_FILE_DROP): the path of an `.rpm` opens it in the installer, as a drop
        does in the GUIs; nothing while a dialog is open or for anything else. False: not taken."""
        path = pasted_rpm(text)
        if path is None or not self.browser.can_open_file():
            return False
        self.open_package_file(path)
        return True

    def open_notifications(self) -> None:
        """Settings → Update Notifications… (§10.11)."""
        self.app.push_screen(NotifierDialog(self.ui))

    def open_upgrade(self) -> None:
        """`r` while the top line says a new Fedora release is out (§10.12): its dialog, with the check made for
        that release earlier in the session, if any (kram.gtk.window.open_upgrade)."""
        target, snap = self.releases.target(), self.browser.snapshot
        if target is None or snap is None:
            return
        if self.upgrade is None or self.upgrade[0].target != target:
            state = UpgradeState(target)
            check = UpgradeCheck(target, self.browser.dnf, loop.post, state)
            self.upgrade = state, check
            check.ask_copr(snap)
        state, check = self.upgrade
        self.app.push_screen(UpgradeDialog(state, check, self.releases.running, self.releases.running_eol(),
                                           self.ui))

    def open_columns(self) -> None:
        """Settings → Columns… (§10.18): a change shows in the list at once and is saved."""
        def apply(columns: Columns) -> None:
            self.list.set_columns(columns)
            preferences.set_value(preferences.TUI_COLUMNS, json.dumps(columns.to_dict()))

        def shown_width(col: int) -> int:
            return next((w for c, w in self.list.columns if c == col), 0)
        self.app.push_screen(ColumnsDialog(self.list.columns_state, apply, shown_width))

    def open_cache(self) -> None:
        """Settings → Cleanup… (kram.gtk.window.open_cache)."""
        b = self.browser
        if not b.snapshot or b.busy():
            return
        self.app.push_screen(CacheDialog(b.dnf, b.clean_cache, self.ui, run_helper=b.run_helper))

    def _edit_filters(self, filters, snap, select, new, resolve_provides, done) -> None:
        """Settings → Custom Filters…, New Filter from Current View, `e` on a custom filter in the sidebar (§10.10):
        `done` from the dialog's dismissal."""
        self.app.push_screen(FiltersDialog(filters, snap, self.ui, select=select, new=new,
                                           resolve_provides=resolve_provides, scheduler=self.scheduler), done)

    # ---------------------------------------------------------------- the sidebar's menu and keys (§7.2.6)

    def sidebar_menu(self, entry) -> list[DynamicItem | str | None]:
        return self.browser.sidebar_menu(entry)

    def menu_item(self, item: DynamicItem | str) -> tuple[str, bool]:
        """(label, enabled) of an item of a menu built when it opens: a dynamic item, or an action by its id."""
        if isinstance(item, DynamicItem):
            return item.label, item.enabled and item.run is not None
        return self.defs[item].label, self.action_enabled(item)

    def run_menu_item(self, item: DynamicItem | str) -> None:
        if not self.menu_item(item)[1]:
            return
        if isinstance(item, DynamicItem):
            item.run()
        else:
            self.run_action(item)

    # ---------------------------------------------------------------- the actions (kram.app.actions)

    def action_enabled(self, action_id: str) -> bool:
        """`action_id` is an action of kram.app.actions or one of the ids of `ActionState` ("downgrade",
        "mark_upgrades_menu")."""
        if action_id in ("reload", "reload_cache"):
            return self.reload_enabled
        default = self.defs[action_id].enabled if action_id in self.defs else False
        return self.actions.enabled.get(action_id, default) if self.actions is not None else default

    def action_visible(self, action_id: str) -> bool:
        default = self.defs[action_id].visible
        return self.actions.visible.get(action_id, default) if self.actions is not None else default

    def disabled_reason(self, action_id: str) -> str:
        """Why an action is off now, for the menu's status line (§7.7.1): the GUIs grey it out and say nothing,
        a terminal has room for a line."""
        b = self.browser
        if b.snapshot is None or action_id in ("reload", "reload_cache"):
            return _("Loading the package catalog…")
        if b.busy():
            return _(BUSY)
        if action_id in ("apply", "unmark_all", "save_marks"):
            return _("Nothing is marked")
        if action_id in ("mark_upgrades", "mark_upgrades_menu"):
            return _("No package has an upgrade")
        if action_id.startswith("mark_upgrades."):
            return _("No upgrade of this kind")
        if action_id == "mark_unneeded":
            return _("No unneeded dependencies")
        if action_id in ("downgrade", "show_in_history"):
            return _("Only for one package at a time") if len(self.selected_rows()) != 1 else \
                _("Not for this package")
        if action_id == "unmark":
            return _("Not marked")
        return _("Not for this package") if self.selected_rows() else ""

    def run_action(self, action_id: str) -> None:
        """What the action does, as the GUIs' menus run it; an action that is off says why on the top line."""
        if not self.action_enabled(action_id):
            if reason := self.disabled_reason(action_id):
                self.ui.status(reason, STATUS_MESSAGE_MS)
            return
        self.action_runs()[action_id]()

    def action_runs(self) -> dict[str, Callable[[], None]]:
        """What each action runs."""
        b, marker = self.browser, self.browser.marker
        return {
            "reload": b.refresh_metadata, "reload_cache": b.reload, "mark_upgrades": marker.mark_all_upgrades,
            "apply": b.apply, "repos": b.open_repos, "copr": self.open_copr, "history": self.open_history,
            "open_file": self.open_package_file, "cache": self.open_cache, "notifications": self.open_notifications,
            "show_in_history": self.show_in_history,
            "lock": lambda: b.set_version_lock(True), "unlock": lambda: b.set_version_lock(False),
            "mark_unneeded": marker.mark_unneeded, "unmark_all": marker.unmark_all,
            "properties": lambda: self.show_tab("general"), "why_blocked": lambda: self.show_tab("dependencies"),
            "find": self.find, "back": b.go_back, "quit": self.app.request_quit, "about": self.about,
            "copy_name": b.copy_names, "copy_nevra": b.copy_nevras, "unmark": b.unmark_selected,
            "filters": b.custom_filters.edit,
            "new_filter": lambda: b.custom_filters.new_from_view(b.filter, b.search.text(), b.search.mode()),
            "save_marks": b.save_marks, "read_marks": b.read_marks, "export_csv": b.export_csv,
            **{mark_upgrades_id(kind): lambda kind=kind: marker.mark_upgrades(kind) for kind in UPGRADE_KINDS},
            **{mark_id(a): lambda a=a: b.mark_selected(a) for a in MARK_ACTIONS},
        }

    def run_either(self, *action_ids: str) -> None:
        """A key with two actions (`+`: install or upgrade, `=`: lock or unlock): the first one that is on."""
        self.run_action(next((a for a in action_ids if self.action_enabled(a)), action_ids[0]))

    def show_tab(self, name: str) -> None:
        """Properties, Why It Cannot Be Upgraded: that tab of the details, shown."""
        self.details.select_name(name)
        self.open_details()

    def about(self) -> None:
        self.app.push_screen(AboutDialog(self.ui))

    def change_group(self, key: str, action: Action) -> None:
        """`+` / `-` on a group or an environment of the sidebar: what its menu's first item of that kind does
        (Install, or Upgrade when it is installed; Remove), through Browser.change_group. When that item is off,
        the top line says why, as its tooltip does in the GUIs."""
        b = self.browser
        group = b.marker.group(key)
        if group is None:
            return
        picked: list[tuple[Action, bool]] = []

        def note(_group: GroupInfo, act: Action, optional: bool) -> None:
            picked.append((act, optional))
        for item in group_menu(group, busy=b.busy(), run=note):
            item.run()
            act, optional = picked.pop()
            if optional or (act is Action.REMOVE) != (action is Action.REMOVE):
                continue
            if item.enabled:
                b.change_group(group, act, False)
            elif item.tip:
                self.ui.status(item.tip, STATUS_MESSAGE_MS)
            return

    # ---------------------------------------------------------------- the list's keys (PackageTable.commands)

    def choose_sort(self) -> None:
        """`s`: the shown columns as a list; the one picked sorts ascending, or as it was if it is the sorted one."""
        current = self.list.sort_shown
        items = [(col, column_label(col)) for col, _w in self.list.columns]

        def chosen(col: int | None) -> None:
            if col is not None:
                self.sort(col, current[1] if current is not None and current[0] == col else False)
        self.app.push_screen(ChoiceList(_("Sort by"), items, current[0] if current else None), chosen)

    def reverse_sort(self) -> None:
        """`S`: the sort the other way round; a ranked list gets the user's last column sort, reversed."""
        col, descending = self.list.sort_shown or self.browser.user_sort
        self.sort(col, not descending)

    def sort(self, column: int, descending: bool) -> None:
        b = self.browser
        b.user_sorted(column, descending)
        self.show_sort((column, descending))
        b.packages.sort(column, descending)

    def context_menu(self, at: tuple[int, int]) -> None:
        """The row's menu (§7.7.2) at the screen cell `at`."""
        open_table_menu(self, at)

    def status_click(self, at: tuple[int, int]) -> None:
        """`space`, a click on the status cell (LIST_STATUS_CLICK), as in the GUIs: with the setting, the likely mark
        of the selected rows (kram.gtk.window._status_click); without it, or for rows that have none, the Package
        menu at the screen cell `at`."""
        if preferences.value(preferences.STATUS_CLICK) and self.likely_mark():
            return
        open_table_menu(self, at, package_menu_items())

    def likely_mark(self) -> bool:
        """A double click (LIST_DOUBLE_CLICK_MARK): unmark a marked row, mark one for installation or upgrade
        (Marker.toggle_likely), each selected row; False when none of them has one."""
        marker = self.browser.marker
        return any([marker.toggle_likely(row) for row in self.selected_rows()])

    def mark_upgrades(self) -> None:
        """`U`, ctrl+u: with upgrades that have advisories, the list of Edit → Mark Upgrades (all, or by advisory
        kind: MARK_UPGRADE_BY_ADVISORY), which the GUIs' split button offers; else all upgrades at once."""
        marker = self.browser.marker
        kinds = [mark_upgrades_id(kind) for kind in UPGRADE_KINDS if marker.upgrades_of(kind)]
        if not kinds or not self.action_enabled("mark_upgrades"):
            self.run_action("mark_upgrades")
            return
        items = [(a, self.defs[a].label) for a in ("mark_upgrades", *kinds)]
        self.app.push_screen(ChoiceList(menu_title(mark_upgrades_menu()), items, "mark_upgrades"),
                             lambda action_id: action_id is not None and self.run_action(action_id))

    def find(self) -> None:
        """`/`, ctrl+f and the menu's Find (§7.6): the search dialog, once there is a catalog to search."""
        if self.browser.snapshot is not None:
            open_search(self)

    def copy_names(self) -> None:
        self.browser.copy_names()

    def copy_nevras(self) -> None:
        self.browser.copy_nevras()

    def open_details(self) -> None:
        if not self.app.has_focus_in("details"):
            self.app.action_toggle_panel("details")

    def follow_empty_link(self, link: str) -> None:
        self.browser.empty_link(link)

    def escape(self) -> bool:
        """Esc in the list: quits while the catalog waits for the lock (§7.1); False: not taken."""
        if self.waiting_for_lock and self.browser.snapshot is None:
            self.app.request_quit()
            return True
        return False
