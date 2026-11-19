"""Bottom detail tabs for the selected package."""
import html
from datetime import datetime
from urllib.parse import quote, unquote

from PySide6.QtCore import Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem

from ..core.model import PkgDetails, PkgRow
from ..core.origin import display_repo
from ..i18n import _, pgettext
from .file_list import FileList
from .icons import ADVISORY_COLOR, ORIGIN_LABEL, advisory_icon, blocked_icon
from .package_model import ADVISORY_LABEL, blocked_tip, human_size

e = html.escape


def _date(ts: int | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"


def _browser() -> QTextBrowser:
    b = QTextBrowser()
    b.setOpenLinks(False)
    return b


def _reference(kind: str, ref_id: str) -> str:
    """A bug or CVE an advisory fixes: "CVE-2026-1234", Red Hat's Bugzilla as "RHBZ#2369081"."""
    return f"RHBZ#{ref_id}" if kind == "bugzilla" and ref_id.isdigit() else ref_id


def _advisories_html(row: PkgRow) -> str:
    """The advisories of an upgrade: what it fixes, with links to the advisory and to the bugs and CVEs."""
    parts = []
    for a in row.advisories:
        name = f"<a href='{e(a.url)}'>{e(a.id)}</a>" if a.url else e(a.id)
        parts.append(f"<p><b>{name}</b> — {e(ADVISORY_LABEL[a.level])}"
                     f"{' — ' + _date(a.issued)[:10] if a.issued else ''}"
                     f"{'<br>' + e(a.title) if a.title else ''}</p>")
        if a.description:
            parts.append(f"<p>{e(a.description).replace(chr(10), '<br>')}</p>")
        links = [f"<a href='{e(url)}'>{e(_reference(kind, ref_id) or url)}</a>" if url else e(_reference(kind, ref_id))
                 for kind, ref_id, url in a.references]
        if links:
            parts.append(f"<p>{e(_('References:'))} {', '.join(links)}</p>")
    return "".join(parts)


def _blocked_html(reason: str) -> str:
    """Above the dependencies of an upgrade that cannot be installed: the root cause, then the resolver's message."""
    title, _nl, cause = blocked_tip(reason).partition("\n")
    return (f"<p style='color:{ADVISORY_COLOR['important']}'><b>{e(title)}</b></p>"
            f"{f'<p><b>{e(cause)}</b></p>' if cause else ''}"
            f"<p>{e(_('The repository has to fix it. Until then Mark All Upgrades leaves this package out.'))}</p>"
            f"<p style='font-family:monospace; font-size:small; white-space:pre-wrap'>{e(reason.strip())}</p><hr>")


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
        self._blocked = ""  # its HTML
        self._deps_body = ""
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
        self._tabs = {
            "description": (self.desc, _("Description")), "general": (self.general, _("General")),
            "advisories": (self.advisories, _("Advisories")), "dependencies": (self.deps, _("Dependencies")),
            "files": (self.files, _("Files")), "versions": (self.versions, _("Versions")),
            "changelog": (self.changelog, _("Changelog")),
        }
        for widget, title in self._tabs.values():
            self.addTab(widget, title)
        self.setTabVisible(self.indexOf(self.advisories), False)
        # the advisories tab comes and goes with the selected package: when the user picked it, it is selected again
        # for the next package that has one, and meanwhile the tab the user had before stands in for it
        self._wants_advisories = False
        self._other_tab = self.general
        self._switching = False
        self.currentChanged.connect(self._on_current_changed)

    def _on_current_changed(self, _index) -> None:
        if self._switching:
            return
        self._wants_advisories = self.currentWidget() is self.advisories
        if not self._wants_advisories:
            self._other_tab = self.currentWidget()

    def current_name(self) -> str:
        """The current tab, as saved in the settings: "general", "advisories"…"""
        if self._wants_advisories:
            return "advisories"
        return next(name for name, (widget, _title) in self._tabs.items() if widget is self.currentWidget())

    def select_name(self, name: str) -> None:
        widget = self._tabs.get(name, (self.desc, ""))[0]
        if widget is self.advisories and not self.isTabVisible(self.indexOf(widget)):
            self._wants_advisories = True
            return
        self.setCurrentWidget(widget)

    def show_advisories(self, row: PkgRow | None) -> None:
        """Show or hide the advisories tab for the selected package; at once, without waiting for its details."""
        index = self.indexOf(self.advisories)
        self._switching = True
        try:
            if row is None or not row.advisories:
                if self.currentIndex() == index:
                    self.setCurrentWidget(self._other_tab)
                self.setTabVisible(index, False)
                self.advisories.clear()
                return
            self.setTabIcon(index, advisory_icon(row.advisory.level))
            self.setTabToolTip(index, ADVISORY_LABEL[row.advisory.level])
            self.advisories.setHtml(_advisories_html(row))
            self.setTabVisible(index, True)
            if self._wants_advisories:
                self.setCurrentIndex(index)
        finally:
            self._switching = False

    def show_blocked(self, reason: str | None) -> None:
        """Mark the dependencies tab when the selected upgrade cannot be installed now; at once, like the advisories."""
        index = self.indexOf(self.deps)
        self.setTabIcon(index, blocked_icon() if reason else QIcon())
        self.setTabToolTip(index, blocked_tip(reason) if reason else "")
        self._blocked = _blocked_html(reason) if reason else ""
        self._set_deps()

    def _set_deps(self) -> None:
        if self._blocked or self._deps_body:
            self.deps.setHtml(self._blocked + self._deps_body)
        else:
            self.deps.clear()

    def clear(self) -> None:
        for b in (self.desc, self.general, self.changelog):
            b.clear()
        self._deps_body = ""
        self.show_blocked(None)
        self.files.clear()
        self.versions.clear()
        self.show_advisories(None)

    def show_package(self, row: PkgRow, d: PkgDetails) -> None:
        paragraphs = "".join(f"<p>{e(p)}</p>" for p in d.description.split("\n\n") if p.strip())
        self.desc.setHtml(f"<h3>{e(d.summary)}</h3>{paragraphs}")

        def tr(label, value):
            return f"<tr><td style='padding-right:16px'><b>{label}</b></td><td>{value}</td></tr>"

        url = f"<a href='{e(d.url)}'>{e(d.url)}</a>" if d.url else "—"
        reason = {True: _("by the user"), False: _("as a dependency"), None: "—"}[d.user_installed]
        rows = [
            tr(_("Package"), e(d.nevra)),
            tr(_("Origin"), f"{ORIGIN_LABEL[row.origin]} — {e(display_repo(row.origin_repo))}"),
            tr(_("Candidate repository"), e(display_repo(d.repo_id)) or "—"),
            tr(_("License"), e(d.license)),
            tr(_("Website"), url),
            tr(_("Vendor"), e(d.vendor) or "—"),
            tr(_("Packager"), e(d.packager) or "—"),
            tr(_("Source package"), e(d.source_rpm)),
            tr(_("Built"), _date(d.build_time)),
            tr(pgettext("install date", "Installed"), _date(d.install_time)),
            tr(_("Install reason"), reason),
            tr(_("Installed size"), human_size(d.install_size)),
            tr(_("Download size"), human_size(d.download_size) if d.download_size else "—"),
        ]
        self.general.setHtml(f"<table>{''.join(rows)}</table>")

        def section(title, items, kind="dep"):
            if not items:
                return ""
            if kind == "pkg":
                lis = "".join(f"<li><a href='pkg:{quote(f'{n}.{a}')}'>{e(n)}.{e(a)}</a></li>" for n, a in items)
            else:
                lis = "".join(f"<li><a href='dep:{quote(i)}'>{e(i)}</a></li>" for i in items)
            return f"<b>{title} ({len(items)})</b><ul style='margin-top:2px'>{lis}</ul>"

        self._deps_body = "".join([
            section(_("Requires"), d.requires),
            section(_("Recommends"), d.recommends),
            section(_("Suggests"), d.suggests),
            section(_("Required by installed packages"), d.required_by, "pkg"),
            section(_("Conflicts"), d.conflicts),
            section(_("Obsoletes"), d.obsoletes),
            section(_("Provides"), d.provides),
        ]) or f"<i>{e(_('No dependencies'))}</i>"
        self._set_deps()

        self.files.set_files(d.files, d.files_complete)

        self.versions.clear()
        for v in d.versions:
            state = pgettext("version state", "installed") if v.installed else (_("candidate") if v.candidate else "")
            item = QTreeWidgetItem([v.evr, display_repo(v.repo_id), state])
            if v.installed or v.candidate:
                f = item.font(0)
                f.setBold(True)
                item.setFont(0, f)
            self.versions.addTopLevelItem(item)

        if d.changelog:
            self.changelog.setHtml("".join(
                f"<p><b>{_date(c.timestamp)[:10]}</b> — {e(c.author)}<br>"
                f"{e(c.text).replace(chr(10), '<br>')}</p>" for c in d.changelog))
        else:
            self.changelog.setHtml("<i>" + e(_("The changelog is available for installed packages only "
                                                "(dnf5 does not download it for repositories by default).")) + "</i>")

    def _on_link(self, url) -> None:
        s = url.toString()
        kind, _, value = s.partition(":")
        if kind in ("dep", "pkg"):
            self.linkActivated.emit(kind, unquote(value))
        elif kind in ("http", "https"):
            QDesktopServices.openUrl(url)

