"""Settings → COPR: the enabled projects (enable, disable, remove, show their packages) and finding new ones with the
Copr search API. The front end draws what `CoprProjects` tells its `CoprView`; the changes run through the helper."""
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..core import net
from ..core.copr import DEFAULT_HUB, PROJECT_RE, SEARCH_URL, CoprProject, parse_repo_id, parse_search, rank
from ..core.mainloop import Post
from ..core.model import CatalogSnapshot
from ..i18n import _, ngettext
from .ports import CANCEL, Button, Question, Ui, view_ref

# the Copr search API routinely takes 10-20 s to answer, whatever the result size
SEARCH_TIMEOUT_S = 60
SEARCH_LIMIT = 50
MISSING_BUILD_COLOR = "#c03030"


@dataclass(frozen=True)
class EnabledProject:
    """A row of the top table: a COPR repository on this system."""
    repo_id: str
    hub: str
    project: str
    enabled: bool
    packages: str   # in the repository; "" when it is off and so not loaded
    installed: str  # installed from it


@dataclass(frozen=True)
class ResultLine:
    project: CoprProject
    name: str         # with "(enabled)" when it is
    description: str
    tooltip: str      # the whole description, and the homepage
    builds: str       # "✓ fedora-45-x86_64" or "✗ …"
    builds_ok: bool
    builds_tip: str   # what it does build for, when not for this system


@dataclass(frozen=True)
class Buttons:
    enable: bool
    disable: bool
    remove: bool
    packages: bool
    add: bool


class CoprView(Protocol):
    def show_projects(self, projects: list[EnabledProject]) -> None: ...

    def show_results(self, results: list[ResultLine]) -> None: ...

    def show_search_status(self, text: str) -> None: ...

    def set_searching(self, on: bool) -> None:
        """A search runs: the Search button is off."""
        ...

    def select_first_result(self) -> None: ...


