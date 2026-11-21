"""Installing one package file, gdebi-style: what it is, what installing it changes, and the button that does it.

`Install` runs it without a toolkit: the catalog (loaded first when Kram was started with the file alone), reading
the file on a thread of its own, the first resolve, `rpm -V` of an installed copy of the same version, resolving again
when a recommendation is unchecked, and the request to run. Each step that finishes shows what is known so far through
the view: the header's lines, the tabs as docs, the size line, the button and what is still running."""
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..core import local_rpm, proc
from ..core.local_rpm import LocalRpm, VerifyResult
from ..core.mainloop import Post
from ..core.marks import dnf5_command
from ..core.model import LocalTarget, Requirement, TransactionPreview
from ..core.origin import display_repo
from ..core.worker import DnfWorker
from ..i18n import N_, _, ngettext
from .apply_review import ChangeSection, Recommendations, RecRow, change_sections, removal_warning, signed_size
from .columns import human_size
from .details import date_text
from .doc import (
    BR,
    Doc,
    Heading,
    Inline,
    Section,
    Span,
    Table,
    bold,
    colored,
    filled,
    italic,
    joined,
    lines,
    link,
    para,
)
from .icons import ERROR, INFO, OK, WARN
from .ports import is_web_link, view_ref

INDENT = "indent"  # a header line under the one before it, without an icon
BUTTONS = {"install": (N_("Install"), "list-add"), "alongside": (N_("Install"), "list-add"),
           "upgrade": (N_("Upgrade"), "go-up"),
           "downgrade": (N_("Downgrade"), "go-down"), "reinstall": (N_("Reinstall"), "view-refresh")}
MAX_REASON_LINES = 4
MAX_PROVIDERS = 3
# rpm -V letters
VERIFY_FLAGS = {"S": N_("size"), "M": N_("permissions"), "5": N_("contents"), "D": N_("device"),
                "L": N_("link target"), "U": N_("owner"), "G": N_("group"), "T": N_("modification time"),
                "P": N_("capabilities")}


@dataclass(frozen=True)
class Note:
    """A header line: `kind` is OK, WARN, ERROR or INFO (its icon, kram.app.icons.STATE_ICONS) or INDENT."""
    kind: str | None
    spans: tuple[Span, ...]


def note(kind: str | None, *spans: Span) -> Note:
    return Note(kind, spans)


@dataclass(frozen=True)
class InstallButton:
    text: str
    icon: str       # a theme icon name
    visible: bool
    enabled: bool


def real_path(path: str) -> str:
    """A symlink to a package works like the file itself; the helper only opens real files."""
    real = os.path.realpath(path)
    return real if real.endswith(".rpm") else os.path.abspath(path)


# ---------------------------------------------------------------- the header's lines


def state_note(t: LocalTarget, r: LocalRpm | None) -> Note:
    new = r.evr if r is not None else ""
    if t.action == "install":
        return note(OK, _("Not installed yet."))
    if t.action == "upgrade":
        return note(OK, _("Upgrades the installed version {old} to {new}.").format(old=t.installed_evr, new=new))
    if t.action == "alongside":
        return note(INFO, _("Installs next to the installed version {old}: several versions of this package are kept "
                            "side by side, like kernels.").format(old=t.installed_evr))
    if t.action == "downgrade":
        return note(WARN, bold(_("A newer version is installed ({old}). Installing this file downgrades it to "
                                 "{new}.").format(old=t.installed_evr, new=new)))
    return note(INFO, _("This version is already installed. Reinstalling puts its files back as they were packaged."))


def signature_note(r: LocalRpm) -> Note:
    s = r.signature
    if s.state == "ok":
        return note(OK, _("Signed by {signer}.").format(signer=s.signer or s.key))
    if s.state == "nokey":
        return note(WARN, _("Signed with a key this system does not know ({key}). Install it only if you trust where "
                            "the file came from.").format(key=s.key))
    if s.state == "unknown":
        return note(WARN, _("The signature could not be checked. Install it only if you trust where the file came "
                            "from."))
    return note(WARN, _("Not signed. Install it only if you trust where the file came from."))


