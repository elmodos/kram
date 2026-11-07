"""Installing one package file, gdebi-style: what it is, what installing it changes, and the button that does it.

Self-contained (it gets the catalog, its dnf thread and the helper client), so it also works without the main
window. Marks in the main window are not part of it."""
import html
import os

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase, QIcon, QTextDocumentFragment
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QStyle,
    QTabWidget,
    QTextBrowser,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core import local_rpm
from ..core.local_rpm import LocalRpm, VerifyResult
from ..core.marks import dnf5_command
from ..core.model import LocalTarget, TransactionPreview
from ..core.origin import display_repo
from ..i18n import N_, _, ngettext
from .apply_dialog import ChangesTree, RecommendationsList, removal_warning, signed_size
from .details import _date
from .dnf_thread import DnfThread
from .package_model import human_size
from .progress_dialog import ProgressDialog

e = html.escape
OK, WARN, ERROR, INFO = "#2f7a1f", "#a86f1f", "#c03030", None
# the header's lines get theme icons, not symbols: a font without "ℹ" shows a plain "i"
ICONS = {OK: ("data-success", "emblem-ok-symbolic"), WARN: ("data-warning", "dialog-warning"),
         ERROR: ("data-error", "dialog-error"), INFO: ("data-information", "dialog-information")}
INDENT = "indent"  # a line under the one before it, without an icon
BUTTONS = {"install": (N_("Install"), "list-add"), "alongside": (N_("Install"), "list-add"),
           "upgrade": (N_("Upgrade"), "go-up"),
           "downgrade": (N_("Downgrade"), "go-down"), "reinstall": (N_("Reinstall"), "view-refresh")}
MAX_REASON_LINES = 4
MAX_PROVIDERS = 3
# rpm -V letters
VERIFY_FLAGS = {"S": N_("size"), "M": N_("permissions"), "5": N_("contents"), "D": N_("device"),
                "L": N_("link target"), "U": N_("owner"), "G": N_("group"), "T": N_("modification time"),
                "P": N_("capabilities")}


def _browser() -> QTextBrowser:
    b = QTextBrowser()
    b.setOpenLinks(False)
    b.anchorClicked.connect(QDesktopServices.openUrl)
    return b


def _plain() -> QPlainTextEdit:
    t = QPlainTextEdit()
    t.setReadOnly(True)
    t.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
    return t


def _line(kind: str | None, text: str) -> tuple[str | None, str]:
    """A header line: an icon for `kind` (OK, WARN, ERROR, INFO or INDENT) and rich text."""
    return kind, text


