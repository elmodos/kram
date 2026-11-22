"""Feature parity between the front ends: the list of every feature Kram has, and how each front end supports it.

This is the source of truth for the parity of the Qt and GTK front ends. A feature is added here when it is built, with
its description and both front ends' support. Every test that proves a SUPPORTED entry is marked
`@pytest.mark.feature(Feature.X, front="qt" | "gtk")`; tests/test_parity.py reads the marks from the sources.
PLANNED and NOT_IMPLEMENTED fail the run for a released front end (FRONTS_RELEASED); PARTIAL and NOT_INTENDED
need a note. docs/PARITY.md explains the statuses and the release rule. Names are sorted and grouped by their prefix
(the scope): APPLY_ and DIALOG_ for dialogs, DETAILS_ for the detail tabs, LIST_ for the package list, and so on.

No toolkit is imported here: the tables are plain data, so the toolkit-free layer can hold them. Checked by
tests/test_parity.py: keep the order and the layout. docs/PARITY.md explains the statuses and how to add a feature.
"""
from enum import Enum


class Feature(Enum):
    DETAILS_ADVISORIES_TAB = "details_advisories_tab"
    DETAILS_BLOCKED_REASON = "details_blocked_reason"
    DETAILS_CHANGELOG = "details_changelog"
    DETAILS_DESCRIPTION = "details_description"
    DETAILS_FILES_COPY_PATH = "details_files_copy_path"
    DETAILS_FILES_FILTER = "details_files_filter"
    DETAILS_FILES_LIST = "details_files_list"
    DETAILS_FILES_SHOW_IN_FM = "details_files_show_in_fm"
    DETAILS_FILES_TREE = "details_files_tree"
    DETAILS_LINKS = "details_links"
    DETAILS_REMEMBER_TAB = "details_remember_tab"
    DETAILS_TABS = "details_tabs"
    DETAILS_VERSIONS = "details_versions"
    DIALOG_ABOUT_TOOLKIT = "dialog_about_toolkit"
    DIALOG_APPLY = "dialog_apply"
    DIALOG_APPLY_CANNOT_APPLY = "dialog_apply_cannot_apply"
    DIALOG_APPLY_COMMAND = "dialog_apply_command"
    DIALOG_APPLY_DOWNLOAD_ONLY = "dialog_apply_download_only"
    DIALOG_APPLY_FREE_SPACE = "dialog_apply_free_space"
    DIALOG_APPLY_RECOMMENDATIONS = "dialog_apply_recommendations"
    DIALOG_APPLY_SKIPPED = "dialog_apply_skipped"
    DIALOG_CLEANUP = "dialog_cleanup"
    DIALOG_CLEANUP_CACHES = "dialog_cleanup_caches"
    DIALOG_CLEANUP_COMPARE = "dialog_cleanup_compare"
    DIALOG_CLEANUP_DELETE_UNUSED = "dialog_cleanup_delete_unused"
    DIALOG_CLEANUP_LEFTOVERS = "dialog_cleanup_leftovers"
    DIALOG_CLEANUP_SEARCH_ALL = "dialog_cleanup_search_all"
    DIALOG_COPR = "dialog_copr"
    DIALOG_COPR_ENABLE_FROM_SEARCH = "dialog_copr_enable_from_search"
    DIALOG_COPR_NO_BUILD_QUESTION = "dialog_copr_no_build_question"
    DIALOG_COPR_PACKAGES = "dialog_copr_packages"
    DIALOG_COPR_REMOVE_QUESTION = "dialog_copr_remove_question"
    DIALOG_CUSTOM_FILTERS = "dialog_custom_filters"
    DIALOG_CUSTOM_FILTERS_COUNT = "dialog_custom_filters_count"
    DIALOG_CUSTOM_FILTERS_MATCH = "dialog_custom_filters_match"
    DIALOG_CUSTOM_FILTERS_NEW_FROM_VIEW = "dialog_custom_filters_new_from_view"
    DIALOG_HISTORY = "dialog_history"
    DIALOG_HISTORY_FILTER = "dialog_history_filter"
    DIALOG_HISTORY_OPEN_PACKAGE = "dialog_history_open_package"
    DIALOG_HISTORY_UNDO = "dialog_history_undo"
    DIALOG_INSTALL_FILE = "dialog_install_file"
    DIALOG_INSTALL_FILE_CHECK = "dialog_install_file_check"
    DIALOG_INSTALL_FILE_COMMAND = "dialog_install_file_command"
    DIALOG_INSTALL_FILE_RECOMMENDATIONS = "dialog_install_file_recommendations"
    DIALOG_NOTIFICATIONS = "dialog_notifications"
    DIALOG_NOTIFICATIONS_FEDORA_TIMER = "dialog_notifications_fedora_timer"
    DIALOG_NOTIFICATIONS_STALE_DAYS = "dialog_notifications_stale_days"
    DIALOG_PROGRESS = "dialog_progress"
    DIALOG_PROGRESS_AUTO_CLOSE = "dialog_progress_auto_close"
    DIALOG_PROGRESS_CLOSE_LOCK = "dialog_progress_close_lock"
    DIALOG_PROGRESS_KEY_QUESTION = "dialog_progress_key_question"
    DIALOG_PROGRESS_LOG = "dialog_progress_log"
    DIALOG_REPOSITORIES = "dialog_repositories"
    DIALOG_REPOSITORIES_FILTER = "dialog_repositories_filter"
    DIALOG_REPOSITORIES_REMOVE = "dialog_repositories_remove"
    DIALOG_REPOSITORIES_SHOW_AUX = "dialog_repositories_show_aux"
    DIALOG_WHATS_NEW = "dialog_whats_new"
    ICON_NON_PIXELATED = "icon_non_pixelated"
    INSTALL_FILE_ARGUMENT = "install_file_argument"
    INSTALL_FILE_DROP = "install_file_drop"
    INSTALL_FILE_OPEN_MENU = "install_file_open_menu"
    INSTANCE_ACTIVATION_TOKEN = "instance_activation_token"
    INSTANCE_TRAY = "instance_tray"
    LIST_COLUMNS = "list_columns"
    LIST_CONTEXT_MENU = "list_context_menu"
    LIST_DOUBLE_CLICK_MARK = "list_double_click_mark"
    LIST_EMPTY_EXPLANATION = "list_empty_explanation"
    LIST_LOCK_PADLOCK = "list_lock_padlock"
    LIST_MULTI_SELECT = "list_multi_select"
    LIST_ROW_TINT = "list_row_tint"
    LIST_SORT = "list_sort"
    LIST_STATUS_CLICK = "list_status_click"
    LIST_VERSION_LOCK = "list_version_lock"
    MARKINGS_CSV_EXPORT = "markings_csv_export"
    MARKINGS_FILE = "markings_file"
    MARK_APPLY_BUTTON = "mark_apply_button"
    MARK_INSTALL_REMOVE = "mark_install_remove"
    MARK_UNMARK_ALL = "mark_unmark_all"
    MARK_UNMARK_ONE = "mark_unmark_one"
    MARK_UNNEEDED = "mark_unneeded"
    MARK_UPGRADE_ALL = "mark_upgrade_all"
    MARK_UPGRADE_BY_ADVISORY = "mark_upgrade_by_advisory"
    MARK_UPGRADE_SPLIT_BUTTON = "mark_upgrade_split_button"
    MENU_ACCELERATORS = "menu_accelerators"
    MENU_BAR = "menu_bar"
    MENU_DOWNGRADE_SUBMENU = "menu_downgrade_submenu"
    MENU_HAMBURGER = "menu_hamburger"
    MENU_ICONS = "menu_icons"
    MENU_PACKAGE = "menu_package"
    MENU_SIDEBAR = "menu_sidebar"
    RELEASE_BUTTON = "release_button"
    RELEASE_DIALOG = "release_dialog"
    RELEASE_WATCH = "release_watch"
    SEARCH_BAR = "search_bar"
    SEARCH_FILTER_WHILE_TYPING = "search_filter_while_typing"
    SEARCH_MODES = "search_modes"
    SETTINGS_MENU_BAR = "settings_menu_bar"
    SETTINGS_REGISTRY = "settings_registry"
    SETTINGS_STATUS_CLICK = "settings_status_click"
    SETTINGS_TOOLBAR_STYLE = "settings_toolbar_style"
    SETTINGS_WATCH_RELEASES = "settings_watch_releases"
    SIDEBAR_COUNTS = "sidebar_counts"
    SIDEBAR_CUSTOM_FILTER_EDIT = "sidebar_custom_filter_edit"
    SIDEBAR_CUSTOM_FILTER_MENU = "sidebar_custom_filter_menu"
    SIDEBAR_ENVIRONMENTS_TREE = "sidebar_environments_tree"
    SIDEBAR_GROUP_CHANGE = "sidebar_group_change"
    SIDEBAR_SECTION_ICONS = "sidebar_section_icons"
    SIDEBAR_VIEWS = "sidebar_views"
    SYSTEM_FILE_MANAGER = "system_file_manager"
    SYSTEM_POLKIT = "system_polkit"
    SYSTEM_THEME_FOLLOWS_DESKTOP = "system_theme_follows_desktop"
    SYSTEM_WEB_LINKS = "system_web_links"
    TRANSLATIONS_CATALOGS = "translations_catalogs"
    WINDOW_CLOSE_PENDING = "window_close_pending"
    WINDOW_FRACTIONAL_SCALE = "window_fractional_scale"
    WINDOW_HEADER_BUTTONS = "window_header_buttons"
    WINDOW_KEYBOARD_ONLY = "window_keyboard_only"
    WINDOW_PANES_SAVED = "window_panes_saved"
    WINDOW_STATUS_BAR = "window_status_bar"


