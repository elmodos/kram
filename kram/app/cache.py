"""Settings → Cleanup: the size of each package cache and cleaning it; rpm's leftover configuration files
(.rpmsave, .rpmnew), comparing and deleting them. `Cleanup` measures and searches on the dnf thread, asks before
it deletes (Ui port) and runs what needs root through the helper; the front end draws what it tells its
`CleanupView`."""
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..core.cache import PACKAGEKIT_BLOCKED, CacheReport, clean_user_cache, measure
from ..core.leftovers import Kind, Leftover, LeftoverReport, classify, diff
from ..core.leftovers import scan as scan_leftovers
from ..core.worker import DnfWorker
from ..i18n import N_, _, ngettext
from .columns import human_size
from .ports import CANCEL, Button, Question, Ui, view_ref

METADATA, USER, PACKAGEKIT = "dnf_metadata", "user", "packagekit"
# the field of CacheReport, which is also the helper's target (except USER, cleaned without the helper); icon names
# in the order to try: not every theme has them, and a system with GNOME Software has no Discover logo
CACHES = (
    ("dnf_packages", ("package-x-generic",), N_("DNF: downloaded packages"),
     N_("Left by interrupted transactions and “download only”."), N_("Clean")),
    (METADATA, ("application-x-sqlite3", "text-x-generic"), N_("DNF: repository metadata"),
     N_("What Kram and dnf know about the available packages."), N_("Download Again…")),
    (USER, ("user-identity", "system-users"), N_("DNF: cache of your user"),
     N_("Written by dnf when it runs without root. Kram does not use it."), N_("Clean")),
    (PACKAGEKIT, ("plasmadiscover", "system-software-install"), N_("Discover / GNOME Software"),
     N_("Packages downloaded for offline updates and never removed."), N_("Clean")),
)


LEFTOVERS_ICONS = ("document-properties", "preferences-other")
# run_helper(request, title, done(final event, or None if it failed))
RunHelper = Callable[[dict, str, Callable[[dict | None], None]], None]


@dataclass(frozen=True)
class CacheLine:
    target: str
    shown: bool        # this system has the cache
    path: str = ""     # where the files are, as the user reads it
    folder: str = ""   # a folder that exists, for the link
    size: str = ""
    files: str = ""    # "" where the number says nothing
    can_clean: bool = False


@dataclass(frozen=True)
class LeftoverLine:
    leftover: Leftover
    icons: tuple[str, ...]
    description: str
    when: str          # date and size, two lines
    can_compare: bool
    compare_tip: str
    can_delete: bool


class CleanupView(Protocol):
    def show_measuring(self) -> None:
        """The sizes are being counted: "…", and no Clean button meanwhile."""
        ...

    def show_caches(self, lines: list[CacheLine]) -> None: ...

    def set_clean_enabled(self, target: str, on: bool) -> None: ...

    def show_note(self, text: str | None) -> None:
        """A warning under the list (with "⚠"), or none."""
        ...

    def show_leftovers_status(self, text: str) -> None: ...

    def show_leftovers(self, lines: list[LeftoverLine], status: str, can_search_root: bool,
                       can_delete_unused: bool) -> None: ...

    def show_diff(self, leftover: Leftover, text: str) -> None: ...


def describe(leftover: Leftover) -> str:
    package = leftover.package
    if leftover.kind is Kind.ORPHAN:
        return _("A copy of a file that no longer exists. Nothing uses it.")
    if leftover.kind is Kind.NEW:
        text = (_("The new default of {package}, not applied because the file had been changed.") if package
                else _("A package's new default, not applied because the file had been changed."))
        return text.format(package=package) + " " + _("Compare and take over what you need, then delete it.")
    text = (_("Your earlier version, put aside by {package}.") if package
            else _("Your earlier version, put aside by a package."))
    return text.format(package=package) + " " + _("Compare and take over your changes, then delete it.")