class CoprProjects:
    def __init__(self, view: CoprView, ui: Ui, post: Post, run_helper: Callable[[dict, str], object],
                 show_packages: Callable[[str], None]):
        """`run_helper(request, title)` runs a helper request with its progress; `show_packages(repo id)` shows a
        repository's packages in the main window."""
        self._view, self._ui, self._post = view_ref(view), ui, post
        self._run_helper, self._show_packages = run_helper, show_packages
        self._closed = False
        self._snap: CatalogSnapshot | None = None
        self.projects: list[EnabledProject] = []
        self.results: list[CoprProject] = []
        self._search_request: net.Request | None = None

    def close(self) -> None:
        self._closed = True  # results that arrive later are for a dialog that is gone
        if self._search_request is not None:
            self._search_request.cancel()

    # ---------------------------------------------------------------- enabled projects

    def set_catalog(self, snap: CatalogSnapshot, counts: Counter) -> None:
        if self._closed:  # the catalog's counts arrived after the dialog was closed
            return
        self._snap = snap
        installed = Counter(r.origin_repo for r in snap.rows if r.installed)
        coprs = [(repo, ref) for repo in snap.repos if (ref := parse_repo_id(repo.id)) is not None]
        coprs.sort(key=lambda c: c[1].project.lower())
        self.projects = [EnabledProject(repo.id, ref.hub, ref.project, repo.enabled,
                                        str(counts.get(repo.id, 0)) if repo.enabled else "",
                                        str(installed.get(repo.id, 0))) for repo, ref in coprs]
        self._view.show_projects(self.projects)
        self._show_results()  # "(enabled)" depends on the projects list

    def buttons(self, project: EnabledProject | None, result: CoprProject | None, typed: str) -> Buttons:
        """For the selected project, the selected search result and the text in the field."""
        sel = project is not None
        if result is not None:
            add = not self._is_enabled(result.full_name)
        else:
            text = typed.strip()
            add = bool(PROJECT_RE.match(text)) and not self._is_enabled(text)
        return Buttons(sel and not project.enabled, sel and project.enabled, sel, sel, add)

    def _is_enabled(self, full_name: str) -> bool:
        """The owner/project is on this system and on: enabling it again would do nothing. A disabled one can be
        enabled from the search too."""
        name = full_name.lower()
        return any(p.enabled and p.hub == DEFAULT_HUB and p.project.lower() == name for p in self.projects)

    def change(self, project: EnabledProject, action: str) -> None:
        """"enable" or "disable"."""
        self._copr(action, project.project, project.hub)

    def remove(self, project: EnabledProject) -> None:
        n = sum(1 for r in self._snap.rows if r.installed and r.origin_repo == project.repo_id) if self._snap else 0
        informative = ngettext(
            "{n} installed package comes from it. It stays installed but will no longer get updates "
            "(it will show as orphaned).",
            "{n} installed packages come from it. They stay installed but will no longer get updates "
            "(they will show as orphaned).", n).format(n=n) if n else ""
        buttons = (Button("remove", _("Remove"), "destructive"),
                   *((Button("show", _("Show packages")),) if n else ()), CANCEL)

        def answered(answer: str | None) -> None:
            if answer == "remove":
                self._copr("remove", project.project, project.hub)
            elif answer == "show":
                self._show_packages(project.repo_id)
        self._ui.ask(Question(_("Remove COPR project"),
                              _("Remove the {project} repository from the system?").format(project=project.project),
                              buttons, informative=informative), answered)

    def show_packages(self, project: EnabledProject) -> None:
        self._show_packages(project.repo_id)

    def _copr(self, action: str, project: str, hub: str) -> None:
        titles = {"enable": _("Enabling {project}"), "disable": _("Disabling {project}"),
                  "remove": _("Removing {project}")}
        request = {"op": "copr", "action": action, "project": project}
        if hub != DEFAULT_HUB:
            request["hub"] = hub
        self._run_helper(request, titles[action].format(project=project))

    # ---------------------------------------------------------------- search

    def search(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self._search_request is not None:  # superseded: its answer is dropped
            self._search_request.cancel()
        self._view.show_search_status(_("Searching… Copr can take up to a minute to answer."))
        self._view.set_searching(True)
        self._search_request = net.fetch(
            SEARCH_URL.format(hub=DEFAULT_HUB), params={"query": text, "limit": str(SEARCH_LIMIT)},
            timeout_s=SEARCH_TIMEOUT_S, post=self._post,
            done=lambda body: self._on_search_done(text, body), failed=self._on_search_failed)

    def _on_search_failed(self, error: net.NetError) -> None:
        self._search_request = None
        self._view.set_searching(False)
        self._view.show_search_status(_("Search failed: {error}").format(error=error))

    def _on_search_done(self, text: str, body: bytes) -> None:
        self._search_request = None
        self._view.set_searching(False)
        try:
            results = parse_search(json.loads(body))
        except (ValueError, AttributeError):
            self._view.show_search_status(_("Search failed: unexpected answer from Copr"))
            return
        self.results = results = rank(results, text)
        self._show_results()
        n = len(results)
        self._view.show_search_status(ngettext("{n} project found.", "{n} projects found.", n).format(n=n))
        if results:
            self._view.select_first_result()

    def _show_results(self) -> None:
        snap = self._snap
        if snap is None:
            return
        chroot = f"fedora-{snap.releasever}-{snap.basearch}"
        lines = []
        for p in self.results:
            ok = p.has_chroot(snap.releasever, snap.basearch)
            lines.append(ResultLine(
                p, p.full_name + ("  " + _("(enabled)") if self._is_enabled(p.full_name) else ""), p.description,
                p.description + (f"\n\n{p.homepage}" if p.homepage else ""), ("✓ " if ok else "✗ ") + chroot, ok,
                "" if ok else _("Builds exist for: {chroots}").format(chroots=", ".join(p.chroots) or "—")))
        self._view.show_results(lines)

    def enable(self, result: CoprProject | None, typed: str) -> None:
        """Enable the selected search result; without one, the owner/project typed in the field."""
        if result is None:
            text = typed.strip()  # allow enabling a typed owner/project without searching
            if PROJECT_RE.match(text) and not self._is_enabled(text):
                self._copr("enable", text, DEFAULT_HUB)
            return
        if self._is_enabled(result.full_name):
            return
        snap = self._snap
        if snap and not result.has_chroot(snap.releasever, snap.basearch):
            self._ui.ask(Question(_("No builds for this system"),
                                  _("{project} has no builds for Fedora {release} ({arch}). Enable it anyway?").format(
                                      project=result.full_name, release=snap.releasever, arch=snap.basearch)),
                         lambda answer: answer == "yes" and self._copr("enable", result.full_name, DEFAULT_HUB))
            return
        self._copr("enable", result.full_name, DEFAULT_HUB)