class Support(Enum):
    PLANNED = "planned"                  # a front end in development: not built yet, allowed until it is released
    NOT_IMPLEMENTED = "not_implemented"  # breaks parity once the front end is released
    SUPPORTED = "supported"              # proved by marked tests
    PARTIAL = "partial"                  # works, but not all of it is proved; the note says what
    NOT_INTENDED = "not_intended"        # deliberately absent or different; the note says why


class Entry:
    __slots__ = ("support", "note")

    def __init__(self, support: Support, note: str = ""):
        self.support, self.note = support, note


DESCRIPTIONS: dict[Feature, str] = {
    Feature.DETAILS_ADVISORIES_TAB: 'The advisories tab appears only for packages that have advisories',
    Feature.DETAILS_BLOCKED_REASON: 'The dependencies tab says why an upgrade is blocked, and asks for it once',
    Feature.DETAILS_CHANGELOG: 'The changelog tab of a package',
    Feature.DETAILS_DESCRIPTION: 'The description tab: summary, long description, homepage',
    Feature.DETAILS_FILES_COPY_PATH: 'Copy Path in the Files tab copies the selected paths (Ctrl+C)',
    Feature.DETAILS_FILES_FILTER: 'The Files tab filter: text anywhere in the path, or a shell pattern; matches are bold',
    Feature.DETAILS_FILES_LIST: 'The Files tab as a flat list of full paths, one per row, instead of the folder tree',
    Feature.DETAILS_FILES_SHOW_IN_FM: 'Show in File Manager for a file of the Files tab',
    Feature.DETAILS_FILES_TREE: 'The Files tab as a folder tree, every folder open, with the filter',
    Feature.DETAILS_LINKS: 'Links in the tabs: packages, dependencies and web pages',
    Feature.DETAILS_REMEMBER_TAB: 'The details tab stays the one the user chose, across sessions',
    Feature.DETAILS_TABS: 'The detail tabs: description, general, dependencies, advisories, files, versions, changelog',
    Feature.DETAILS_VERSIONS: 'The Versions tab: the versions of a package, its repository and its state',
    Feature.DIALOG_ABOUT_TOOLKIT: 'About names the front end and its toolkit version',
    Feature.DIALOG_APPLY: 'The Apply changes review: everything the transaction does, before it runs',
    Feature.DIALOG_APPLY_CANNOT_APPLY: "When nothing can be done: the problem, with 'Undo What Is Possible' and 'Show Locked Packages'",
    Feature.DIALOG_APPLY_COMMAND: "'Equivalent command': the dnf5 command the transaction runs, shown read-only",
    Feature.DIALOG_APPLY_DOWNLOAD_ONLY: "Checkbox 'Download packages only': fetch the packages, install nothing",
    Feature.DIALOG_APPLY_FREE_SPACE: 'Apply stays off when the disk cannot hold the change; a download that fits is allowed',
    Feature.DIALOG_APPLY_RECOMMENDATIONS: 'Recommended packages with a checkbox each; unchecking resolves again without them',
    Feature.DIALOG_APPLY_SKIPPED: 'Marked changes the resolver left out are shown above the list',
    Feature.DIALOG_CLEANUP: 'Cleanup: the package caches and the leftover configuration files',
    Feature.DIALOG_CLEANUP_CACHES: 'Cache rows: size, number of files, Clean and Download Again',
    Feature.DIALOG_CLEANUP_COMPARE: 'Compare: a leftover file against the current one, as a coloured diff',
    Feature.DIALOG_CLEANUP_DELETE_UNUSED: 'Delete Unused: remove leftover copies whose file no longer exists, after a question',
    Feature.DIALOG_CLEANUP_LEFTOVERS: 'Leftover configuration files (.rpmsave, .rpmnew) with their date and size',
    Feature.DIALOG_CLEANUP_SEARCH_ALL: 'Search All Folders: look in the folders only root can read, as root',
    Feature.DIALOG_COPR: 'COPR repositories: the enabled projects, and search for new ones',
    Feature.DIALOG_COPR_ENABLE_FROM_SEARCH: 'Enable a search result, or the owner/project typed in the field',
    Feature.DIALOG_COPR_NO_BUILD_QUESTION: 'Asks before enabling a project that has no build for this Fedora',
    Feature.DIALOG_COPR_PACKAGES: 'Show packages of an enabled COPR project from the dialog',
    Feature.DIALOG_COPR_REMOVE_QUESTION: "Remove asks first, with 'Show packages' when installed packages come from the project",
    Feature.DIALOG_CUSTOM_FILTERS: 'Custom Filters: named lists of conditions, edited in a dialog',
    Feature.DIALOG_CUSTOM_FILTERS_COUNT: 'Live count: how many packages the filter being edited matches',
    Feature.DIALOG_CUSTOM_FILTERS_MATCH: "'Show packages that match': all conditions or any condition",
    Feature.DIALOG_CUSTOM_FILTERS_NEW_FROM_VIEW: 'New Filter From View: a filter from the current view and search text',
    Feature.DIALOG_HISTORY: 'Transaction History: the transactions, their packages, and undo',
    Feature.DIALOG_HISTORY_FILTER: 'Filter the transactions by package name',
    Feature.DIALOG_HISTORY_OPEN_PACKAGE: 'A package of a transaction opens in the main window; the history closes',
    Feature.DIALOG_HISTORY_UNDO: 'Mark Changes to Undo: marks the changes that undo the selected transaction',
    Feature.DIALOG_INSTALL_FILE: 'Install Package File: what an .rpm does, and the install button',
    Feature.DIALOG_INSTALL_FILE_CHECK: 'Reinstall checks the installed files with rpm -V first; what it repairs is listed',
    Feature.DIALOG_INSTALL_FILE_COMMAND: "'Equivalent command': sudo dnf5 install <file>, read-only",
    Feature.DIALOG_INSTALL_FILE_RECOMMENDATIONS: 'Recommended packages of the file, with checkboxes',
    Feature.DIALOG_NOTIFICATIONS: "Update Notifications: the tray icon, the stale-data days, Fedora's timer, other notifiers",
    Feature.DIALOG_NOTIFICATIONS_FEDORA_TIMER: "Turn On Fedora's Update Check: asks for the password, shows the timer's state",
    Feature.DIALOG_NOTIFICATIONS_STALE_DAYS: 'Warn when the package information is older than N days',
    Feature.DIALOG_PROGRESS: 'The progress of a helper request: stage, bars, log',
    Feature.DIALOG_PROGRESS_AUTO_CLOSE: "Checkbox 'Close when finished successfully', remembered",
    Feature.DIALOG_PROGRESS_CLOSE_LOCK: 'The dialog cannot be closed while the transaction runs (Esc, close button, window close)',
    Feature.DIALOG_PROGRESS_KEY_QUESTION: 'The GPG key question of a repository, answered in the dialog',
    Feature.DIALOG_PROGRESS_LOG: "'Details' log of the helper's events, timestamped",
    Feature.DIALOG_REPOSITORIES: "Repositories: enable and disable, show packages, remove the user's own",
    Feature.DIALOG_REPOSITORIES_FILTER: 'Filter the repositories by id or name',
    Feature.DIALOG_REPOSITORIES_REMOVE: 'Remove names every repository of the file, and the packages that come from them',
    Feature.DIALOG_REPOSITORIES_SHOW_AUX: "Checkbox 'Show debuginfo and source repositories'",
    Feature.DIALOG_WHATS_NEW: "What's New: the release notes, newest first",
    Feature.ICON_NON_PIXELATED: 'The painted status, origin and mark icons are sharp at every screen scale',
    Feature.INSTALL_FILE_ARGUMENT: 'kram file.rpm opens the installer alone, without the main window',
    Feature.INSTALL_FILE_DROP: 'An .rpm dropped on the main window opens the installer',
    Feature.INSTALL_FILE_OPEN_MENU: 'File → Open Package File…: choose an .rpm, remembers its folder',
    Feature.INSTANCE_ACTIVATION_TOKEN: "A second start focuses the window with the desktop's activation token (Wayland)",
    Feature.INSTANCE_TRAY: "The tray's click shows the running Kram; kram --upgradable opens on the upgradable filter",
    Feature.LIST_COLUMNS: 'Columns can be shown and hidden, reordered and resized; the state is saved',
    Feature.LIST_CONTEXT_MENU: "Right-click on a row: the package's menu",
    Feature.LIST_DOUBLE_CLICK_MARK: 'Double click toggles the likely mark of the row',
    Feature.LIST_EMPTY_EXPLANATION: 'The empty list says why it is empty and links to the results',
    Feature.LIST_LOCK_PADLOCK: 'A padlock on a locked package, and the upgrade it holds back',
    Feature.LIST_MULTI_SELECT: 'Several rows selected at once; the actions apply to all of them',
    Feature.LIST_ROW_TINT: "Rows with a mark are tinted with the mark's colour",
    Feature.LIST_SORT: 'Sorting by a column header, one sort at a time',
    Feature.LIST_VERSION_LOCK: 'Lock Version and Unlock Version: keep a package at its installed version',
    Feature.LIST_STATUS_CLICK: 'A click on the status cell opens the status menu, or marks the likely action',
    Feature.MARKINGS_CSV_EXPORT: 'Export the package list as CSV',
    Feature.MARKINGS_FILE: 'Save the marks to a file and read them back',
    Feature.MARK_APPLY_BUTTON: 'The Apply button: previews the transaction, then runs it after the review',
    Feature.MARK_INSTALL_REMOVE: 'Mark for installation and for removal (Ins, Del)',
    Feature.MARK_UNMARK_ALL: 'Unmark All (Ctrl+Shift+Z)',
    Feature.MARK_UNMARK_ONE: 'Unmark the selected package (Ctrl+Z)',
    Feature.MARK_UNNEEDED: 'Mark unneeded dependencies for removal: what autoremove would remove',
    Feature.MARK_UPGRADE_ALL: 'Mark All Upgrades (Ctrl+U)',
    Feature.MARK_UPGRADE_BY_ADVISORY: 'Mark upgrades by advisory kind: security, critical and important, fixes',
    Feature.MARK_UPGRADE_SPLIT_BUTTON: 'The split button next to Reload: its arrow lists the advisory kinds',
    Feature.MENU_ACCELERATORS: 'Keyboard shortcuts, as the menus show them',
    Feature.MENU_BAR: 'The menu bar: File, Edit, Package, Settings, Help',
    Feature.MENU_DOWNGRADE_SUBMENU: 'Downgrade submenu: the older versions of the selected package',
    Feature.MENU_HAMBURGER: "The header bar's main menu, hidden while the menu bar is shown",
    Feature.MENU_ICONS: 'Icons in menus',
    Feature.MENU_PACKAGE: 'Package menu: the actions of the selected row',
    Feature.MENU_SIDEBAR: "Sidebar context menu: the entry's actions",
    Feature.RELEASE_BUTTON: 'The Fedora N button: a new release is out',
    Feature.RELEASE_DIALOG: 'Fedora N dialog: check for COPR builds, log, cancel, release notes, guide, open the upgrade tool',
    Feature.RELEASE_WATCH: 'Watch Fedora Releases: asks Bodhi on Reload',
    Feature.SEARCH_BAR: 'The search field with its mode, in the header bar',
    Feature.SEARCH_FILTER_WHILE_TYPING: 'The list filters while the search text is typed; the field says so',
    Feature.SEARCH_MODES: 'Search modes: Name, Name + summary, Description, Provides, File',
    Feature.SETTINGS_MENU_BAR: "The 'Show Menu Bar' setting: the menu bar instead of the header menu",
    Feature.SETTINGS_REGISTRY: 'Settings come from one registry: a new setting shows up in both front ends',
    Feature.SETTINGS_STATUS_CLICK: 'The setting: clicking the status icon marks the likely action',
    Feature.SETTINGS_TOOLBAR_STYLE: "Toolbar style (Qt's own setting)",
    Feature.SETTINGS_WATCH_RELEASES: 'The setting Watch Fedora Releases: the Fedora N button follows it',
    Feature.SIDEBAR_COUNTS: 'The counts beside each sidebar entry',
    Feature.SIDEBAR_CUSTOM_FILTER_EDIT: 'Double click a custom filter to edit it',
    Feature.SIDEBAR_CUSTOM_FILTER_MENU: 'Custom filter menu: only the actions that make sense for a custom filter',
    Feature.SIDEBAR_ENVIRONMENTS_TREE: 'Environments as a tree of their groups',
    Feature.SIDEBAR_GROUP_CHANGE: 'Groups are installed or removed at once from the sidebar',
    Feature.SIDEBAR_SECTION_ICONS: 'The section buttons (status, origin, groups, environments, search, custom) have icons',
    Feature.SIDEBAR_VIEWS: "The sidebar's sections: status, origin, groups, environments, search results, custom filters",
    Feature.SYSTEM_FILE_MANAGER: "Show in File Manager: reveals a file in the desktop's file manager",
    Feature.SYSTEM_POLKIT: 'Changes ask for authorization (polkit, through pkexec); the helper runs as root',
    Feature.SYSTEM_THEME_FOLLOWS_DESKTOP: 'Light and dark follow the desktop, in GNOME sessions',
    Feature.SYSTEM_WEB_LINKS: 'Web links open in the browser; only web addresses are followed',
    Feature.TRANSLATIONS_CATALOGS: 'Every string is translated in the 12 catalogs',
    Feature.WINDOW_CLOSE_PENDING: 'Closing the window asks about what is still running or pending',
    Feature.WINDOW_FRACTIONAL_SCALE: 'Sharp at 125 % and 150 %',
    Feature.WINDOW_HEADER_BUTTONS: 'Header: Reload, Apply, Mark upgrades, COPR, Repositories',
    Feature.WINDOW_KEYBOARD_ONLY: 'Everything reachable from the keyboard',
    Feature.WINDOW_PANES_SAVED: 'The window size and the pane dividers are saved',
    Feature.WINDOW_STATUS_BAR: "Status bar: the number of packages, the catalog's age, the warning link",
}


