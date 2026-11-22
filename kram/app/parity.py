"""Feature parity between the front ends: every feature Kram has, and how each front end supports it.

A feature is added here when it is built, and both tables must list it (tests/test_parity.py). A SUPPORTED entry
must be proved by a test marked `@pytest.mark.feature(Feature.X, front="qt" | "gtk")`: the test run checks that
the marked tests exist. NOT_IMPLEMENTED fails the run. PARTIAL and NOT_INTENDED need a note.

No toolkit is imported here: the tables are plain data, so the toolkit-free layer can hold them.
"""
from enum import Enum


class Feature(Enum):
    NON_PIXELATED_ICONS = "non_pixelated_icons"
    PACKAGE_LIST_SORT = "package_list_sort"
    PACKAGE_LIST_COLUMNS = "package_list_columns"
    ROW_MARKS_TINT = "row_marks_tint"
    PACKAGE_CONTEXT_MENU = "package_context_menu"
    STATUS_CLICK_MARKS_LIKELY = "status_click_marks_likely"
    SEARCH_BAR = "search_bar"
    SIDEBAR_VIEWS = "sidebar_views"
    DETAILS_TABS = "details_tabs"
    MENU_BAR = "menu_bar"
    HAMBURGER_MENU = "hamburger_menu"
    SETTINGS_FROM_REGISTRY = "settings_from_registry"
    APPLY_REVIEW = "apply_review"
    PROGRESS_DIALOG = "progress_dialog"
    UPDATE_NOTIFICATIONS = "update_notifications"
    CLEANUP_DIALOG = "cleanup_dialog"
    REPOSITORIES_DIALOG = "repositories_dialog"
    COPR_DIALOG = "copr_dialog"
    CUSTOM_FILTERS_DIALOG = "custom_filters_dialog"
    HISTORY_WINDOW = "history_window"
    INSTALL_FILE_DIALOG = "install_file_dialog"
    KRAM_FILE_RPM = "kram_file_rpm"
    DROP_RPM = "drop_rpm"
    FEDORA_UPGRADE_BUTTON = "fedora_upgrade_button"
    WHATS_NEW = "whats_new"
    ABOUT_TOOLKIT = "about_toolkit"
    RELEASE_WATCH = "release_watch"
    CSV_EXPORT = "csv_export"
    MARKINGS_FILES = "markings_files"
    SINGLE_INSTANCE_TRAY = "single_instance_tray"
    THEME_FOLLOWS_DESKTOP = "theme_follows_desktop"
    TOOLBAR_STYLE = "toolbar_style"
    FILES_TAB_TREE = "files_tab_tree"
    VERSIONS_TAB = "versions_tab"


class Support(Enum):
    NOT_IMPLEMENTED = "not_implemented"  # breaks parity: the test run fails
    SUPPORTED = "supported"              # proved by marked tests
    PARTIAL = "partial"                  # works, but not all of it is proved; the note says what
    NOT_INTENDED = "not_intended"        # deliberately absent or different; the note says why


class Entry:
    __slots__ = ("support", "note")

    def __init__(self, support: Support, note: str = ""):
        self.support, self.note = support, note


S = Support.SUPPORTED


def _s() -> Entry:
    return Entry(S)


def _p(note: str) -> Entry:
    return Entry(Support.PARTIAL, note)


def _n(note: str) -> Entry:
    return Entry(Support.NOT_INTENDED, note)


