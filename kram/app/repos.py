"""Settings → Repositories: which repositories are on, the changes the user makes to that, showing a repository's
packages, choosing its mirror and removing the user's own repository files. `Repos` holds the rules and texts; the
front end's dialog shows the table.

The dialog stays open for what is done from it: Mirrors… opens over it, and a removal runs over it, after which the
table shows the new state (`update`). Only Show packages closes it, because the packages are in the main window."""
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

from ..core.mirrors import source_of
from ..core.model import RepoInfo
from ..core.repo_files import Removal, removal
from ..i18n import _, ngettext
from .icons import ORIGIN_LABEL, IconRef
from .ports import CANCEL, Button, Question, Ui, view_ref

AUX_SUFFIXES = ("-debuginfo", "-source", "-debugsource")


@dataclass(frozen=True)
class RepoLine:
    repo: RepoInfo
    packages: str        # available packages; "—" without metadata yet, "" when off
    packages_tip: str
    priority: str
    origin: str
    origin_icon: IconRef
    mirror: str = ""       # "Automatic", or the host of the mirror the repository is pinned to; "" with none to choose
    mirror_tip: str = ""   # the pinned mirror's whole address


@dataclass(frozen=True)
class ReposData:
    """What the dialog shows, read again after every change. `counts`: available packages per repo; `owners`: .repo
    file -> the package that owns it; `listed`: rows of the package list per repo (its Origin filter); `installed`:
    installed packages per repo they came from; `variables`: releasever and basearch (kram.core.mirrors)."""
    repos: list[RepoInfo]
    counts: Counter = field(default_factory=Counter)
    owners: dict[str, str] = field(default_factory=dict)
    listed: Counter = field(default_factory=Counter)
    installed: Counter = field(default_factory=Counter)
    variables: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionState:
    enabled: bool
    tooltip: str  # why not, when not


class ReposView(Protocol):
    def close_with_choice(self) -> None:
        """Close without applying anything: the user chose to see a repository's packages in the main window."""
        ...


def is_aux(repo_id: str) -> bool:
    """A debuginfo or source repository: hidden unless asked for."""
    return repo_id.endswith(AUX_SUFFIXES)


def matches(repo: RepoInfo, needle: str, show_aux: bool) -> bool:
    needle = needle.strip().lower()
    if not show_aux and is_aux(repo.id):
        return False
    return not needle or needle in repo.id.lower() or needle in repo.name.lower()