QT: dict[Feature, Entry] = {
    Feature.DETAILS_ADVISORIES_TAB: Entry(Support.SUPPORTED),
    Feature.DETAILS_BLOCKED_REASON: Entry(Support.SUPPORTED),
    Feature.DETAILS_CHANGELOG: Entry(Support.PARTIAL, 'not tested'),
    Feature.DETAILS_DESCRIPTION: Entry(Support.PARTIAL, 'not tested'),
    Feature.DETAILS_FILES_COPY_PATH: Entry(Support.SUPPORTED),
    Feature.DETAILS_FILES_FILTER: Entry(Support.SUPPORTED),
    Feature.DETAILS_FILES_LIST: Entry(Support.SUPPORTED),
    Feature.DETAILS_FILES_SHOW_IN_FM: Entry(Support.PARTIAL, 'not tested'),
    Feature.DETAILS_FILES_TREE: Entry(Support.SUPPORTED),
    Feature.DETAILS_LINKS: Entry(Support.PARTIAL, 'not tested'),
    Feature.DETAILS_REMEMBER_TAB: Entry(Support.PARTIAL, 'not tested'),
    Feature.DETAILS_TABS: Entry(Support.SUPPORTED),
    Feature.DETAILS_VERSIONS: Entry(Support.PARTIAL, 'the versions table has no test'),
    Feature.DIALOG_ABOUT_TOOLKIT: Entry(Support.SUPPORTED),
    Feature.DIALOG_APPLY: Entry(Support.SUPPORTED),
    Feature.DIALOG_APPLY_CANNOT_APPLY: Entry(Support.PARTIAL, 'the buttons are not tested'),
    Feature.DIALOG_APPLY_COMMAND: Entry(Support.SUPPORTED),
    Feature.DIALOG_APPLY_DOWNLOAD_ONLY: Entry(Support.SUPPORTED),
    Feature.DIALOG_APPLY_FREE_SPACE: Entry(Support.SUPPORTED),
    Feature.DIALOG_APPLY_RECOMMENDATIONS: Entry(Support.SUPPORTED),
    Feature.DIALOG_APPLY_SKIPPED: Entry(Support.SUPPORTED),
    Feature.DIALOG_CLEANUP: Entry(Support.SUPPORTED),
    Feature.DIALOG_CLEANUP_CACHES: Entry(Support.SUPPORTED),
    Feature.DIALOG_CLEANUP_COMPARE: Entry(Support.PARTIAL, 'no widget test'),
    Feature.DIALOG_CLEANUP_DELETE_UNUSED: Entry(Support.SUPPORTED),
    Feature.DIALOG_CLEANUP_LEFTOVERS: Entry(Support.SUPPORTED),
    Feature.DIALOG_CLEANUP_SEARCH_ALL: Entry(Support.SUPPORTED),
    Feature.DIALOG_COPR: Entry(Support.PARTIAL, 'projects and search logic in test_copr_flow.py; the dialog has no widget test'),
    Feature.DIALOG_COPR_ENABLE_FROM_SEARCH: Entry(Support.PARTIAL, 'the logic is in test_copr_flow.py; no widget test'),
    Feature.DIALOG_COPR_NO_BUILD_QUESTION: Entry(Support.SUPPORTED),
    Feature.DIALOG_COPR_PACKAGES: Entry(Support.PARTIAL, 'no widget test'),
    Feature.DIALOG_COPR_REMOVE_QUESTION: Entry(Support.SUPPORTED),
    Feature.DIALOG_CUSTOM_FILTERS: Entry(Support.SUPPORTED),
    Feature.DIALOG_CUSTOM_FILTERS_COUNT: Entry(Support.SUPPORTED),
    Feature.DIALOG_CUSTOM_FILTERS_MATCH: Entry(Support.PARTIAL, 'no widget test'),
    Feature.DIALOG_CUSTOM_FILTERS_NEW_FROM_VIEW: Entry(Support.SUPPORTED),
    Feature.DIALOG_HISTORY: Entry(Support.SUPPORTED),
    Feature.DIALOG_HISTORY_FILTER: Entry(Support.SUPPORTED),
    Feature.DIALOG_HISTORY_OPEN_PACKAGE: Entry(Support.PARTIAL, 'not tested'),
    Feature.DIALOG_HISTORY_UNDO: Entry(Support.SUPPORTED),
    Feature.DIALOG_INSTALL_FILE: Entry(Support.SUPPORTED),
    Feature.DIALOG_INSTALL_FILE_CHECK: Entry(Support.SUPPORTED),
    Feature.DIALOG_INSTALL_FILE_COMMAND: Entry(Support.SUPPORTED),
    Feature.DIALOG_INSTALL_FILE_RECOMMENDATIONS: Entry(Support.PARTIAL, 'no widget test'),
    Feature.DIALOG_NOTIFICATIONS: Entry(Support.SUPPORTED),
    Feature.DIALOG_NOTIFICATIONS_FEDORA_TIMER: Entry(Support.PARTIAL, 'the state is in test_notifier.py; the button is not tested'),
    Feature.DIALOG_NOTIFICATIONS_STALE_DAYS: Entry(Support.SUPPORTED),
    Feature.DIALOG_PROGRESS: Entry(Support.SUPPORTED),
    Feature.DIALOG_PROGRESS_AUTO_CLOSE: Entry(Support.PARTIAL, 'no widget test'),
    Feature.DIALOG_PROGRESS_CLOSE_LOCK: Entry(Support.PARTIAL, 'no widget test'),
    Feature.DIALOG_PROGRESS_KEY_QUESTION: Entry(Support.SUPPORTED),
    Feature.DIALOG_PROGRESS_LOG: Entry(Support.PARTIAL, 'no widget test'),
    Feature.DIALOG_REPOSITORIES: Entry(Support.SUPPORTED),
    Feature.DIALOG_REPOSITORIES_FILTER: Entry(Support.PARTIAL, 'no widget test'),
    Feature.DIALOG_REPOSITORIES_REMOVE: Entry(Support.SUPPORTED),
    Feature.DIALOG_REPOSITORIES_SHOW_AUX: Entry(Support.PARTIAL, 'no widget test'),
    Feature.DIALOG_WHATS_NEW: Entry(Support.SUPPORTED),
    Feature.ICON_NON_PIXELATED: Entry(Support.PARTIAL, 'drawn and rendered (test_icons_render), sharp at 125 % checked by hand (56b13fc)'),
    Feature.INSTALL_FILE_ARGUMENT: Entry(Support.PARTIAL, 'the entry point kram file.rpm is not tested'),
    Feature.INSTALL_FILE_DROP: Entry(Support.PARTIAL, 'dropping an .rpm on the window is not tested'),
    Feature.INSTALL_FILE_OPEN_MENU: Entry(Support.PARTIAL, 'not tested'),
    Feature.INSTANCE_ACTIVATION_TOKEN: Entry(Support.PARTIAL, 'not tested'),
    Feature.INSTANCE_TRAY: Entry(Support.SUPPORTED),
    Feature.LIST_COLUMNS: Entry(Support.SUPPORTED),
    Feature.LIST_CONTEXT_MENU: Entry(Support.PARTIAL, 'right-click menu of a row is not tested'),
    Feature.LIST_DOUBLE_CLICK_MARK: Entry(Support.PARTIAL, 'not tested'),
    Feature.LIST_EMPTY_EXPLANATION: Entry(Support.SUPPORTED),
    Feature.LIST_LOCK_PADLOCK: Entry(Support.SUPPORTED),
    Feature.LIST_MULTI_SELECT: Entry(Support.PARTIAL, 'not tested'),
    Feature.LIST_ROW_TINT: Entry(Support.PARTIAL, 'row tints are not tested'),
    Feature.LIST_SORT: Entry(Support.PARTIAL, "header sort is Qt's own; no test of the header"),
    Feature.LIST_VERSION_LOCK: Entry(Support.PARTIAL, "the logic is in test_versionlock.py; the menu items are not tested"),
    Feature.LIST_STATUS_CLICK: Entry(Support.SUPPORTED),
    Feature.MARKINGS_CSV_EXPORT: Entry(Support.SUPPORTED),
    Feature.MARKINGS_FILE: Entry(Support.SUPPORTED),
    Feature.MARK_APPLY_BUTTON: Entry(Support.SUPPORTED),
    Feature.MARK_INSTALL_REMOVE: Entry(Support.SUPPORTED),
    Feature.MARK_UNMARK_ALL: Entry(Support.SUPPORTED),
    Feature.MARK_UNMARK_ONE: Entry(Support.PARTIAL, 'not tested'),
    Feature.MARK_UNNEEDED: Entry(Support.SUPPORTED),
    Feature.MARK_UPGRADE_ALL: Entry(Support.SUPPORTED),
    Feature.MARK_UPGRADE_BY_ADVISORY: Entry(Support.SUPPORTED),
    Feature.MARK_UPGRADE_SPLIT_BUTTON: Entry(Support.PARTIAL, 'not tested'),
    Feature.MENU_ACCELERATORS: Entry(Support.PARTIAL, 'not tested'),
    Feature.MENU_BAR: Entry(Support.SUPPORTED),
    Feature.MENU_DOWNGRADE_SUBMENU: Entry(Support.SUPPORTED),
    Feature.MENU_HAMBURGER: Entry(Support.NOT_INTENDED, "the Qt front end has the menu bar only; the hamburger is GTK's (D12)"),
    Feature.MENU_ICONS: Entry(Support.PARTIAL, 'not tested'),
    Feature.MENU_PACKAGE: Entry(Support.PARTIAL, 'not tested'),
    Feature.MENU_SIDEBAR: Entry(Support.PARTIAL, 'not tested'),
    Feature.RELEASE_BUTTON: Entry(Support.SUPPORTED),
    Feature.RELEASE_DIALOG: Entry(Support.PARTIAL, 'not tested'),
    Feature.RELEASE_WATCH: Entry(Support.SUPPORTED),
    Feature.SEARCH_BAR: Entry(Support.PARTIAL, 'search logic in test_search_controller.py; the bar has no widget test'),
    Feature.SEARCH_FILTER_WHILE_TYPING: Entry(Support.PARTIAL, 'not tested'),
    Feature.SEARCH_MODES: Entry(Support.PARTIAL, 'the ranking is in test_search.py; the dropdown is not tested'),
    Feature.SETTINGS_MENU_BAR: Entry(Support.NOT_INTENDED, 'a GTK setting; the Qt front end always has the menu bar'),
    Feature.SETTINGS_REGISTRY: Entry(Support.SUPPORTED),
    Feature.SETTINGS_STATUS_CLICK: Entry(Support.SUPPORTED),
    Feature.SETTINGS_TOOLBAR_STYLE: Entry(Support.SUPPORTED),
    Feature.SETTINGS_WATCH_RELEASES: Entry(Support.SUPPORTED),
    Feature.SIDEBAR_COUNTS: Entry(Support.SUPPORTED),
    Feature.SIDEBAR_CUSTOM_FILTER_EDIT: Entry(Support.SUPPORTED),
    Feature.SIDEBAR_CUSTOM_FILTER_MENU: Entry(Support.SUPPORTED),
    Feature.SIDEBAR_ENVIRONMENTS_TREE: Entry(Support.SUPPORTED),
    Feature.SIDEBAR_GROUP_CHANGE: Entry(Support.SUPPORTED),
    Feature.SIDEBAR_SECTION_ICONS: Entry(Support.PARTIAL, 'the section buttons are text only; icons are not drawn in Qt'),
    Feature.SIDEBAR_VIEWS: Entry(Support.SUPPORTED),
    Feature.SYSTEM_FILE_MANAGER: Entry(Support.PARTIAL, 'not tested'),
    Feature.SYSTEM_POLKIT: Entry(Support.PARTIAL, "the helper's requests are tested; the prompt is not"),
    Feature.SYSTEM_THEME_FOLLOWS_DESKTOP: Entry(Support.SUPPORTED),
    Feature.SYSTEM_WEB_LINKS: Entry(Support.PARTIAL, 'not tested'),
    Feature.TRANSLATIONS_CATALOGS: Entry(Support.SUPPORTED),
    Feature.WINDOW_CLOSE_PENDING: Entry(Support.PARTIAL, 'not tested'),
    Feature.WINDOW_FRACTIONAL_SCALE: Entry(Support.PARTIAL, 'checked by hand'),
    Feature.WINDOW_HEADER_BUTTONS: Entry(Support.PARTIAL, 'not tested'),
    Feature.WINDOW_KEYBOARD_ONLY: Entry(Support.PARTIAL, 'not tested'),
    Feature.WINDOW_PANES_SAVED: Entry(Support.PARTIAL, 'not tested'),
    Feature.WINDOW_STATUS_BAR: Entry(Support.PARTIAL, 'not tested'),
}