def repo_note(t: LocalTarget, r: LocalRpm) -> Note:
    if t.repo_newer:
        return note(WARN, _("The {repo} repository has a newer version ({version}): the next system update will "
                            "install it over this one.").format(repo=display_repo(t.repo_id), version=t.repo_evr))
    if t.repo_evr:
        return note(INFO, _("Also available from the {repo} repository (version {version}).").format(
            repo=display_repo(t.repo_id), version=t.repo_evr))
    if r.adds_repository:
        return note(INFO, _("Adds a repository of its own and gets updates from it."))
    return note(INFO, _("No repository has this package: it gets no updates unless you install a newer file."))


def verify_notes(v: VerifyResult) -> list[Note]:
    out = []
    if v.problems:
        out.append(note(WARN, ngettext("{n} installed file is missing or changed (see the Files tab).",
                                       "{n} installed files are missing or changed (see the Files tab).",
                                       v.problems).format(n=v.problems)))
    else:
        out.append(note(OK, _("The installed files are intact.")))
    if v.unreadable:
        n = len(v.unreadable)
        out.append(note(INFO, ngettext("{n} file could not be checked: no permission to read it.",
                                       "{n} files could not be checked: no permission to read them.", n).format(n=n)))
    return out


# ---------------------------------------------------------------- the tabs


def description_doc(r: LocalRpm) -> Doc:
    return Doc([Heading((r.summary,))] + [para(p) for p in r.description.split("\n\n") if p.strip()])


def details_doc(r: LocalRpm) -> Doc:
    url: Span = link("web", r.url) if r.url and is_web_link(r.url) else (r.url or "—")
    signature = {"ok": r.signature.key, "nokey": r.signature.key}.get(r.signature.state, "—")
    rows = [(_("Package"), r.nevra), (_("File"), r.path), (_("SHA-256"), r.sha256), (_("Signing key"), signature),
            (_("License"), r.license), (_("Website"), url), (_("Vendor"), r.vendor or "—"),
            (_("Packager"), r.packager or "—"), (_("Built"), date_text(r.build_time)),
            (_("Installed size"), human_size(r.install_size)), (_("File size"), human_size(r.file_size))]
    return Doc([Table(tuple(((label,), (value,)) for label, value in rows))])


def changelog_doc(r: LocalRpm) -> Doc:
    if not r.changelog:
        return Doc([Inline((italic(_("No changelog")),))])
    return Doc([para(bold(date_text(c.timestamp)[:10]), f" — {c.author}", BR, *lines(c.text)) for c in r.changelog])


def scripts_text(r: LocalRpm) -> str:
    if r.scripts is None:
        return _("The scripts could not be read.")
    return r.scripts or _("This package runs no scripts.")


def requirement_line(q: Requirement, brought: set[str]) -> tuple[Span, ...]:
    """A requirement with what satisfies it: installed, this package, a package coming with it, or nothing."""
    def names(found: list[str]) -> str:
        return ", ".join(found[:MAX_PROVIDERS]) + (" …" if len(found) > MAX_PROVIDERS else "")

    coming = [n for n in q.available if n in brought]
    if q.installed:
        color, text = OK, _("installed: {names}").format(names=names(q.installed))
    elif q.own:
        color, text = OK, _("provided by this package")
    elif coming:
        color, text = OK, _("will be installed: {names}").format(names=names(coming))
    elif q.available:
        color, text = INFO, _("not installed")
    else:
        color, text = ERROR, _("unavailable: no package provides it")
    mark: Span = {OK: "✔" if not coming or q.installed or q.own else bold("+"), INFO: "○", ERROR: "✖"}[color]
    return (colored(color, mark) if color else mark, f" {q.text} ", colored("gray", f"— {text}"))