class InstallDialog(QDialog):
    def __init__(self, path: str, catalog, dnf: DnfThread, helper, basearch: str = "x86_64", marks: int = 0,
                 parent=None, load_catalog: bool = False):
        super().__init__(parent)
        self.setWindowTitle(_("Install Package File"))
        self.resize(880, 760)
        # a symlink to a package works like the file itself; the helper only opens real files
        real = os.path.realpath(path)
        self.path = real if real.endswith(".rpm") else os.path.abspath(path)
        self.catalog, self.dnf, self.helper, self.marks = catalog, dnf, helper, marks
        self.rpm: LocalRpm | None = None
        self.target: LocalTarget | None = None
        self.preview: TransactionPreview | None = None
        self.verify: VerifyResult | None = None
        self.error = ""               # why the file cannot be installed at all
        self.changed_system = False   # a transaction ran: even a failed one may have changed something
        self._busy: dict[str, str] = {}
        self._choice_problem = ""     # the unchecked recommendations cannot be carried out
        self._generation = 0
        self._closed = False
        self._verify_proc: QProcess | None = None
        self._reader = DnfThread(self)  # hashing a big file must not hold up the dnf thread

        lay = QVBoxLayout(self)
        head = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(QIcon.fromTheme("application-x-rpm", QIcon.fromTheme("package-x-generic")).pixmap(48, 48))
        icon.setAlignment(Qt.AlignTop)
        head.addWidget(icon)
        text = QVBoxLayout()
        self.title = QLabel(e(os.path.basename(self.path)))
        font = QFont(self.title.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.4)
        self.title.setFont(font)
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.title.setWordWrap(True)  # a long name and version must not widen the dialog
        self.subtitle = QLabel()
        self.subtitle.setWordWrap(True)
        self.subtitle.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.notes = QWidget()
        self._notes_layout = QVBoxLayout(self.notes)
        self._notes_layout.setContentsMargins(0, 0, 0, 0)
        self._notes_layout.setSpacing(2)
        for w in (self.title, self.subtitle, self.notes):
            text.addWidget(w)
        head.addLayout(text, 1)
        lay.addLayout(head)

        self.tabs = QTabWidget()
        self.desc = _browser()
        self.details = _browser()
        self.changes = ChangesTree(basearch)
        self.deps = _browser()
        deps = QSplitter(Qt.Vertical)
        changes_box = QWidget()
        box_lay = QVBoxLayout(changes_box)
        box_lay.setContentsMargins(0, 0, 0, 0)
        box_lay.addWidget(QLabel("<b>{}</b>".format(_("What installing it changes"))))
        box_lay.addWidget(self.changes)
        deps.addWidget(changes_box)
        deps.addWidget(self.deps)
        deps.setChildrenCollapsible(False)
        deps.setSizes([300, 200])
        self.files = _plain()
        self.changelog = _browser()
        self.scripts = _plain()
        for widget, title in [(self.desc, _("Description")), (self.details, _("Details")),
                              (deps, _("Dependencies")), (self.files, _("Files")),
                              (self.changelog, _("Changelog")), (self.scripts, _("Scripts"))]:
            self.tabs.addTab(widget, title)

        self.recs = RecommendationsList(set())
        self.recs.toggled.connect(self._resolve_again)
        self.recs.setVisible(False)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.tabs)
        split.addWidget(self.recs)
        split.setChildrenCollapsible(False)
        split.setSizes([420, 200])
        lay.addWidget(split, 1)

        self.sizes = QLabel()
        self.sizes.setWordWrap(True)
        lay.addWidget(self.sizes)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(f"color: {ERROR}; font-weight: bold")
        self.warning.setVisible(False)
        lay.addWidget(self.warning)
        self.cmd = QLineEdit()
        self.cmd.setReadOnly(True)
        self.cmd.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.cmd_box = QGroupBox(_("Equivalent command"))
        QVBoxLayout(self.cmd_box).addWidget(self.cmd)
        self.cmd_box.setVisible(False)
        lay.addWidget(self.cmd_box)

        bottom = QHBoxLayout()
        self.status = QLabel()  # what runs now; the buttons wait for it
        bottom.addWidget(self.status, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.install = buttons.addButton(_("Install"), QDialogButtonBox.AcceptRole)
        self.install.setIcon(QIcon.fromTheme("list-add"))
        self.install.setDefault(True)
        buttons.accepted.connect(self._install)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        lay.addLayout(bottom)

        self._busy["read"] = _("Reading {file}…").format(file=os.path.basename(self.path))
        catalog, file = self.catalog, self.path
        if load_catalog:  # on its own (`kram file.rpm`): nobody has loaded the catalog yet
            self._busy["catalog"] = _("Loading metadata…")
            self.dnf.submit(catalog.load, self._on_catalog, self._on_catalog_failed)
        else:
            self._busy["resolve"] = _("Resolving dependencies…")
        self._render()
        self._reader.submit(lambda: local_rpm.read(self.path), self._on_read, self._on_read_failed)

        def first():
            target = catalog.open_local(file)
            return target, catalog.resolve_local(file, target.helper_action, [], sizes=True)
        self.dnf.submit(first, self._on_target, self._on_resolve_failed)

    # ---------------------------------------------------------------- results

    def _on_catalog(self, snapshot) -> None:
        # the dnf thread runs the first resolve right after this load
        if self._closed:
            return
        self._busy.pop("catalog", None)
        self._busy["resolve"] = _("Resolving dependencies…")
        self.changes.set_basearch(snapshot.basearch)
        self._render()

    def _on_catalog_failed(self, error: BaseException) -> None:
        if self._closed:
            return
        self._busy.pop("catalog", None)
        self.error = self.error or _("Could not load the package catalog:\n\n{error}").format(error=error)
        self._render()

    def _on_read(self, rpm: LocalRpm) -> None:
        if self._closed:
            return
        self.rpm = rpm
        self._busy.pop("read", None)
        if rpm.source:
            self.error = _("This is a source package: it can be used to build the program, not installed.")
        elif rpm.signature.state == "bad":
            self.error = _("The file is damaged: its checksums do not match.")
        self._fill_tabs()
        self._start_verify()
        self._render()

    def _on_read_failed(self, error: BaseException) -> None:
        if self._closed:
            return
        self._busy.pop("read", None)
        self.error = self.error or _("Could not read the file: {error}").format(error=error)
        self._render()

    def _on_target(self, result) -> None:
        if self._closed:
            return
        self.target, self.preview = result
        self._busy.pop("resolve", None)
        self.recs.fill(self.preview)
        self.recs.setVisible(bool(self.preview.recommendations))
        self.changes.fill(self.preview)
        self._fill_deps()
        for line in "\n".join(self.preview.problems).splitlines():
            item = QTreeWidgetItem([line])
            self.changes.addTopLevelItem(item)
            item.setFirstColumnSpanned(True)
        self._start_verify()
        self._render()

    def _on_resolve_failed(self, error: BaseException) -> None:
        if self._closed:
            return
        self._busy.pop("resolve", None)
        self.error = self.error or _("Could not resolve the changes:\n\n{error}").format(error=error)
        self._render()

    def _resolve_again(self) -> None:
        self._generation += 1
        generation = self._generation
        self._busy["resolve"] = _("Resolving dependencies…")
        self.recs.tree.setEnabled(False)
        self._render()
        catalog, file, action, exclude = self.catalog, self.path, self.target.helper_action, sorted(self.recs.exclude)

        def done(preview: TransactionPreview) -> None:
            if self._closed or generation != self._generation:
                return
            self._busy.pop("resolve", None)
            self.recs.tree.setEnabled(True)
            if preview.ok:
                self.preview = preview
                self.recs.fill(preview)
                self.changes.fill(preview)
                self._fill_deps()
                self._choice_problem = ""
            else:
                self._choice_problem = _("These choices cannot be carried out:") + " " + preview.problems[0][:300]
            self._render()

        def failed(error: BaseException) -> None:
            if not self._closed and generation == self._generation:
                self._busy.pop("resolve", None)
                self.recs.tree.setEnabled(True)
                self._choice_problem = _("Could not resolve the changes:\n\n{error}").format(error=error)
                self._render()

        self.dnf.submit(lambda: catalog.resolve_local(file, action, exclude, sizes=False), done, failed)

    # ---------------------------------------------------------------- rpm -V of the installed copy

    def _start_verify(self) -> None:
        """Same version installed: check its files, so a reinstall is done knowing what it repairs."""
        r, t = self.rpm, self.target
        if r is None or t is None or t.action != "reinstall" or self._verify_proc is not None or self.error:
            return
        proc = self._verify_proc = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("LC_ALL", "C.UTF-8")  # parsed: "missing", "(Permission denied)"
        proc.setProcessEnvironment(env)
        proc.finished.connect(lambda _code, _status: self._on_verified(proc))
        proc.errorOccurred.connect(lambda err: err == QProcess.FailedToStart and self._on_verified(proc))
        self._busy["verify"] = _("Checking the installed files of {name}…").format(name=r.name)
        cmd = local_rpm.verify_command(r.name, r.version, r.release, r.arch)
        proc.start(cmd[0], cmd[1:])

    def _on_verified(self, proc: QProcess) -> None:
        if self._closed or "verify" not in self._busy:
            return
        self._busy.pop("verify")
        self.verify = local_rpm.parse_verify(bytes(proc.readAllStandardOutput()).decode(errors="replace"))
        self._fill_files()
        self._render()

    # ---------------------------------------------------------------- showing it

    def _render(self) -> None:
        """Header, size line, buttons and status from what is known so far."""
        r, t, p = self.rpm, self.target, self.preview
        if r is not None:
            self.title.setText(f"{e(r.name)} <span style='font-weight:normal'>{e(r.evr)}.{e(r.arch)}</span>")
            self.subtitle.setText(e(r.summary))
        blocked = bool(self.error) or (p is not None and not p.ok)
        lines = []
        if blocked:
            lines.append(_line(ERROR, "<b>{}</b>".format(e(_("Cannot be installed.")))))
            reason = (self.error or "\n".join(p.problems)).splitlines()
            if len(reason) > MAX_REASON_LINES:  # the solver's whole story is in the Dependencies tab
                reason = reason[:MAX_REASON_LINES] + ["… " + _("(the full text is in the Dependencies tab)")]
            lines.append(_line(INDENT, "<br>".join(map(e, reason))))
        elif t is not None:
            lines.append(self._state_line(t, r))
        if r is not None and not self.error:
            lines.append(self._signature_line(r))
        if r is not None and t is not None and not self.error:
            if t.repo_newer:
                lines.append(_line(WARN, e(_("The {repo} repository has a newer version ({version}): the next "
                                             "system update will install it over this one.").format(
                    repo=display_repo(t.repo_id), version=t.repo_evr))))
            elif t.repo_evr:
                lines.append(_line(INFO, e(_("Also available from the {repo} repository (version {version}).").format(
                    repo=display_repo(t.repo_id), version=t.repo_evr))))
            elif r.adds_repository:
                lines.append(_line(INFO, e(_("Adds a repository of its own and gets updates from it."))))
            else:
                lines.append(_line(INFO, e(_("No repository has this package: it gets no updates unless you "
                                             "install a newer file."))))
        if r is not None and r.scripts and not self.error:
            lines.append(_line(WARN, e(_("Runs scripts as root when it is installed or removed (see the Scripts "
                                         "tab)."))))
        if self.verify is not None:
            v = self.verify
            if v.problems:
                lines.append(_line(WARN, e(ngettext(
                    "{n} installed file is missing or changed (see the Files tab).",
                    "{n} installed files are missing or changed (see the Files tab).", v.problems).format(n=v.problems))))
            else:
                lines.append(_line(OK, e(_("The installed files are intact."))))
            if v.unreadable:
                n = len(v.unreadable)
                lines.append(_line(INFO, e(ngettext("{n} file could not be checked: no permission to read it.",
                                                    "{n} files could not be checked: no permission to read them.",
                                                    n).format(n=n))))
        if self.marks:
            lines.append(_line(INFO, e(ngettext(
                "{n} change marked in the main window is not part of this and stays marked.",
                "{n} changes marked in the main window are not part of this and stay marked.",
                self.marks).format(n=self.marks))))
        self._set_notes(lines)

        sizes, warning = self._choice_problem, ""
        if p is not None and p.ok and not self.error and not sizes:
            others = [i for i in p.items if i.repo_id != "@commandline"]
            download = sum(i.download_size for i in others)
            parts = []
            if others:
                parts.append(ngettext("Also changes {n} more package, see the Dependencies tab.",
                                      "Also changes {n} more packages, see the Dependencies tab.",
                                      len(others)).format(n=len(others)))
            parts.append(_("To download: {size}.").format(size=f"<b>{human_size(download)}</b>"))
            parts.append(_("Disk space change: {size}.").format(size=f"<b>{signed_size(p.size_change)}</b>"))
            sizes = "   ".join(parts)
            warning = removal_warning(p)
        self.sizes.setText(sizes)
        self.sizes.setVisible(bool(sizes))
        self.warning.setText(warning)
        self.warning.setVisible(bool(warning))
        self.cmd_box.setVisible(t is not None and not blocked)
        if t is not None:
            self.cmd.setText(dnf5_command(self._request()))
            self.cmd.setCursorPosition(0)

        action = t.action if t is not None else "install"
        label, icon = BUTTONS[action]
        self.install.setText(_(label))
        self.install.setIcon(QIcon.fromTheme(icon))
        self.install.setVisible(not blocked)
        self.install.setEnabled(not blocked and not self._busy and r is not None and t is not None
                                and not self._choice_problem)
        self.status.setText(" ".join(self._busy.values()))

    def _set_notes(self, lines: list[tuple[str | None, str]]) -> None:
        lay = self._notes_layout
        while lay.count():
            row = lay.takeAt(0).widget()
            row.setParent(None)  # gone from findChildren now, not at the next event loop
            row.deleteLater()
        size = self.style().pixelMetric(QStyle.PM_SmallIconSize)
        for kind, text in lines:
            row = QWidget()
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            icon = QLabel()
            icon.setFixedWidth(size)
            icon.setAlignment(Qt.AlignTop)
            if kind != INDENT:
                name, fallback = ICONS[kind]
                icon.setPixmap(QIcon.fromTheme(name, QIcon.fromTheme(fallback)).pixmap(size, size))
            label = QLabel(text)
            label.setWordWrap(True)
            label.setTextFormat(Qt.RichText)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row_lay.addWidget(icon)
            row_lay.addWidget(label, 1)
            lay.addWidget(row)

    def notes_text(self) -> str:
        """The header's lines as plain text (for tests)."""
        labels = self.notes.findChildren(QLabel)
        return "\n".join(QTextDocumentFragment.fromHtml(l.text()).toPlainText() for l in labels if l.text())

    def _state_line(self, t: LocalTarget, r: LocalRpm | None) -> tuple[str | None, str]:
        new = r.evr if r is not None else ""
        if t.action == "install":
            return _line(OK, e(_("Not installed yet.")))
        if t.action == "upgrade":
            return _line(OK, e(_("Upgrades the installed version {old} to {new}.").format(old=t.installed_evr, new=new)))
        if t.action == "alongside":
            return _line(INFO, e(_("Installs next to the installed version {old}: several versions of this package "
                                   "are kept side by side, like kernels.").format(old=t.installed_evr)))
        if t.action == "downgrade":
            return _line(WARN, "<b>{}</b>".format(e(_(
                "A newer version is installed ({old}). Installing this file downgrades it to {new}.").format(
                old=t.installed_evr, new=new))))
        return _line(INFO, e(_("This version is already installed. Reinstalling puts its files back as they "
                               "were packaged.")))

    @staticmethod
    def _signature_line(r: LocalRpm) -> tuple[str | None, str]:
        s = r.signature
        if s.state == "ok":
            return _line(OK, e(_("Signed by {signer}.").format(signer=s.signer or s.key)))
        if s.state == "nokey":
            return _line(WARN, e(_("Signed with a key this system does not know ({key}). Install it only if you "
                                   "trust where the file came from.").format(key=s.key)))
        return _line(WARN, e(_("Not signed. Install it only if you trust where the file came from.")))

    def _fill_tabs(self) -> None:
        r = self.rpm
        paragraphs = "".join(f"<p>{e(p)}</p>" for p in r.description.split("\n\n") if p.strip())
        self.desc.setHtml(f"<h3>{e(r.summary)}</h3>{paragraphs}")

        def tr(label, value):
            return f"<tr><td style='padding-right:16px'><b>{e(label)}</b></td><td>{value}</td></tr>"

        url = f"<a href='{e(r.url)}'>{e(r.url)}</a>" if r.url else "—"
        signature = {"ok": r.signature.key, "nokey": r.signature.key}.get(r.signature.state, "—")
        self.details.setHtml("<table>{}</table>".format("".join([
            tr(_("Package"), e(r.nevra)),
            tr(_("File"), e(r.path)),
            tr(_("SHA-256"), f"<code>{e(r.sha256)}</code>"),
            tr(_("Signing key"), f"<code>{e(signature)}</code>"),
            tr(_("License"), e(r.license)),
            tr(_("Website"), url),
            tr(_("Vendor"), e(r.vendor) or "—"),
            tr(_("Packager"), e(r.packager) or "—"),
            tr(_("Built"), _date(r.build_time)),
            tr(_("Installed size"), human_size(r.install_size)),
            tr(_("File size"), human_size(r.file_size)),
        ])))

        self._fill_deps()
        self._fill_files()
        if r.changelog:
            self.changelog.setHtml("".join(
                f"<p><b>{_date(c.timestamp)[:10]}</b> — {e(c.author)}<br>"
                f"{e(c.text).replace(chr(10), '<br>')}</p>" for c in r.changelog))
        else:
            self.changelog.setHtml(f"<i>{e(_('No changelog'))}</i>")
        self.scripts.setPlainText(r.scripts or _("This package runs no scripts."))

    def _fill_deps(self) -> None:
        """The file's dependencies; once the catalog has looked, with what satisfies each of them."""
        r, t = self.rpm, self.target
        if r is None:
            return
        brought = set()
        if self.preview is not None:
            brought = {i.name for i in self.preview.items
                       if i.action in ("install", "upgrade", "downgrade", "reinstall") and i.repo_id != "@commandline"}

        def plain(title, items):
            if not items:
                return ""
            lines = "".join(f"<p style='margin:0 0 0 16px'>• {e(i)}</p>" for i in items)
            return f"<p style='margin:8px 0 2px 0'><b>{e(title)} ({len(items)})</b></p>{lines}"

        def checked(title, kind, fallback):
            reqs = t.deps.get(kind) if t is not None else None
            if reqs is None:
                return plain(title, fallback)
            return plain(title, []) if not reqs else (
                f"<p style='margin:8px 0 2px 0'><b>{e(title)} ({len(reqs)})</b></p>"
                + "".join(self._requirement_line(q, brought) for q in reqs))

        self.deps.setHtml("".join([
            checked(_("Requires"), "requires", r.requires),
            checked(_("Recommends"), "recommends", r.recommends),
            checked(_("Suggests"), "suggests", r.suggests),
            plain(_("Supplements"), r.supplements),
            plain(_("Conflicts"), r.conflicts),
            plain(_("Obsoletes"), r.obsoletes),
            plain(_("Provides"), r.provides),
        ]) or f"<i>{e(_('No dependencies'))}</i>")

    @staticmethod
    def _requirement_line(q, brought: set[str]) -> str:
        def names(found: list[str]) -> str:
            return ", ".join(found[:MAX_PROVIDERS]) + (" …" if len(found) > MAX_PROVIDERS else "")

        coming = [n for n in q.available if n in brought]
        if q.installed:
            color, note = OK, _("installed: {names}").format(names=names(q.installed))
        elif q.own:
            color, note = OK, _("provided by this package")
        elif coming:
            color, note = OK, _("will be installed: {names}").format(names=names(coming))
        elif q.available:
            color, note = INFO, _("not installed")
        else:
            color, note = ERROR, _("unavailable: no package provides it")
        mark = {OK: "✔" if not coming or q.installed or q.own else "<b>+</b>", INFO: "○", ERROR: "✖"}[color]
        styled = f"<span style='color:{color}'>{mark}</span>" if color else mark
        return f"<p style='margin:0 0 0 16px'>{styled} {e(q.text)} <span style='color:gray'>— {e(note)}</span></p>"

    def _fill_files(self) -> None:
        if self.rpm is None:
            return
        head = []
        if self.verify is not None:
            v = self.verify
            head += ["# " + _("Missing: {path}").format(path=p) for p in v.missing]
            for path, flags, config in v.changed:
                what = ", ".join(_(VERIFY_FLAGS[c]) for c in flags if c in VERIFY_FLAGS)
                line = _("Changed ({what}): {path}").format(what=what, path=path)
                head.append("# " + line + (" — " + _("a configuration file") if config else ""))
            head += ["# " + _("Could not check: {path}").format(path=p) for p in v.unreadable]
            if head:
                head.append("")
        self.files.setPlainText("\n".join(head + self.rpm.files))

    # ---------------------------------------------------------------- installing

    def _install(self) -> None:
        if self.helper.busy or self.rpm is None or self.target is None or not self.install.isEnabled():
            return
        request = self._request()
        self.install.setEnabled(False)
        self.changed_system = True
        progress = ProgressDialog(self.helper, request, _("Installing {name}").format(name=self.rpm.name), self)
        progress.exec()
        if progress.ok:
            self.accept()
        else:
            self._render()

    def _request(self) -> dict:
        request = {"op": "local_install", "path": self.path, "sha256": self.rpm.sha256 if self.rpm else "",
                   "action": self.target.helper_action}
        if self.recs.exclude:
            request["exclude_weak"] = sorted(self.recs.exclude)
        return request

    def done(self, result: int) -> None:
        if not self._closed:
            self._closed = True
            if self._verify_proc is not None and self._verify_proc.state() != QProcess.NotRunning:
                self._verify_proc.kill()
            self._reader.shutdown()
            self.dnf.submit(self.catalog.forget_local, lambda _result: None)
        super().done(result)