GTK: dict[Feature, Entry] = {
    Feature.LIST_VERSION_LOCK: Entry(Support.PARTIAL, "the logic is in test_versionlock.py; the menu items are not tested"),
    Feature.DETAILS_ADVISORIES_TAB: Entry(Support.PARTIAL, 'not tested in GTK'),
    Feature.DETAILS_BLOCKED_REASON: Entry(Support.PARTIAL, 'not tested in GTK'),
    Feature.DETAILS_CHANGELOG: Entry(Support.PARTIAL, 'not tested'),
    Feature.DETAILS_DESCRIPTION: Entry(Support.PARTIAL, 'not tested'),
    Feature.DETAILS_FILES_COPY_PATH: Entry(Support.SUPPORTED),
    Feature.DETAILS_FILES_FILTER: Entry(Support.SUPPORTED),
    Feature.DETAILS_FILES_LIST: Entry(Support.SUPPORTED),
    Feature.DETAILS_FILES_SHOW_IN_FM: Entry(Support.PARTIAL, 'not tested'),
    Feature.DETAILS_FILES_TREE: Entry(Support.SUPPORTED),
    Feature.DETAILS_LINKS: Entry(Support.PARTIAL, 'not tested'),
    Feature.DETAILS_REMEMBER_TAB: Entry(Support.PARTIAL, 'not tested'),
    Feature.DETAILS_TABS: Entry(Support.PARTIAL, 'the tabs show the shared docs; no GTK test of the tabs'),
    Feature.DETAILS_VERSIONS: Entry(Support.SUPPORTED),
    Feature.DIALOG_ABOUT_TOOLKIT: Entry(Support.SUPPORTED),
    Feature.DIALOG_APPLY: Entry(Support.SUPPORTED),
    Feature.DIALOG_APPLY_CANNOT_APPLY: Entry(Support.PARTIAL, 'the buttons are not tested'),
    Feature.DIALOG_APPLY_COMMAND: Entry(Support.SUPPORTED),
    Feature.DIALOG_APPLY_DOWNLOAD_ONLY: Entry(Support.SUPPORTED),
    Feature.DIALOG_APPLY_FREE_SPACE: Entry(Support.PARTIAL, 'not tested in GTK'),
    Feature.DIALOG_APPLY_RECOMMENDATIONS: Entry(Support.SUPPORTED),
    Feature.DIALOG_APPLY_SKIPPED: Entry(Support.PARTIAL, 'not tested in GTK'),
    Feature.DIALOG_CLEANUP: Entry(Support.SUPPORTED),
    Feature.DIALOG_CLEANUP_CACHES: Entry(Support.SUPPORTED),
    Feature.DIALOG_CLEANUP_COMPARE: Entry(Support.PARTIAL, 'not tested'),
    Feature.DIALOG_CLEANUP_DELETE_UNUSED: Entry(Support.PARTIAL, 'not tested'),
    Feature.DIALOG_CLEANUP_LEFTOVERS: Entry(Support.SUPPORTED),
    Feature.DIALOG_CLEANUP_SEARCH_ALL: Entry(Support.PARTIAL, 'not tested'),
    Feature.DIALOG_COPR: Entry(Support.SUPPORTED),
    Feature.DIALOG_COPR_ENABLE_FROM_SEARCH: Entry(Support.SUPPORTED),
    Feature.DIALOG_COPR_NO_BUILD_QUESTION: Entry(Support.PARTIAL, 'not tested in GTK'),
    Feature.DIALOG_COPR_PACKAGES: Entry(Support.SUPPORTED),
    Feature.DIALOG_COPR_REMOVE_QUESTION: Entry(Support.PARTIAL, 'not tested in GTK'),
    Feature.DIALOG_CUSTOM_FILTERS: Entry(Support.SUPPORTED),
    Feature.DIALOG_CUSTOM_FILTERS_COUNT: Entry(Support.SUPPORTED),
    Feature.DIALOG_CUSTOM_FILTERS_MATCH: Entry(Support.PARTIAL, 'not tested'),
    Feature.DIALOG_CUSTOM_FILTERS_NEW_FROM_VIEW: Entry(Support.PARTIAL, 'not tested'),
    Feature.DIALOG_HISTORY: Entry(Support.SUPPORTED),
    Feature.DIALOG_HISTORY_FILTER: Entry(Support.SUPPORTED),
    Feature.DIALOG_HISTORY_OPEN_PACKAGE: Entry(Support.PARTIAL, 'not tested'),
    Feature.DIALOG_HISTORY_UNDO: Entry(Support.SUPPORTED),
    Feature.DIALOG_INSTALL_FILE: Entry(Support.SUPPORTED),
    Feature.DIALOG_INSTALL_FILE_CHECK: Entry(Support.PARTIAL, 'not tested in GTK'),
    Feature.DIALOG_INSTALL_FILE_COMMAND: Entry(Support.SUPPORTED),
    Feature.DIALOG_INSTALL_FILE_RECOMMENDATIONS: Entry(Support.PARTIAL, 'not tested'),
    Feature.DIALOG_NOTIFICATIONS: Entry(Support.SUPPORTED),
    Feature.DIALOG_NOTIFICATIONS_FEDORA_TIMER: Entry(Support.PARTIAL, 'not tested'),
    Feature.DIALOG_NOTIFICATIONS_STALE_DAYS: Entry(Support.PARTIAL, 'not tested'),
    Feature.DIALOG_PROGRESS: Entry(Support.SUPPORTED),
    Feature.DIALOG_PROGRESS_AUTO_CLOSE: Entry(Support.SUPPORTED),
    Feature.DIALOG_PROGRESS_CLOSE_LOCK: Entry(Support.SUPPORTED),
    Feature.DIALOG_PROGRESS_KEY_QUESTION: Entry(Support.PARTIAL, 'not tested in GTK'),
    Feature.DIALOG_PROGRESS_LOG: Entry(Support.SUPPORTED),
    Feature.DIALOG_REPOSITORIES: Entry(Support.SUPPORTED),
    Feature.DIALOG_REPOSITORIES_FILTER: Entry(Support.SUPPORTED),
    Feature.DIALOG_REPOSITORIES_REMOVE: Entry(Support.PARTIAL, 'not tested in GTK'),
    Feature.DIALOG_REPOSITORIES_SHOW_AUX: Entry(Support.SUPPORTED),
    Feature.DIALOG_WHATS_NEW: Entry(Support.SUPPORTED),
    Feature.ICON_NON_PIXELATED: Entry(Support.SUPPORTED),
    Feature.INSTALL_FILE_ARGUMENT: Entry(Support.PARTIAL, 'only the argument parsing is tested; the installer runs by hand'),
    Feature.INSTALL_FILE_DROP: Entry(Support.SUPPORTED),
    Feature.INSTALL_FILE_OPEN_MENU: Entry(Support.PARTIAL, 'not tested'),
    Feature.INSTANCE_ACTIVATION_TOKEN: Entry(Support.PARTIAL, 'checked by hand (S9)'),
    Feature.INSTANCE_TRAY: Entry(Support.PARTIAL, 'checked by hand (S9); the Activate interface is not tested'),
    Feature.LIST_COLUMNS: Entry(Support.SUPPORTED),
    Feature.LIST_CONTEXT_MENU: Entry(Support.SUPPORTED),
    Feature.LIST_DOUBLE_CLICK_MARK: Entry(Support.SUPPORTED),
    Feature.LIST_EMPTY_EXPLANATION: Entry(Support.PARTIAL, 'not tested'),
    Feature.LIST_LOCK_PADLOCK: Entry(Support.PARTIAL, 'not tested'),
    Feature.LIST_MULTI_SELECT: Entry(Support.SUPPORTED),
    Feature.LIST_ROW_TINT: Entry(Support.SUPPORTED),
    Feature.LIST_SORT: Entry(Support.SUPPORTED),
    Feature.LIST_STATUS_CLICK: Entry(Support.SUPPORTED),
    Feature.MARKINGS_CSV_EXPORT: Entry(Support.PARTIAL, 'wired to the shared Browser flow; not tested in GTK'),
    Feature.MARKINGS_FILE: Entry(Support.PARTIAL, 'wired to the shared Browser flow; not tested in GTK'),
    Feature.MARK_APPLY_BUTTON: Entry(Support.PARTIAL, 'not tested'),
    Feature.MARK_INSTALL_REMOVE: Entry(Support.SUPPORTED),
    Feature.MARK_UNMARK_ALL: Entry(Support.PARTIAL, 'not tested'),
    Feature.MARK_UNMARK_ONE: Entry(Support.PARTIAL, 'not tested'),
    Feature.MARK_UNNEEDED: Entry(Support.PARTIAL, 'not tested'),
    Feature.MARK_UPGRADE_ALL: Entry(Support.PARTIAL, 'not tested'),
    Feature.MARK_UPGRADE_BY_ADVISORY: Entry(Support.PARTIAL, 'not tested'),
    Feature.MARK_UPGRADE_SPLIT_BUTTON: Entry(Support.PARTIAL, 'not tested'),
    Feature.MENU_ACCELERATORS: Entry(Support.SUPPORTED),
    Feature.MENU_BAR: Entry(Support.SUPPORTED),
    Feature.MENU_DOWNGRADE_SUBMENU: Entry(Support.PARTIAL, 'not tested'),
    Feature.MENU_HAMBURGER: Entry(Support.SUPPORTED),
    Feature.MENU_ICONS: Entry(Support.NOT_INTENDED, 'GTK popover menus show no icons for ordinary items'),
    Feature.MENU_PACKAGE: Entry(Support.PARTIAL, 'not tested'),
    Feature.MENU_SIDEBAR: Entry(Support.PARTIAL, 'not tested'),
    Feature.RELEASE_BUTTON: Entry(Support.SUPPORTED),
    Feature.RELEASE_DIALOG: Entry(Support.SUPPORTED),
    Feature.RELEASE_WATCH: Entry(Support.SUPPORTED),
    Feature.SEARCH_BAR: Entry(Support.SUPPORTED),
    Feature.SEARCH_FILTER_WHILE_TYPING: Entry(Support.PARTIAL, 'not tested'),
    Feature.SEARCH_MODES: Entry(Support.PARTIAL, 'not tested'),
    Feature.SETTINGS_MENU_BAR: Entry(Support.SUPPORTED),
    Feature.SETTINGS_REGISTRY: Entry(Support.SUPPORTED),
    Feature.SETTINGS_STATUS_CLICK: Entry(Support.PARTIAL, 'not tested'),
    Feature.SETTINGS_TOOLBAR_STYLE: Entry(Support.NOT_INTENDED, "Qt's toolbar style; GTK has no toolbar styles"),
    Feature.SETTINGS_WATCH_RELEASES: Entry(Support.SUPPORTED),
    Feature.SIDEBAR_COUNTS: Entry(Support.PARTIAL, 'not tested'),
    Feature.SIDEBAR_CUSTOM_FILTER_EDIT: Entry(Support.PARTIAL, 'not tested'),
    Feature.SIDEBAR_CUSTOM_FILTER_MENU: Entry(Support.PARTIAL, 'not tested'),
    Feature.SIDEBAR_ENVIRONMENTS_TREE: Entry(Support.PARTIAL, 'not tested'),
    Feature.SIDEBAR_GROUP_CHANGE: Entry(Support.PARTIAL, 'not tested'),
    Feature.SIDEBAR_SECTION_ICONS: Entry(Support.SUPPORTED),
    Feature.SIDEBAR_VIEWS: Entry(Support.SUPPORTED),
    Feature.SYSTEM_FILE_MANAGER: Entry(Support.PARTIAL, 'not tested'),
    Feature.SYSTEM_POLKIT: Entry(Support.PARTIAL, "the helper's requests are tested; the prompt is not"),
    Feature.SYSTEM_THEME_FOLLOWS_DESKTOP: Entry(Support.NOT_INTENDED, "libadwaita follows the desktop's style and colour scheme"),
    Feature.SYSTEM_WEB_LINKS: Entry(Support.PARTIAL, 'not tested'),
    Feature.TRANSLATIONS_CATALOGS: Entry(Support.SUPPORTED),
    Feature.WINDOW_CLOSE_PENDING: Entry(Support.PARTIAL, 'not tested'),
    Feature.WINDOW_FRACTIONAL_SCALE: Entry(Support.PARTIAL, 'checked by hand: pixelation at 125 % fixed with vector icons; the user confirms'),
    Feature.WINDOW_HEADER_BUTTONS: Entry(Support.PARTIAL, 'not tested'),
    Feature.WINDOW_KEYBOARD_ONLY: Entry(Support.PARTIAL, 'not tested'),
    Feature.WINDOW_PANES_SAVED: Entry(Support.PARTIAL, 'not tested'),
    Feature.WINDOW_STATUS_BAR: Entry(Support.SUPPORTED),
}