def deps_doc(r: LocalRpm, t: LocalTarget | None, preview: TransactionPreview | None) -> Doc:
    """The file's dependencies; once the catalog has looked, with what satisfies each of them."""
    brought = set()
    if preview is not None:
        brought = {i.name for i in preview.items
                   if i.action in ("install", "upgrade", "downgrade", "reinstall") and i.repo_id != "@commandline"}

    def plain(title: str, items: list[str]) -> list:
        return [Section(title, len(items), tuple((f"• {i}",) for i in items), marked=True)] if items else []

    def checked(title: str, kind: str, fallback: list[str]) -> list:
        reqs = t.deps.get(kind) if t is not None else None
        if reqs is None:
            return plain(title, fallback)
        return [Section(title, len(reqs), tuple(requirement_line(q, brought) for q in reqs), marked=True)] if reqs \
            else []

    blocks = (checked(_("Requires"), "requires", r.requires) + checked(_("Recommends"), "recommends", r.recommends)
              + checked(_("Suggests"), "suggests", r.suggests) + plain(_("Supplements"), r.supplements)
              + plain(_("Conflicts"), r.conflicts) + plain(_("Obsoletes"), r.obsoletes)
              + plain(_("Provides"), r.provides))
    return Doc(blocks or [Inline((italic(_("No dependencies")),))])


def files_text(r: LocalRpm, v: VerifyResult | None) -> str:
    """The file list, after what `rpm -V` found wrong with the installed copy."""
    head = []
    if v is not None:
        head += ["# " + _("Missing: {path}").format(path=p) for p in v.missing]
        for path, flags, config in v.changed:
            what = ", ".join(_(VERIFY_FLAGS[c]) for c in flags if c in VERIFY_FLAGS)
            line = _("Changed ({what}): {path}").format(what=what, path=path)
            head.append("# " + line + (" — " + _("a configuration file") if config else ""))
        head += ["# " + _("Could not check: {path}").format(path=p) for p in v.unreadable]
        if head:
            head.append("")
    return "\n".join(head + r.files)


# ---------------------------------------------------------------- the dialog


class InstallView(Protocol):
    def show_title(self, name: str, version: str, summary: str) -> None:
        """`version` is "" while the file is not read yet (`name` is then the file's name)."""
        ...

    def show_notes(self, notes: list[Note]) -> None: ...

    def show_sizes(self, spans: list[Span]) -> None:
        """The size line, or why the chosen recommendations do not work; empty: none."""
        ...

    def show_warning(self, text: str) -> None: ...

    def show_command(self, text: str | None) -> None:
        """The equivalent dnf5 command; None: none to show."""
        ...

    def show_button(self, button: InstallButton) -> None: ...

    def show_status(self, text: str) -> None:
        """What runs now; the button waits for it."""
        ...

    def show_file(self, description: Doc, details: Doc, changelog: Doc, scripts: str) -> None: ...

    def show_deps(self, doc: Doc) -> None: ...

    def show_files(self, text: str) -> None: ...

    def show_changes(self, sections: list[ChangeSection], problems: list[str]) -> None: ...

    def show_recs(self, rows: tuple[list[RecRow], list[RecRow]], visible: bool) -> None: ...

    def set_recs_enabled(self, on: bool) -> None: ...

    def run_transaction(self, request: dict, title: str, done: Callable[[bool], None]) -> None:
        """Run `request` through the helper with its progress; `done(ok)` when it is over."""
        ...

    def close_installed(self) -> None: ...


