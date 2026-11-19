"""The main window's actions and its menu bar: text, icon, shortcut and tooltip of each. What they do, the window
connects."""
import html

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QMenu, QMenuBar, QWidget

from ..core.filters import UPGRADES_FIXES, UPGRADES_SECURITY, UPGRADES_SECURITY_HIGH
from ..core.marks import Action
from ..i18n import _


class WindowActions:
    def __init__(self, window: QWidget):
        self._window = window
        a = self._action
        self.reload = a(_("Reload"), "view-refresh", "Ctrl+R",
                        tip=_("Refresh repository metadata and reload the catalog (needs a password)"))
        self.reload.setShortcuts([QKeySequence("Ctrl+R"), QKeySequence("F5")])  # F5: what browsers and file managers use
        self.reload_cache = a(_("Reload from cache"), "view-refresh", "Ctrl+Shift+R",
                              tip=_("Reload the catalog from the local cache, without network or password"))
        self.mark_upgrades = a(_("Mark All Upgrades"), None, "Ctrl+U",
                               tip=_("Mark every package that has a newer version for upgrade"))
        # the other ways to mark upgrades, by their advisories (the arrow next to the toolbar button, Edit menu);
        # upgrades from repositories without advisories (RPM Fusion, COPR, most third-party ones) are not among them
        self.mark_upgrades_of_kind = {
            kind: a(text, tip=tip)
            for kind, text, tip in (
                (UPGRADES_SECURITY, _("Mark Security Upgrades"),
                 _("Mark the upgrades that fix a security issue, as dnf upgrade --security")),
                (UPGRADES_SECURITY_HIGH, _("Mark Critical and Important Security Upgrades"),
                 _("Mark the upgrades that fix a security issue rated critical or important")),
                (UPGRADES_FIXES, _("Mark Security and Bug Fix Upgrades"),
                 _("Mark the upgrades that fix a security issue or bugs, leaving out enhancements")),
            )}
        self.mark_upgrades_menu = QMenu(_("Mark Upgrades"), window)
        self.mark_upgrades_menu.addAction(self.mark_upgrades)
        self.mark_upgrades_menu.addSeparator()
        self.mark_upgrades_menu.addActions(list(self.mark_upgrades_of_kind.values()))
        # Breeze's monochrome update glyphs match the other toolbar icons; system-software-update is a colour app
        # icon there, kept as the fallback. With upgrades to mark the button shows update-medium; update-none says
        # "nothing to update" and its dim grey is exactly right for the disabled button, but would make an enabled
        # one look disabled
        fallback = QIcon.fromTheme("system-software-update")
        self._upgrade_icons = {True: QIcon.fromTheme("update-medium", fallback),
                               False: QIcon.fromTheme("update-none", fallback)}
        self.mark_unneeded = a(_("Mark Unneeded Dependencies for Removal"), "edit-delete", enabled=False,
                               tip=_("Mark for removal the dependencies nothing needs any more, as dnf autoremove "
                                     "does"))
        self.apply = a(_("Apply"), "dialog-ok-apply", "Ctrl+P", enabled=False,
                       tip=_("Review and apply the marked changes"))
        self.unmark_all = a(_("Unmark All"), "edit-clear", "Ctrl+Shift+Z", enabled=False,
                            tip=_("Discard all marked changes"))
        self.properties = a(_("Properties"), "document-properties")
        self.repos = a(_("Repositories"), "configure", enabled=False,
                       tip=_("Enable or disable software repositories"))
        self.filters = a(_("Custom Filters…"), "view-filter", enabled=False,
                         tip=_("Create and edit your own filters for the sidebar"))
        self.new_filter = a(_("New Filter from Current View…"), "list-add", enabled=False,
                            tip=_("A custom filter with the current sidebar selection and search"))
        self.copr = a(_("COPR"), "folder-cloud", enabled=False, tip=_("Manage COPR projects: community repositories"))
        self.cache = a(_("Cleanup…"), "edit-clear-all", enabled=False,
                       tip=_("Clean the package caches and remove leftover configuration files"))
        self.notifications = a(_("Update Notifications…"), "preferences-desktop-notification",
                               tip=_("An icon in the system tray when updates are available"))
        # Synaptic's "Clicking on the status icon marks the most likely action", off by default there too
        self.status_click = QAction(_("Clicking the status icon marks the likely action"), window, checkable=True)
        tip = _("A click on the status icon unmarks a marked package, marks one that is not installed for "
                "installation and one with an upgrade for upgrade. Otherwise it opens the action menu, as "
                "right-clicking does.")
        self.status_click.setToolTip(f"<p>{html.escape(tip)}</p>")  # rich text, so that Qt wraps it
        self.status_click.setStatusTip(tip)
        self.status_click.toggled.connect(lambda on: QSettings().setValue("table/status_click", on))
        self.find = a(_("Find"), "edit-find", QKeySequence.StandardKey.Find)
        self.back = a(_("Back"), "go-previous", "Alt+Left",
                      tip=_("Go back to the previous package (after following a dependency)"))
        self.save_marks = a(_("Save Markings As…"), "document-save-as", "Ctrl+S", enabled=False,
                            tip=_("Save the marked changes to a text file"))
        self.read_marks = a(_("Read Markings…"), "document-open", "Ctrl+O", enabled=False,
                            tip=_("Mark the changes listed in a saved markings file"))
        self.export_csv = a(_("Export List as CSV…"), "document-export", enabled=False,
                            tip=_("Save the packages listed now, in their order, to a CSV file"))
        self.open_file = a(_("Open Package File…"), "document-open", enabled=False,
                           tip=_("Install a downloaded .rpm file (you can also drop it on the window)"))
        self.quit = a(_("Quit"), "application-exit", QKeySequence.StandardKey.Quit)
        self.about = a(_("About Kram"), "help-about")

        # scoped to the package table (see `table_actions`): Ctrl+C still copies text in the search field and the
        # detail tabs, Del/Ins/Ctrl+Z keep their meaning in the search field
        self.copy_name = a(_("Copy Name"), "edit-copy", "Ctrl+C", table=True)
        self.copy_nevra = a(_("Copy name-version-release.arch"), "edit-copy", "Ctrl+Shift+C", table=True)
        self.mark: dict[Action, QAction] = {
            action: a(text, icon, shortcut, tip=text, table=True)
            for action, text, icon, shortcut in [
                (Action.INSTALL, _("Mark for Installation"), "list-add", "Ins"),
                (Action.UPGRADE, _("Mark for Upgrade"), "go-up", None),
                (Action.REINSTALL, _("Mark for Reinstallation"), "view-refresh", None),
                (Action.REMOVE, _("Mark for Removal"), "list-remove", "Del"),
                (Action.MARK_USER, _("Mark as Installed by User"), "user-identity", None),
                (Action.MARK_DEP, _("Mark as Dependency"), "link", None),
            ]}
        self.downgrade_menu = QMenu(_("Downgrade to Version"), window)
        self.downgrade_menu.setIcon(QIcon.fromTheme("go-down"))
        # dnf's version lock: changed at once through the helper, not marked for Apply (it installs nothing)
        self.lock = a(_("Lock Version"), "object-locked", table=True,
                      tip=_("Keep the installed version: upgrades leave it out until it is unlocked (needs a "
                            "password)"))
        self.unlock = a(_("Unlock Version"), "object-unlocked", table=True,
                        tip=_("Remove the version lock: the package gets upgrades again (needs a password)"))
        self.unmark = a(_("Unmark"), "edit-undo", "Ctrl+Z", tip=_("Unmark the selected packages"), table=True)
        self.set_upgrades_available(False)

    def _action(self, text, icon=None, shortcut=None, enabled=True, tip=None, table=False) -> QAction:
        a = QAction(QIcon.fromTheme(icon) if icon else QIcon(), text, self._window)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setEnabled(enabled)
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        if table:
            a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        else:
            self._window.addAction(a)  # shortcuts work even when the action is only in a menu
        return a

    def table_actions(self) -> list[QAction]:
        """For the package table to add: their shortcuts work only there."""
        return [self.copy_name, self.copy_nevra, *self.mark.values(), self.unmark]

    def set_upgrades_available(self, available: bool) -> None:
        self.mark_upgrades.setEnabled(available)
        self.mark_upgrades_menu.setEnabled(available)
        self.mark_upgrades.setIcon(self._upgrade_icons[available])

    def fill_package_menu(self, menu: QMenu) -> None:
        """The Package menu, the table's context menu and the status icon's menu."""
        menu.addActions(list(self.mark.values()))
        menu.addMenu(self.downgrade_menu)
        menu.addSeparator()
        menu.addActions([self.lock, self.unlock])
        menu.addSeparator()
        menu.addAction(self.unmark)

    def fill_menu_bar(self, mb: QMenuBar, settings: list[QAction], toolbar_styles: list[QAction]) -> None:
        """`settings`: checkable settings of other parts, at the end of the Settings menu."""
        m = mb.addMenu(_("&File"))
        m.addAction(self.open_file)
        m.addSeparator()
        m.addActions([self.reload, self.reload_cache])
        m.addSeparator()
        m.addActions([self.read_marks, self.save_marks])
        m.addAction(self.export_csv)
        m.addSeparator()
        m.addAction(self.quit)
        m = mb.addMenu(_("&Edit"))
        m.addMenu(self.mark_upgrades_menu)
        m.addAction(self.mark_unneeded)
        m.addSeparator()
        m.addActions([self.unmark_all, self.apply])
        m.addSeparator()
        m.addActions([self.copy_name, self.copy_nevra])
        m.addSeparator()
        m.addAction(self.find)
        m = mb.addMenu(_("&Package"))
        self.fill_package_menu(m)
        m.addSeparator()
        m.addActions([self.properties, self.back])
        m = mb.addMenu(_("&Settings"))
        m.addActions([self.repos, self.copr, self.cache, self.notifications])
        m.addSeparator()
        m.addActions([self.filters, self.new_filter])
        m.addSeparator()
        m.addActions([self.status_click, *settings])
        m.setToolTipsVisible(True)
        m.addMenu(_("Toolbar")).addActions(toolbar_styles)
        m = mb.addMenu(_("&Help"))
        m.addAction(self.about)