# the terminal front end, in development: PLANNED until built; see docs/PARITY.md
TUI: dict[Feature, Entry] = {
    Feature.LIST_VERSION_LOCK: Entry(Support.PLANNED),
    Feature.DETAILS_ADVISORIES_TAB: Entry(Support.PLANNED),
    Feature.DETAILS_BLOCKED_REASON: Entry(Support.PLANNED),
    Feature.DETAILS_CHANGELOG: Entry(Support.PLANNED),
    Feature.DETAILS_DESCRIPTION: Entry(Support.PLANNED),
    Feature.DETAILS_FILES_COPY_PATH: Entry(Support.PLANNED),
    Feature.DETAILS_FILES_FILTER: Entry(Support.PLANNED),
    Feature.DETAILS_FILES_LIST: Entry(Support.PLANNED),
    Feature.DETAILS_FILES_SHOW_IN_FM: Entry(Support.PLANNED),
    Feature.DETAILS_FILES_TREE: Entry(Support.PLANNED),
    Feature.DETAILS_LINKS: Entry(Support.PLANNED),
    Feature.DETAILS_REMEMBER_TAB: Entry(Support.PLANNED),
    Feature.DETAILS_TABS: Entry(Support.PLANNED),
    Feature.DETAILS_VERSIONS: Entry(Support.PLANNED),
    Feature.DIALOG_ABOUT_TOOLKIT: Entry(Support.PLANNED),
    Feature.DIALOG_APPLY: Entry(Support.PLANNED),
    Feature.DIALOG_APPLY_CANNOT_APPLY: Entry(Support.PLANNED),
    Feature.DIALOG_APPLY_COMMAND: Entry(Support.PLANNED),
    Feature.DIALOG_APPLY_DOWNLOAD_ONLY: Entry(Support.PLANNED),
    Feature.DIALOG_APPLY_FREE_SPACE: Entry(Support.PLANNED),
    Feature.DIALOG_APPLY_RECOMMENDATIONS: Entry(Support.PLANNED),
    Feature.DIALOG_APPLY_SKIPPED: Entry(Support.PLANNED),
    Feature.DIALOG_CLEANUP: Entry(Support.PLANNED),
    Feature.DIALOG_CLEANUP_CACHES: Entry(Support.PLANNED),
    Feature.DIALOG_CLEANUP_COMPARE: Entry(Support.PLANNED),
    Feature.DIALOG_CLEANUP_DELETE_UNUSED: Entry(Support.PLANNED),
    Feature.DIALOG_CLEANUP_LEFTOVERS: Entry(Support.PLANNED),
    Feature.DIALOG_CLEANUP_SEARCH_ALL: Entry(Support.PLANNED),
    Feature.DIALOG_COPR: Entry(Support.PLANNED),
    Feature.DIALOG_COPR_ENABLE_FROM_SEARCH: Entry(Support.PLANNED),
    Feature.DIALOG_COPR_NO_BUILD_QUESTION: Entry(Support.PLANNED),
    Feature.DIALOG_COPR_PACKAGES: Entry(Support.PLANNED),
    Feature.DIALOG_COPR_REMOVE_QUESTION: Entry(Support.PLANNED),
    Feature.DIALOG_CUSTOM_FILTERS: Entry(Support.PLANNED),
    Feature.DIALOG_CUSTOM_FILTERS_COUNT: Entry(Support.PLANNED),
    Feature.DIALOG_CUSTOM_FILTERS_MATCH: Entry(Support.PLANNED),
    Feature.DIALOG_CUSTOM_FILTERS_NEW_FROM_VIEW: Entry(Support.PLANNED),
    Feature.DIALOG_HISTORY: Entry(Support.PLANNED),
    Feature.DIALOG_HISTORY_FILTER: Entry(Support.PLANNED),
    Feature.DIALOG_HISTORY_OPEN_PACKAGE: Entry(Support.PLANNED),
    Feature.DIALOG_HISTORY_UNDO: Entry(Support.PLANNED),
    Feature.DIALOG_INSTALL_FILE: Entry(Support.PLANNED),
    Feature.DIALOG_INSTALL_FILE_CHECK: Entry(Support.PLANNED),
    Feature.DIALOG_INSTALL_FILE_COMMAND: Entry(Support.PLANNED),
    Feature.DIALOG_INSTALL_FILE_RECOMMENDATIONS: Entry(Support.PLANNED),
    Feature.DIALOG_NOTIFICATIONS: Entry(Support.PLANNED),
    Feature.DIALOG_NOTIFICATIONS_FEDORA_TIMER: Entry(Support.PLANNED),
    Feature.DIALOG_NOTIFICATIONS_STALE_DAYS: Entry(Support.PLANNED),
    Feature.DIALOG_PROGRESS: Entry(Support.PLANNED),
    Feature.DIALOG_PROGRESS_AUTO_CLOSE: Entry(Support.PLANNED),
    Feature.DIALOG_PROGRESS_CLOSE_LOCK: Entry(Support.PLANNED),
    Feature.DIALOG_PROGRESS_KEY_QUESTION: Entry(Support.PLANNED),
    Feature.DIALOG_PROGRESS_LOG: Entry(Support.PLANNED),
    Feature.DIALOG_REPOSITORIES: Entry(Support.PLANNED),
    Feature.DIALOG_REPOSITORIES_FILTER: Entry(Support.PLANNED),
    Feature.DIALOG_REPOSITORIES_REMOVE: Entry(Support.PLANNED),
    Feature.DIALOG_REPOSITORIES_SHOW_AUX: Entry(Support.PLANNED),
    Feature.DIALOG_WHATS_NEW: Entry(Support.PLANNED),
    Feature.ICON_NON_PIXELATED: Entry(Support.NOT_INTENDED, 'a terminal draws no painted icons'),
    Feature.INSTALL_FILE_ARGUMENT: Entry(Support.PLANNED),
    Feature.INSTALL_FILE_DROP: Entry(Support.PLANNED),
    Feature.INSTALL_FILE_OPEN_MENU: Entry(Support.PLANNED),
    Feature.INSTANCE_ACTIVATION_TOKEN: Entry(Support.PLANNED),
    Feature.INSTANCE_TRAY: Entry(Support.PLANNED),
    Feature.LIST_COLUMNS: Entry(Support.PLANNED),
    Feature.LIST_CONTEXT_MENU: Entry(Support.PLANNED),
    Feature.LIST_DOUBLE_CLICK_MARK: Entry(Support.PLANNED),
    Feature.LIST_EMPTY_EXPLANATION: Entry(Support.PLANNED),
    Feature.LIST_LOCK_PADLOCK: Entry(Support.PLANNED),
    Feature.LIST_MULTI_SELECT: Entry(Support.PLANNED),
    Feature.LIST_ROW_TINT: Entry(Support.PLANNED),
    Feature.LIST_SORT: Entry(Support.PLANNED),
    Feature.LIST_STATUS_CLICK: Entry(Support.PLANNED),
    Feature.MARKINGS_CSV_EXPORT: Entry(Support.PLANNED),
    Feature.MARKINGS_FILE: Entry(Support.PLANNED),
    Feature.MARK_APPLY_BUTTON: Entry(Support.PLANNED),
    Feature.MARK_INSTALL_REMOVE: Entry(Support.PLANNED),
    Feature.MARK_UNMARK_ALL: Entry(Support.PLANNED),
    Feature.MARK_UNMARK_ONE: Entry(Support.PLANNED),
    Feature.MARK_UNNEEDED: Entry(Support.PLANNED),
    Feature.MARK_UPGRADE_ALL: Entry(Support.PLANNED),
    Feature.MARK_UPGRADE_BY_ADVISORY: Entry(Support.PLANNED),
    Feature.MARK_UPGRADE_SPLIT_BUTTON: Entry(Support.PLANNED),
    Feature.MENU_ACCELERATORS: Entry(Support.PLANNED),
    Feature.MENU_BAR: Entry(Support.PLANNED),
    Feature.MENU_DOWNGRADE_SUBMENU: Entry(Support.PLANNED),
    Feature.MENU_HAMBURGER: Entry(Support.NOT_INTENDED, 'the hamburger is a GTK header bar button'),
    Feature.MENU_ICONS: Entry(Support.NOT_INTENDED, 'a terminal menu has no icons'),
    Feature.MENU_PACKAGE: Entry(Support.PLANNED),
    Feature.MENU_SIDEBAR: Entry(Support.PLANNED),
    Feature.RELEASE_BUTTON: Entry(Support.PLANNED),
    Feature.RELEASE_DIALOG: Entry(Support.PLANNED),
    Feature.RELEASE_WATCH: Entry(Support.PLANNED),
    Feature.SEARCH_BAR: Entry(Support.PLANNED),
    Feature.SEARCH_FILTER_WHILE_TYPING: Entry(Support.PLANNED),
    Feature.SEARCH_MODES: Entry(Support.PLANNED),
    Feature.SETTINGS_MENU_BAR: Entry(Support.NOT_INTENDED, "the menu bar setting is GTK's"),
    Feature.SETTINGS_REGISTRY: Entry(Support.PLANNED),
    Feature.SETTINGS_STATUS_CLICK: Entry(Support.PLANNED),
    Feature.SETTINGS_TOOLBAR_STYLE: Entry(Support.NOT_INTENDED, "Qt's toolbar style"),
    Feature.SETTINGS_WATCH_RELEASES: Entry(Support.PLANNED),
    Feature.SIDEBAR_COUNTS: Entry(Support.PLANNED),
    Feature.SIDEBAR_CUSTOM_FILTER_EDIT: Entry(Support.PLANNED),
    Feature.SIDEBAR_CUSTOM_FILTER_MENU: Entry(Support.PLANNED),
    Feature.SIDEBAR_ENVIRONMENTS_TREE: Entry(Support.PLANNED),
    Feature.SIDEBAR_GROUP_CHANGE: Entry(Support.PLANNED),
    Feature.SIDEBAR_SECTION_ICONS: Entry(Support.NOT_INTENDED, 'a terminal draws no icons on its section buttons'),
    Feature.SIDEBAR_VIEWS: Entry(Support.PLANNED),
    Feature.SYSTEM_FILE_MANAGER: Entry(Support.PLANNED),
    Feature.SYSTEM_POLKIT: Entry(Support.PLANNED),
    Feature.SYSTEM_THEME_FOLLOWS_DESKTOP: Entry(Support.NOT_INTENDED, 'a terminal takes its colours from the terminal emulator'),
    Feature.SYSTEM_WEB_LINKS: Entry(Support.PLANNED),
    Feature.TRANSLATIONS_CATALOGS: Entry(Support.PLANNED),
    Feature.WINDOW_CLOSE_PENDING: Entry(Support.PLANNED),
    Feature.WINDOW_FRACTIONAL_SCALE: Entry(Support.NOT_INTENDED, 'a terminal has no screen scale'),
    Feature.WINDOW_HEADER_BUTTONS: Entry(Support.PLANNED),
    Feature.WINDOW_KEYBOARD_ONLY: Entry(Support.PLANNED),
    Feature.WINDOW_PANES_SAVED: Entry(Support.PLANNED),
    Feature.WINDOW_STATUS_BAR: Entry(Support.PLANNED),
}