class Install:
    """`catalog` and `dnf` (its thread) resolve; `post` hands the file reader's and `rpm -V`'s results to the main
    loop. `marks`: changes marked in the main window, which this leaves alone. `start` begins; `close` when the dialog
    goes, whatever arrives later is dropped and the catalog forgets the file."""

    def __init__(self, path: str, catalog, dnf: DnfWorker, post: Post, view: InstallView, *, busy: Callable[[], bool],
                 basearch: str = "x86_64", marks: int = 0, load_catalog: bool = False):
        self.path = real_path(path)
        self.catalog, self.dnf, self.marks = catalog, dnf, marks
        self.rpm: LocalRpm | None = None
        self.target: LocalTarget | None = None
        self.preview: TransactionPreview | None = None
        self.verify: VerifyResult | None = None
        self.error = ""               # why the file cannot be installed at all
        self.changed_system = False   # a transaction ran: even a failed one may have changed something
        self.recs = Recommendations(set())
        self._view, self._post, self._helper_busy = view_ref(view), post, busy
        self._basearch, self._load_catalog = basearch, load_catalog
        self._busy: dict[str, str] = {}
        self._choice_problem = ""     # the unchecked recommendations cannot be carried out
        self._generation = 0
        self._closed = False
        self._verify_proc: proc.Process | None = None
        self._reader = DnfWorker(post, "kram-reader")  # hashing a big file must not hold up the dnf thread

    def start(self) -> None:
        self._busy["read"] = _("Reading {file}…").format(file=os.path.basename(self.path))
        catalog, file = self.catalog, self.path
        if self._load_catalog:  # on its own (`kram file.rpm`): nobody has loaded the catalog yet
            self._busy["catalog"] = _("Loading metadata…")
            self.dnf.submit(catalog.load, self._on_catalog, self._on_catalog_failed)
        else:
            self._busy["resolve"] = _("Resolving dependencies…")
        self._view.show_title(os.path.basename(self.path), "", "")
        self._render()
        self._reader.submit(lambda: local_rpm.read(file), self._on_read, self._on_read_failed)

        def first():
            target = catalog.open_local(file)
            return target, catalog.resolve_local(file, target.helper_action, [], sizes=True)
        self.dnf.submit(first, self._on_target, self._on_resolve_failed)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._verify_proc is not None:
            self._verify_proc.kill()
        self._reader.shutdown()
        self.dnf.submit(self.catalog.forget_local, lambda _result: None)

    def can_install(self) -> bool:
        return (not self._blocked() and not self._busy and self.rpm is not None and self.target is not None
                and not self._choice_problem)

    def request(self) -> dict:
        return self.recs.request({"op": "local_install", "path": self.path,
                                  "sha256": self.rpm.sha256 if self.rpm else "", "action": self.target.helper_action})

    # ---------------------------------------------------------------- results

    def _on_catalog(self, snapshot) -> None:
        # the dnf thread runs the first resolve right after this load
        if self._closed:
            return
        self._busy.pop("catalog", None)
        self._busy["resolve"] = _("Resolving dependencies…")
        self._basearch = snapshot.basearch
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
        self._view.show_title(rpm.name, f"{rpm.evr}.{rpm.arch}", rpm.summary)
        self._view.show_file(description_doc(rpm), details_doc(rpm), changelog_doc(rpm), scripts_text(rpm))
        self._show_deps()
        self._view.show_files(files_text(rpm, self.verify))
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
        self.target, preview = result
        self._busy.pop("resolve", None)
        self._show_preview(preview, problems="\n".join(preview.problems).splitlines())
        self._start_verify()
        self._render()

    def _on_resolve_failed(self, error: BaseException) -> None:
        if self._closed:
            return
        self._busy.pop("resolve", None)
        self.error = self.error or _("Could not resolve the changes:\n\n{error}").format(error=error)
        self._render()

    def _show_preview(self, preview: TransactionPreview, problems: list[str] = ()) -> None:
        self.preview = preview
        self._view.show_recs(self.recs.rows(preview), bool(preview.recommendations))
        self._view.show_changes(change_sections(preview, self._basearch), list(problems))
        self._show_deps()

    def recs_changed(self) -> None:
        """A recommendation was checked or unchecked (`recs.set_checked`): resolve again without what is left out."""
        self._generation += 1
        generation = self._generation
        self._busy["resolve"] = _("Resolving dependencies…")
        self._view.set_recs_enabled(False)
        self._render()
        catalog, file, action, exclude = self.catalog, self.path, self.target.helper_action, sorted(self.recs.exclude)

        def done(preview: TransactionPreview) -> None:
            if self._closed or generation != self._generation:
                return
            self._busy.pop("resolve", None)
            self._view.set_recs_enabled(True)
            if preview.ok:
                self._show_preview(preview)
                self._choice_problem = ""
            else:
                self._choice_problem = _("These choices cannot be carried out:") + " " + preview.problems[0][:300]
            self._render()

        def failed(error: BaseException) -> None:
            if not self._closed and generation == self._generation:
                self._busy.pop("resolve", None)
                self._view.set_recs_enabled(True)
                self._choice_problem = _("Could not resolve the changes:\n\n{error}").format(error=error)
                self._render()

        self.dnf.submit(lambda: catalog.resolve_local(file, action, exclude, sizes=False), done, failed)

    # ---------------------------------------------------------------- rpm -V of the installed copy

    def _start_verify(self) -> None:
        """Same version installed: check its files, so a reinstall is done knowing what it repairs."""
        r, t = self.rpm, self.target
        if r is None or t is None or t.action != "reinstall" or self._verify_proc is not None or self.error:
            return
        self._busy["verify"] = _("Checking the installed files of {name}…").format(name=r.name)
        cmd = local_rpm.verify_command(r.name, r.version, r.release, r.arch)
        # parsed: "missing", "(Permission denied)"; rpm that cannot start finishes with nothing to report
        self._verify_proc = proc.run(cmd, post=self._post, env={"LC_ALL": "C.UTF-8"}, done=self._on_verified)

    def _on_verified(self, _code: int, stdout: str, _stderr: str) -> None:
        if self._closed or "verify" not in self._busy:
            return
        self._busy.pop("verify")
        self.verify = local_rpm.parse_verify(stdout)
        self._view.show_files(files_text(self.rpm, self.verify))
        self._render()

    # ---------------------------------------------------------------- installing

    def install(self) -> None:
        if self._helper_busy() or not self.can_install():
            return
        self.changed_system = True
        self._busy["install"] = ""  # the button waits for the transaction
        self._render()
        self._view.run_transaction(self.request(), _("Installing {name}").format(name=self.rpm.name), self._installed)

    def _installed(self, ok: bool) -> None:
        self._busy.pop("install", None)
        if ok:
            self._view.close_installed()
        elif not self._closed:
            self._render()

    # ---------------------------------------------------------------- showing it

    def _show_deps(self) -> None:
        if self.rpm is not None:
            self._view.show_deps(deps_doc(self.rpm, self.target, self.preview))

    def _blocked(self) -> bool:
        return bool(self.error) or (self.preview is not None and not self.preview.ok)

    def notes(self) -> list[Note]:
        r, t, p = self.rpm, self.target, self.preview
        out = []
        if self._blocked():
            out.append(note(ERROR, bold(_("Cannot be installed."))))
            reason = (self.error or "\n".join(p.problems)).splitlines()
            if len(reason) > MAX_REASON_LINES:  # the solver's whole story is in the Dependencies tab
                reason = reason[:MAX_REASON_LINES] + ["… " + _("(the full text is in the Dependencies tab)")]
            out.append(note(INDENT, *lines("\n".join(reason))))
        elif t is not None:
            out.append(state_note(t, r))
        if r is not None and not self.error:
            out.append(signature_note(r))
            if t is not None:
                out.append(repo_note(t, r))
            if r.scripts:
                out.append(note(WARN, _("Runs scripts as root when it is installed or removed (see the Scripts "
                                        "tab).")))
        if self.verify is not None:
            out += verify_notes(self.verify)
        if self.marks:
            out.append(note(INFO, ngettext(
                "{n} change marked in the main window is not part of this and stays marked.",
                "{n} changes marked in the main window are not part of this and stay marked.",
                self.marks).format(n=self.marks)))
        return out

    def size_line(self) -> list[Span]:
        p = self.preview
        if self._choice_problem:
            return lines(self._choice_problem)
        if p is None or not p.ok or self.error:
            return []
        others = [i for i in p.items if i.repo_id != "@commandline"]
        parts = []
        if others:
            parts.append([ngettext("Also changes {n} more package, see the Dependencies tab.",
                                   "Also changes {n} more packages, see the Dependencies tab.",
                                   len(others)).format(n=len(others))])
        parts.append(filled(_("To download: {size}."), size=bold(human_size(sum(i.download_size for i in others)))))
        parts.append(filled(_("Disk space change: {size}."), size=bold(signed_size(p.size_change))))
        return joined(parts, ["   "])

    def _render(self) -> None:
        """Header, size line, buttons and status from what is known so far."""
        if self._closed:
            return
        t, p, blocked = self.target, self.preview, self._blocked()
        v = self._view
        v.show_notes(self.notes())
        v.show_sizes(self.size_line())
        ok = p is not None and p.ok and not self.error and not self._choice_problem
        v.show_warning(removal_warning(p) if ok else "")
        v.show_command(dnf5_command(self.request()) if t is not None and not blocked else None)
        label, icon = BUTTONS[t.action if t is not None else "install"]
        v.show_button(InstallButton(_(label), icon, not blocked, self.can_install()))
        v.show_status(" ".join(text for text in self._busy.values() if text))

