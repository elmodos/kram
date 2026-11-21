"""Bottom detail tabs for the selected package. What each tab says is kram.app.details; this shows it."""
from urllib.parse import unquote

from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem

from ..app.columns import blocked_tip, shown_advisories
from ..app.details import (
    MAX_DEP_ITEMS,
    TabChoice,
    advisories_doc,
    advisories_tab_icon,
    advisories_tab_tip,
    blocked_doc,
    changelog_doc,
    dependencies_doc,
    description_doc,
    general_doc,
    tab_titles,
    version_rows,
)
from ..app.doc import Doc
from ..core.model import PkgDetails, PkgRow
from ..i18n import _
from .doc_html import to_html
from .file_list import FileList
from .icons import blocked_icon, icon
from .links import open_web_link

__all__ = ["MAX_DEP_ITEMS", "DetailsTabs"]


def _browser() -> QTextBrowser:
    b = QTextBrowser()
    b.setOpenLinks(False)
    return b


class DetailsTabs(QTabWidget):
    # ("dep", requirement string) or ("pkg", "name.arch")
    linkActivated = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.desc = _browser()
        self.general = _browser()
        self.deps = _browser()
        self.deps.anchorClicked.connect(self._on_link)
        # an upgrade that cannot be installed: a cross on the tab and the resolver's message above the dependencies
        self._blocked = Doc()
        self._deps_body = Doc()
        self.general.anchorClicked.connect(self._on_link)
        self.files = FileList()
        self.versions = QTreeWidget()
        self.versions.setHeaderLabels([_("Version"), _("Repository"), _("State")])
        self.versions.setRootIsDecorated(False)
        self.versions.setColumnWidth(0, 260)
        self.versions.setColumnWidth(1, 360)
        self.changelog = _browser()
        # only there for an upgrade with advisories, with a dot in the colour of the most important one
        self.advisories = _browser()
        self.advisories.anchorClicked.connect(self._on_link)
        titles = tab_titles()
        widgets = {"description": self.desc, "general": self.general, "advisories": self.advisories,
                   "dependencies": self.deps, "files": self.files, "versions": self.versions,
                   "changelog": self.changelog}
        self._tabs = {name: (widget, titles[name]) for name, widget in widgets.items()}
        for widget, title in self._tabs.values():
            self.addTab(widget, title)
        self.setTabVisible(self.indexOf(self.advisories), False)
        self._choice = TabChoice()
        self._switching = False
        self.currentChanged.connect(self._on_current_changed)

    def _name_of(self, widget) -> str:
        return next(name for name, (w, _title) in self._tabs.items() if w is widget)

    def _on_current_changed(self, _index) -> None:
        if not self._switching:
            self._choice.user_selected(self._name_of(self.currentWidget()))

    def current_name(self) -> str:
        """The current tab, as saved in the settings: "general", "advisories"…"""
        return self._choice.saved_name(self._name_of(self.currentWidget()))

    def select_name(self, name: str) -> None:
        shown = self.isTabVisible(self.indexOf(self.advisories))
        if (name := self._choice.to_select(name, shown)) is not None:
            self.setCurrentWidget(self._tabs[name][0])

    def show_advisories(self, row: PkgRow | None) -> None:
        """Show or hide the advisories tab for the selected package; at once, without waiting for its details."""
        index = self.indexOf(self.advisories)
        self._switching = True
        try:
            if row is None or not shown_advisories(row):
                if self.currentIndex() == index:
                    self.setCurrentWidget(self._tabs[self._choice.instead_of_advisories()][0])
                self.setTabVisible(index, False)
                self.advisories.clear()
                return
            self.setTabIcon(index, icon(advisories_tab_icon(row)))
            self.setTabToolTip(index, advisories_tab_tip(row))
            self.advisories.setHtml(to_html(advisories_doc(row)))
            self.setTabVisible(index, True)
            if self._choice.wants_advisories:
                self.setCurrentIndex(index)
        finally:
            self._switching = False

    def show_blocked(self, reason: str | None) -> None:
        """Mark the dependencies tab when the selected upgrade cannot be installed now; at once, like the advisories.
        `reason` is None for an upgrade that can be installed; "" for a blocked one whose reason is not known (yet)."""
        index = self.indexOf(self.deps)
        blocked = reason is not None
        self.setTabIcon(index, blocked_icon() if blocked else QIcon())
        self.setTabToolTip(index, blocked_tip(reason) if blocked else "")
        self._blocked = blocked_doc(reason) if blocked else Doc()
        self._set_deps()

    def _set_deps(self) -> None:
        if self._blocked or self._deps_body:
            self.deps.setHtml(to_html(self._blocked + self._deps_body))
        else:
            self.deps.clear()

    def clear(self) -> None:
        for b in (self.desc, self.general, self.changelog):
            b.clear()
        self._deps_body = Doc()
        self.show_blocked(None)
        self.files.clear()
        self.versions.clear()
        self.show_advisories(None)

    def show_package(self, row: PkgRow, d: PkgDetails) -> None:
        self.desc.setHtml(to_html(description_doc(d)))
        self.general.setHtml(to_html(general_doc(row, d)))
        self._deps_body = dependencies_doc(d)
        self._set_deps()
        self.files.set_files(d.files, d.files_complete)
        self.versions.clear()
        for v in version_rows(d):
            item = QTreeWidgetItem([v.evr, v.repo, v.state])
            if v.bold:
                f = item.font(0)
                f.setBold(True)
                item.setFont(0, f)
            if v.dimmed:
                grey = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
                for column in range(3):
                    item.setForeground(column, grey)
            self.versions.addTopLevelItem(item)
        self.changelog.setHtml(to_html(changelog_doc(d)))

    def _on_link(self, url) -> None:
        s = url.toString()
        kind, _, value = s.partition(":")
        if kind in ("dep", "pkg"):
            self.linkActivated.emit(kind, unquote(value))
        elif kind in ("http", "https"):
            open_web_link(url)