# the front ends that are released: any PLANNED or NOT_IMPLEMENTED entry in them fails the test run
FRONTS_RELEASED: frozenset[str] = frozenset({"qt", "gtk"})

FRONTS: dict[str, dict[Feature, Entry]] = {"qt": QT, "gtk": GTK, "tui": TUI}


# Every action of the main window (kram.app.actions.action_defs) and every setting of the registry
# (kram.app.preferences) names the feature it belongs to. A new one without an entry fails tests/test_parity.py.
ACTION_FEATURES: dict[str, Feature] = {
    "about": Feature.DIALOG_ABOUT_TOOLKIT,
    "apply": Feature.MARK_APPLY_BUTTON,
    "back": Feature.DETAILS_LINKS,
    "cache": Feature.DIALOG_CLEANUP,
    "copr": Feature.DIALOG_COPR,
    "copy_name": Feature.MENU_PACKAGE,
    "copy_nevra": Feature.MENU_PACKAGE,
    "export_csv": Feature.MARKINGS_CSV_EXPORT,
    "filters": Feature.DIALOG_CUSTOM_FILTERS,
    "find": Feature.SEARCH_BAR,
    "history": Feature.DIALOG_HISTORY,
    "lock": Feature.LIST_VERSION_LOCK,
    "mark.install": Feature.MARK_INSTALL_REMOVE,
    "mark.mark_dep": Feature.MENU_PACKAGE,
    "mark.mark_user": Feature.MENU_PACKAGE,
    "mark.reinstall": Feature.MENU_PACKAGE,
    "mark.remove": Feature.MARK_INSTALL_REMOVE,
    "mark.upgrade": Feature.MARK_UPGRADE_ALL,
    "mark_unneeded": Feature.MARK_UNNEEDED,
    "mark_upgrades": Feature.MARK_UPGRADE_ALL,
    "mark_upgrades.fixes": Feature.MARK_UPGRADE_BY_ADVISORY,
    "mark_upgrades.security": Feature.MARK_UPGRADE_BY_ADVISORY,
    "mark_upgrades.security_high": Feature.MARK_UPGRADE_BY_ADVISORY,
    "new_filter": Feature.DIALOG_CUSTOM_FILTERS_NEW_FROM_VIEW,
    "notifications": Feature.DIALOG_NOTIFICATIONS,
    "open_file": Feature.INSTALL_FILE_OPEN_MENU,
    "properties": Feature.DETAILS_TABS,
    "quit": Feature.MENU_BAR,
    "read_marks": Feature.MARKINGS_FILE,
    "reload": Feature.WINDOW_HEADER_BUTTONS,
    "reload_cache": Feature.MENU_BAR,
    "repos": Feature.DIALOG_REPOSITORIES,
    "save_marks": Feature.MARKINGS_FILE,
    "show_in_history": Feature.DIALOG_HISTORY,
    "unlock": Feature.LIST_VERSION_LOCK,
    "unmark": Feature.MARK_UNMARK_ONE,
    "unmark_all": Feature.MARK_UNMARK_ALL,
    "why_blocked": Feature.DETAILS_BLOCKED_REASON,
}

SETTING_FEATURES: dict[str, Feature] = {
    "gtk/menubar": Feature.SETTINGS_MENU_BAR,
    "distro/watch": Feature.SETTINGS_WATCH_RELEASES,
    "table/status_click": Feature.SETTINGS_STATUS_CLICK,
    "toolbar/style": Feature.SETTINGS_TOOLBAR_STYLE,
    "update_checker/stale_days": Feature.DIALOG_NOTIFICATIONS_STALE_DAYS,
}
