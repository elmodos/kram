"""Bottom detail tabs for the selected package."""
import html
from datetime import datetime
from urllib.parse import quote, unquote

from PySide6.QtCore import Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import QPlainTextEdit, QTabWidget, QTextBrowser, QTreeWidget, QTreeWidgetItem

from ..core.model import PkgDetails, PkgRow
from ..core.origin import display_repo
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
        self.versions.setHeaderLabels(["Версія", "Репозиторій", "Стан"])
        self.versions.setRootIsDecorated(False)
        self.versions.setColumnWidth(0, 260)
        self.versions.setColumnWidth(1, 360)
        self.changelog = _browser()
        for widget, title in [(self.desc, "Опис"), (self.general, "Загальне"), (self.deps, "Залежності"),
                              (self.files, "Файли"), (self.versions, "Версії"), (self.changelog, "Changelog")]:
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
        reason = {True: "вручну (користувачем)", False: "як залежність", None: "—"}[d.user_installed]
        rows = [
            tr("Пакунок", e(d.nevra)),
            tr("Походження", f"{ORIGIN_LABEL[row.origin]} — {e(display_repo(row.origin_repo))}"),
            tr("Репозиторій кандидата", e(display_repo(d.repo_id)) or "—"),
            tr("Ліцензія", e(d.license)),
            tr("Сайт", url),
            tr("Постачальник", e(d.vendor) or "—"),
            tr("Пакувальник", e(d.packager) or "—"),
            tr("Вихідний пакунок", e(d.source_rpm)),
            tr("Зібрано", _date(d.build_time)),
            tr("Встановлено", _date(d.install_time)),
            tr("Причина встановлення", reason),
            tr("Розмір встановлення", human_size(d.install_size)),
            tr("Розмір завантаження", human_size(d.download_size) if d.download_size else "—"),
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
            section("Залежить від (Requires)", d.requires),
            section("Рекомендує (Recommends)", d.recommends),
            section("Пропонує (Suggests)", d.suggests),
            section("Від нього залежать встановлені пакунки", d.required_by, "pkg"),
            section("Конфліктує з (Conflicts)", d.conflicts),
            section("Замінює (Obsoletes)", d.obsoletes),
            section("Надає (Provides)", d.provides),
        ]) or "<i>Залежностей немає</i>")

        header = "" if d.files_complete else (
            "# Пакунок не встановлено: метадані репозиторію містять лише частину файлів.\n")
        self.files.setPlainText(header + "\n".join(d.files))

        self.versions.clear()
        for v in d.versions:
            state = "встановлено" if v.installed else ("кандидат" if v.candidate else "")
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
            self.changelog.setHtml("<i>Changelog доступний лише для встановлених пакунків "
                                   "(dnf5 не завантажує його для репозиторіїв за замовчуванням).</i>")

    def _on_link(self, url) -> None:
        s = url.toString()
        kind, _, value = s.partition(":")
        if kind in ("dep", "pkg"):
            self.linkActivated.emit(kind, unquote(value))
        elif kind in ("http", "https"):
            QDesktopServices.openUrl(url)