class Repos:
    def __init__(self, repos: list[RepoInfo], counts: Counter, ui: Ui, view: ReposView, *,
                 owners: dict[str, str] | None = None, listed: Counter | None = None,
                 installed: Counter | None = None, variables: dict[str, str] | None = None,
                 on_remove: Callable[[list[str]], None] | None = None,
                 on_mirrors: Callable[[str], None] | None = None):
        """The arguments are those of `ReposData`. `on_remove(repo ids)` removes repositories and `on_mirrors(repo
        id)` shows a repository's mirrors, both while the dialog stays open; `view.close_with_choice()` closes it for
        Show packages."""
        self._ui, self._view = ui, view_ref(view)
        self._on_remove, self._on_mirrors = on_remove, on_mirrors
        self.show_repo: str | None = None
        self.remove_repos: list[str] = []   # the last removal asked for
        self.mirror_repo: str | None = None  # the last repository whose mirrors were asked for
        self.update(ReposData(repos, counts, owners or {}, listed or Counter(), installed or Counter(),
                              variables or {}))

    def update(self, data: ReposData) -> None:
        """Show `data`: after a change made from the dialog. Nothing can be pending then (removals and mirrors wait
        for the changes to be applied or undone), so the checkboxes start again from what is configured."""
        self._original = {r.id: r.enabled for r in data.repos}
        self.enabled = dict(self._original)
        self.repos = {r.id: r for r in data.repos}
        self._counts = data.counts
        self._owners = data.owners
        self._listed = data.listed
        self._installed = data.installed
        self._variables = data.variables

    def lines(self) -> list[RepoLine]:
        """The enabled ones first, then by id."""
        out = []
        for r in sorted(self.repos.values(), key=lambda r: (not r.enabled, r.id)):
            if r.enabled and r.age_seconds is None:
                packages, tip = "—", _("No metadata yet: use Reload")
            else:
                packages, tip = (str(self._counts.get(r.id, 0)) if r.enabled else ""), ""
            source = source_of(r, self._variables)
            mirror, mirror_tip = "", ""
            if source is not None:
                mirror, mirror_tip = (urlsplit(source.pinned).netloc, source.pinned) if source.pinned \
                    else (_("Automatic"), _("dnf chooses among the mirrors of the repository's list."))
            out.append(RepoLine(r, packages, tip, str(r.priority), ORIGIN_LABEL[r.origin], ("origin", r.origin),
                                mirror, mirror_tip))
        return out

    def set_enabled(self, repo_id: str, on: bool) -> None:
        self.enabled[repo_id] = on

    def changes(self) -> dict[str, bool]:
        """Repo id -> new enabled state, only for repos the user toggled."""
        return {i: on for i, on in self.enabled.items() if on != self._original[i]}

    def summary(self) -> str:
        n = len(self.changes())
        return ngettext("{n} repository will change.", "{n} repositories will change.", n).format(n=n) if n else ""

    # ---------------------------------------------------------------- show packages, remove

    def packages_blocker(self, repo_id: str) -> str | None:
        """Why the repository's packages cannot be shown now; None if they can."""
        if self.changes():
            return _("Apply or undo the changes first.")
        if not self._listed.get(repo_id):
            return _("None of its packages are in the list.")
        return None

    def removal_blocker(self, repo_id: str) -> str | None:
        """Why the repository cannot be removed; None if it can."""
        if self.changes():
            return _("Apply or undo the changes first.")
        path = self.repos[repo_id].file_path
        match removal(path, self._owners.get(path)):
            case Removal.OWNED:
                return _("The .repo file is part of the installed package {package}.").format(package=self._owners[path])
            case Removal.SYSTEM:
                return _("Configured by the system.")
            case Removal.NO_FILE:
                return _("Not configured in a file.")
        return None

    def actions(self, repo_id: str | None) -> tuple[ActionState, ActionState]:
        """Show packages and Remove for the selected repository."""
        def state(blocker):
            why = blocker(repo_id) if repo_id is not None else None
            return ActionState(repo_id is not None and why is None, why or "")
        return state(self.packages_blocker), state(self.removal_blocker)

    def mirrors_action(self, repo_id: str | None) -> ActionState:
        """Mirrors… for the selected repository: only a repository with a list of mirrors has anything to choose."""
        if repo_id is None:
            return ActionState(False, "")
        if self.changes():
            return ActionState(False, _("Apply or undo the changes first."))
        if source_of(self.repos[repo_id], self._variables) is None:
            return ActionState(False, _("This repository has a single address: there are no mirrors to choose from."))
        return ActionState(True, "")

    def show_mirrors(self, repo_id: str | None) -> None:
        if repo_id is not None and self.mirrors_action(repo_id).enabled:
            self.mirror_repo = repo_id
            if self._on_mirrors is not None:
                self._on_mirrors(repo_id)  # over this dialog, which stays open

    def show_packages(self, repo_id: str | None) -> None:
        if repo_id is not None and self.packages_blocker(repo_id) is None:
            self.show_repo = repo_id
            self._view.close_with_choice()  # nothing to apply: the main window shows the packages

    def remove(self, repo_id: str | None) -> None:
        if repo_id is None or self.removal_blocker(repo_id) is not None:
            return
        path = self.repos[repo_id].file_path
        in_file = sorted((r for r in self.repos.values() if r.file_path == path), key=lambda r: r.id)
        n = sum(self._installed.get(r.id, 0) for r in in_file)
        if len(in_file) == 1:
            text = _("Remove the repository {repo} from the system?").format(repo=repo_id)
            lines = [_("Its file {path} will be deleted.").format(path=path)]
        else:
            text = ngettext("The file {path} configures {n} repository. Remove it from the system?",
                            "The file {path} configures {n} repositories. Remove them all from the system?",
                            len(in_file)).format(path=path, n=len(in_file))
            lines = ["\n".join(f"• {r.id} — {r.name}" for r in in_file)]
        if n:
            lines.append(ngettext(
                "{n} installed package comes from it. It stays installed but will no longer get updates "
                "(it will show as orphaned).",
                "{n} installed packages come from it. They stay installed but will no longer get updates "
                "(they will show as orphaned).", n).format(n=n) if len(in_file) == 1 else ngettext(
                "{n} installed package comes from them. It stays installed but will no longer get updates "
                "(it will show as orphaned).",
                "{n} installed packages come from them. They stay installed but will no longer get updates "
                "(they will show as orphaned).", n).format(n=n))
        show = n and self.packages_blocker(repo_id) is None
        buttons = (Button("remove", _("Remove"), "destructive"),
                   *((Button("show", _("Show packages")),) if show else ()), CANCEL)

        def answered(answer: str | None) -> None:
            if answer == "remove":
                self.remove_repos = [r.id for r in in_file]
                if self._on_remove is not None:
                    self._on_remove(self.remove_repos)  # over this dialog, which then shows the list without them
            elif answer == "show":
                self.show_packages(repo_id)
        self._ui.ask(Question(_("Remove repository"), text, buttons, informative="\n\n".join(lines)), answered)
