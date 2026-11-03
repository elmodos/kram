"""Bottom detail tabs for the selected package."""
import html
from datetime import datetime
from urllib.parse import quote, unquote

from PySide6.QtCore import Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import QPlainTextEdit, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem

from ..core.model import PkgDetails, PkgRow
from ..core.origin import display_repo
from ..i18n import _, pgettext
from .icons import ORIGIN_LABEL
from .package_model import human_size

e = html.escape


def _date(ts: int | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "—"


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
        self.general.anchorClicked.connect(self._on_link)
        self.files = QPlainTextEdit()
        self.files.setReadOnly(True)
        self.files.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.versions = QTreeWidget()
        self.versions.setHeaderLabels([_("Version"), _("Repository"), _("State")])
        self.versions.setRootIsDecorated(False)
        self.versions.setColumnWidth(0, 260)
        self.versions.setColumnWidth(1, 360)
        self.changelog = _browser()
        for widget, title in [(self.desc, _("Description")), (self.general, _("General")),
                              (self.deps, _("Dependencies")), (self.files, _("Files")),
                              (self.versions, _("Versions")), (self.changelog, _("Changelog"))]:
            self.addTab(widget, title)

    def clear(self) -> None:
        for b in (self.desc, self.general, self.deps, self.changelog):
            b.clear()
        self.files.clear()
        self.versions.clear()

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

        self.deps.setHtml("".join([
            section(_("Requires"), d.requires),
            section(_("Recommends"), d.recommends),
            section(_("Suggests"), d.suggests),
            section(_("Required by installed packages"), d.required_by, "pkg"),
            section(_("Conflicts"), d.conflicts),
            section(_("Obsoletes"), d.obsoletes),
            section(_("Provides"), d.provides),
        ]) or f"<i>{e(_('No dependencies'))}</i>")

        header = "" if d.files_complete else (
            "# " + _("Not installed: repository metadata lists only some of the files.") + "\n")
        self.files.setPlainText(header + "\n".join(d.files))

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