QT: dict[Feature, Entry] = {
    Feature.NON_PIXELATED_ICONS: _p("drawn and rendered (test_icons_render), sharp at 125 % checked by hand (56b13fc)"),
    Feature.PACKAGE_LIST_SORT: _p("header sort is Qt's own; no test of the header"),
    Feature.PACKAGE_LIST_COLUMNS: _s(),
    Feature.ROW_MARKS_TINT: _p("row tints are not tested"),
    Feature.PACKAGE_CONTEXT_MENU: _p("right-click menu of a row is not tested"),
    Feature.STATUS_CLICK_MARKS_LIKELY: _s(),
    Feature.SEARCH_BAR: _p("search logic in test_search_controller.py; the bar has no widget test"),
    Feature.SIDEBAR_VIEWS: _s(),
    Feature.DETAILS_TABS: _s(),
    Feature.MENU_BAR: _s(),
    Feature.HAMBURGER_MENU: _n("the Qt front end has the menu bar only; the hamburger is GTK's (D12)"),
    Feature.SETTINGS_FROM_REGISTRY: _s(),
    Feature.APPLY_REVIEW: _s(),
    Feature.PROGRESS_DIALOG: _s(),
    Feature.UPDATE_NOTIFICATIONS: _s(),
    Feature.CLEANUP_DIALOG: _s(),
    Feature.REPOSITORIES_DIALOG: _s(),
    Feature.COPR_DIALOG: _p("projects and search logic in test_copr_flow.py; the dialog has no widget test"),
    Feature.CUSTOM_FILTERS_DIALOG: _s(),
    Feature.HISTORY_WINDOW: _s(),
    Feature.INSTALL_FILE_DIALOG: _s(),
    Feature.KRAM_FILE_RPM: _p("the entry point kram file.rpm is not tested"),
    Feature.DROP_RPM: _p("dropping an .rpm on the window is not tested"),
    Feature.FEDORA_UPGRADE_BUTTON: _s(),
    Feature.WHATS_NEW: _s(),
    Feature.ABOUT_TOOLKIT: _s(),
    Feature.RELEASE_WATCH: _s(),
    Feature.CSV_EXPORT: _s(),
    Feature.MARKINGS_FILES: _s(),
    Feature.SINGLE_INSTANCE_TRAY: _s(),
    Feature.THEME_FOLLOWS_DESKTOP: _s(),
    Feature.TOOLBAR_STYLE: _s(),
    Feature.FILES_TAB_TREE: _s(),
    Feature.VERSIONS_TAB: _p("the versions table has no test"),
}

GTK: dict[Feature, Entry] = {
    Feature.NON_PIXELATED_ICONS: _s(),
    Feature.PACKAGE_LIST_SORT: _s(),
    Feature.PACKAGE_LIST_COLUMNS: _s(),
    Feature.ROW_MARKS_TINT: _s(),
    Feature.PACKAGE_CONTEXT_MENU: _p("right-click menu of a row is not tested"),
    Feature.STATUS_CLICK_MARKS_LIKELY: _p("implemented, not tested"),
    Feature.SEARCH_BAR: _p("search logic in test_search_controller.py; the bar has no widget test"),
    Feature.SIDEBAR_VIEWS: _s(),
    Feature.DETAILS_TABS: _p("the tabs show the shared docs; no GTK test of the tabs"),
    Feature.MENU_BAR: _s(),
    Feature.HAMBURGER_MENU: _s(),
    Feature.SETTINGS_FROM_REGISTRY: _s(),
    Feature.APPLY_REVIEW: _s(),
    Feature.PROGRESS_DIALOG: _s(),
    Feature.UPDATE_NOTIFICATIONS: _s(),
    Feature.CLEANUP_DIALOG: _s(),
    Feature.REPOSITORIES_DIALOG: _s(),
    Feature.COPR_DIALOG: _s(),
    Feature.CUSTOM_FILTERS_DIALOG: _s(),
    Feature.HISTORY_WINDOW: _s(),
    Feature.INSTALL_FILE_DIALOG: _s(),
    Feature.KRAM_FILE_RPM: _p("only the argument parsing is tested; the installer runs by hand"),
    Feature.DROP_RPM: _p("dropping an .rpm on the window is not tested"),
    Feature.FEDORA_UPGRADE_BUTTON: _s(),
    Feature.WHATS_NEW: _s(),
    Feature.ABOUT_TOOLKIT: _s(),
    Feature.RELEASE_WATCH: _s(),
    Feature.CSV_EXPORT: _p("wired to the shared Browser flow; not tested in GTK"),
    Feature.MARKINGS_FILES: _p("wired to the shared Browser flow; not tested in GTK"),
    Feature.SINGLE_INSTANCE_TRAY: _p("checked by hand (S9); the Activate interface is not tested"),
    Feature.THEME_FOLLOWS_DESKTOP: _n("libadwaita follows the desktop's style and colour scheme"),
    Feature.TOOLBAR_STYLE: _n("Qt's toolbar style; GTK has no toolbar styles"),
    Feature.FILES_TAB_TREE: _s(),
    Feature.VERSIONS_TAB: _p("the versions table has no test"),
}

FRONTS: dict[str, dict[Feature, Entry]] = {"qt": QT, "gtk": GTK}
