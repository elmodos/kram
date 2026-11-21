"""Settings → Repositories: which repositories are on, the changes the user makes to that, and the two ways out that
are not changes: showing a repository's packages, and removing the user's own repository files. `Repos` holds the
rules and texts; the front end's dialog shows the table and closes with what `choice()` says."""
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

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


@dataclass(frozen=True)
class ActionState:
    enabled: bool
    tooltip: str  # why not, when not


class ReposView(Protocol):
    def close_with_choice(self) -> None:
        """Close without applying anything: the user chose to see a repository's packages, or to remove some."""
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
                 installed: Counter | None = None):
        """`counts`: available packages per repo; `owners`: .repo file -> the package that owns it; `listed`: rows
        of the package list per repo (its Origin filter); `installed`: installed packages per repo they came from.
        `view.close_with_choice()` closes the dialog without applying anything, after a choice."""
        self._original = {r.id: r.enabled for r in repos}
        self.enabled = dict(self._original)
        self.repos = {r.id: r for r in repos}
        self._counts = counts
        self._ui, self._view = ui, view_ref(view)
        self._owners = owners or {}
        self._listed = listed or Counter()
        self._installed = installed or Counter()
        self.show_repo: str | None = None
        self.remove_repos: list[str] = []

    def lines(self) -> list[RepoLine]:
        """The enabled ones first, then by id."""
        out = []
        for r in sorted(self.repos.values(), key=lambda r: (not r.enabled, r.id)):
            if r.enabled and r.age_seconds is None:
                packages, tip = "—", _("No metadata yet: use Reload")
            else:
                packages, tip = (str(self._counts.get(r.id, 0)) if r.enabled else ""), ""
            out.append(RepoLine(r, packages, tip, str(r.priority), ORIGIN_LABEL[r.origin], ("origin", r.origin)))
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
                self._view.close_with_choice()  # nothing to apply: the main window runs the removal
            elif answer == "show":
                self.show_packages(repo_id)
        self._ui.ask(Question(_("Remove repository"), text, buttons, informative="\n\n".join(lines)), answered)