class Cleanup:
    def __init__(self, dnf: DnfWorker, view: CleanupView, ui: Ui, clean_system: Callable[[str, Callable[[], None]], None],
                 run_helper: RunHelper | None = None):
        """`clean_system(target, done)` runs the helper's clean_cache; `run_helper` any other request, None when
        there is no helper (then nothing here needs root)."""
        self._dnf, self._view, self._ui = dnf, view_ref(view), ui
        self._clean_system, self._run_helper = clean_system, run_helper
        self._closed = False
        self.leftovers = LeftoverReport([], 0)

    def close(self) -> None:
        self._closed = True  # results that arrive later are for a dialog that is gone

    def start(self) -> None:
        self.refresh()
        self.refresh_leftovers()

    # ---------------------------------------------------------------- caches

    def refresh(self) -> None:
        if self._closed:
            return
        self._view.show_measuring()
        self._dnf.submit(measure, self._show, lambda e: self._note(
            _("Could not count the caches: {error}").format(error=e)))

    def _note(self, text: str | None) -> None:
        if not self._closed:
            self._view.show_note(text)

    def _show(self, report: CacheReport) -> None:
        if self._closed:
            return
        locations = report.locations()
        lines = []
        blocked = report.packagekit_blocker if report.packagekit is not None else None
        for target, *_rest in CACHES:
            usage = getattr(report, target)
            if usage is None:
                lines.append(CacheLine(target, False))
                continue
            shown, folder = locations[target]
            files = "" if target in (METADATA, USER) else \
                ngettext("{n} file", "{n} files", usage.files).format(n=usage.files)  # many small repodata files
            can_clean = (target == METADATA or usage.files > 0) and not (target == PACKAGEKIT and blocked)
            lines.append(CacheLine(target, True, shown, folder, human_size(usage.size), files, can_clean))
        self._view.show_caches(lines)
        self._note(_(PACKAGEKIT_BLOCKED[blocked]) if blocked else None)

    def clean(self, target: str) -> None:
        if target == USER:
            self._view.set_clean_enabled(USER, False)
            self._dnf.submit(clean_user_cache, lambda _result: self.refresh(), self._user_clean_failed)
            return
        if target != METADATA:
            self._clean_system(target, self.refresh)
            return
        self._ui.ask(Question(
            _("Download metadata again"),
            _("Delete the repository metadata and download it again?\n\nThis needs the internet and can take a few "
              "minutes. If the download fails, the available packages disappear from Kram until a Reload "
              "succeeds.")), lambda answer: answer == "yes" and self._clean_system(target, self.refresh))

    def _user_clean_failed(self, error: BaseException) -> None:
        if self._closed:
            return
        self.refresh()
        self._ui.warn(_("Cleanup"), _("Could not clean the cache: {error}").format(error=error))

    # ---------------------------------------------------------------- leftover configuration files

    def refresh_leftovers(self) -> None:
        self._view.show_leftovers_status(_("Searching…"))
        self._dnf.submit(scan_leftovers, self._show_leftovers, self._leftovers_failed)

    def _leftovers_failed(self, error: BaseException) -> None:
        if not self._closed:
            self._view.show_leftovers_status(_("Could not search: {error}").format(error=error))

    def _show_leftovers(self, report: LeftoverReport) -> None:
        if self._closed:
            return
        self.leftovers = report
        n = len(report.files)
        status = ngettext("{n} file found.", "{n} files found.", n).format(n=n) if n else _("Nothing found.")
        if report.unreadable:
            status += " " + ngettext("{n} folder only root can read was not searched.",
                                     "{n} folders only root can read were not searched.",
                                     report.unreadable).format(n=report.unreadable)
        helper = self._run_helper is not None
        self._view.show_leftovers([self._line(f) for f in report.files], status, bool(report.unreadable) and helper,
                                  helper and any(f.kind is Kind.ORPHAN for f in report.files))

    def _line(self, leftover: Leftover) -> LeftoverLine:
        icons = ("dialog-information",) if leftover.kind is Kind.NEW else ("text-x-generic", "document-new")
        when = time.strftime("%x", time.localtime(leftover.mtime)) + "\n" + human_size(leftover.size)
        if leftover.kind is Kind.ORPHAN:
            compare, tip = False, _("There is no current file to compare it with.")
        elif not leftover.comparable:
            compare, tip = False, _("Only root can read it. In a terminal: {command}").format(
                command=f"sudo diff -u {shlex.quote(leftover.current)} {shlex.quote(leftover.path)}")
        else:
            compare, tip = True, ""
        return LeftoverLine(leftover, icons, describe(leftover), when, compare, tip, self._run_helper is not None)

    def compare(self, leftover: Leftover) -> None:
        try:
            text = diff(leftover)
        except OSError as e:
            self._ui.warn(_("Compare"), _("Could not read the files: {error}").format(error=e.strerror))
            return
        self._view.show_diff(leftover, text or _("The files are the same."))

    def delete_unused(self) -> None:
        self.delete([f for f in self.leftovers.files if f.kind is Kind.ORPHAN])

    def delete(self, files: list[Leftover]) -> None:
        if not files or self._run_helper is None:
            return
        if len(files) == 1:
            question = _("Delete {path}?").format(path=files[0].path)
        else:
            question = ngettext("Delete {n} file?", "Delete {n} files?", len(files)).format(n=len(files))
        lines = ["\n".join(f.path for f in files)] if len(files) > 1 else []
        if any(f.kind is Kind.NEW for f in files):
            lines.append(_("The new default settings in it are lost: compare first to take over what you need."))
        elif any(f.kind is Kind.SAVED for f in files):
            lines.append(_("Your changes in it are lost, unless the current file has them too."))

        def answered(answer: str | None) -> None:
            if answer != "delete":
                return
            title = ngettext("Deleting {n} file", "Deleting {n} files", len(files)).format(n=len(files))
            self._run_helper({"op": "remove_leftovers", "paths": [f.path for f in files]}, title, deleted)

        def deleted(result: dict | None) -> None:
            if result is not None:
                gone = {f.path for f in files}
                self._show_leftovers(LeftoverReport([f for f in self.leftovers.files if f.path not in gone],
                                                    self.leftovers.unreadable))
            else:
                self.refresh_leftovers()  # part of them may be gone
        self._ui.ask(Question(_("Delete leftover files"), question,
                              (Button("delete", _("Delete"), "destructive"), CANCEL),
                              informative="\n\n".join(lines)), answered)

    def search_as_root(self) -> None:
        if self._run_helper is None:
            return

        def found(result: dict | None) -> None:
            if result is not None:
                self._dnf.submit(lambda: classify(result.get("files", []), result.get("unreadable", 0)),
                                 self._show_leftovers)
        self._run_helper({"op": "find_leftovers"}, _("Searching for leftover files"), found)
