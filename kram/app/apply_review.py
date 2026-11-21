"""Reviewing a transaction before it runs ("Apply changes", and the package file dialog's Changes): what it does,
grouped; what it costs on disk and whether that fits; warnings for removals that hurt; the recommendations the user
may leave out, resolving again for each; and the equivalent dnf5 command. The front end draws what `ApplyReview`
tells its `ApplyReviewView`."""
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..core.marks import dnf5_command
from ..core.model import PreviewItem, Recommendation, TransactionPreview
from ..core.origin import display_repo
from ..core.session import current_session
from ..helper.kram_helper import space_shortfall
from ..i18n import N_, _, ngettext
from .columns import human_size
from .doc import Span, bold, filled
from .ports import view_ref

# Removing any of these leaves a system that may not boot or log in; worth a loud warning even if dnf allows it.
CRITICAL = frozenset({
    "bash", "coreutils", "dnf5", "glibc", "kernel-core", "NetworkManager", "pam", "polkit", "rpm", "sddm",
    "shadow-utils", "sudo", "systemd", "util-linux", "plasma-workspace", "plasma-desktop", "kwin",
})

# (title, color, predicate over PreviewItem)
GROUPS = [
    (N_("To be installed"), "#2f7a1f", lambda i: i.action == "install" and i.reason == "user"),
    (N_("To be installed with groups"), "#2f7a1f", lambda i: i.action == "install" and i.reason == "group"),
    (N_("To be installed as dependencies"), "#2f7a1f", lambda i: i.action == "install" and i.reason not in ("user", "group")),
    (N_("To be upgraded"), "#1f5fa8", lambda i: i.action == "upgrade"),
    (N_("To be downgraded"), "#a86f1f", lambda i: i.action == "downgrade"),
    (N_("To be reinstalled"), "#1f5fa8", lambda i: i.action == "reinstall"),
    (N_("To be removed"), "#b02020", lambda i: i.action == "remove" and i.reason == "user" and not i.rotated),
    (N_("To be removed with groups"), "#b02020", lambda i: i.action == "remove" and i.reason == "group" and not i.rotated),
    (N_("To be removed as dependent or no longer needed"), "#b02020",
     lambda i: i.action == "remove" and i.reason not in ("user", "group") and not i.rotated),
    (N_("Oldest kernels removed to stay within the limit of kept versions"), "#808080", lambda i: i.rotated),
    (N_("Install reason changes"), None, lambda i: i.action == "reason"),
]
REASON_TEXT = {"user": N_("user"), "dependency": N_("dependency"), "weak": N_("weak dependency"), "group": N_("group"),
               "clean": N_("unneeded")}
# (action, title, color) for the comps groups at the top of the list
GROUP_SECTIONS = [
    ("install", N_("Groups to be installed"), "#2f7a1f"),
    ("upgrade", N_("Groups to be upgraded"), "#1f5fa8"),
    ("remove", N_("Groups to be removed"), "#b02020"),
]




def signed_size(n: int) -> str:
    return ("+" if n >= 0 else "−") + human_size(abs(n))


# (request, on_done(preview), on_error(exception)): resolves again on the dnf thread
Resolver = Callable[[dict, Callable[[TransactionPreview], None], Callable[[BaseException], None]], None]

# ---------------------------------------------------------------- the list of changes


@dataclass(frozen=True)
class ChangeRow:
    name: str
    version: str = ""
    repo: str = ""
    size: str = ""
    warning: str = ""       # a removal the user may not expect: the row's warning icon and its tooltip
    group_id: str = ""      # a comps group's row: its icon, and the id as tooltip


@dataclass(frozen=True)
class ChangeSection:
    title: str              # with its count
    color: str | None
    rows: tuple[ChangeRow, ...]
    groups: bool = False    # comps groups (names only), not packages


def change_sections(preview: TransactionPreview, basearch: str) -> list[ChangeSection]:
    """Every group and package the transaction touches, by what happens to it: groups first."""
    sections = []
    for action, title, color in GROUP_SECTIONS:
        groups = [g for g in preview.groups if g.action == action]
        if groups:
            sections.append(ChangeSection(f"{_(title)} ({len(groups)})", color,
                                          tuple(ChangeRow(g.name, group_id=g.id) for g in groups), groups=True))
    for title, color, pred in GROUPS:
        items = [i for i in preview.items if pred(i)]
        if items:
            sections.append(ChangeSection(f"{_(title)} ({len(items)})", color,
                                          tuple(_change_row(i, basearch) for i in items)))
    return sections


def _change_row(i: PreviewItem, basearch: str) -> ChangeRow:
    name = i.name if i.arch in ("noarch", basearch) else f"{i.name}.{i.arch}"
    if i.action == "reason":
        version = f"→ {_(REASON_TEXT[i.reason]) if i.reason in REASON_TEXT else i.reason}"
    else:
        version = f"{i.old_evr} → {i.evr}" if i.old_evr else i.evr
    size = human_size(i.download_size if i.download_size else i.install_size)
    warning = _("Installed before “{group}”: it was there with the system or for something else, and removing the "
                "group takes it too.").format(group=i.before) if i.before else ""
    return ChangeRow(name, version, display_repo(i.repo_id), size, warning)


# ---------------------------------------------------------------- texts


def shortfall(preview: TransactionPreview, download_only: bool) -> list[tuple[str, int]]:
    """[(mount point, bytes missing)] for applying the preview, or only downloading its packages."""
    if not preview.cache_dir:  # a preview made without one (a test): nothing to check against
        return []
    try:
        return space_shortfall(preview.to_download, 0 if download_only else preview.size_change, preview.cache_dir)
    except OSError:  # cannot tell: rpm still checks
        return []


def groups_only_note(preview: TransactionPreview) -> str:
    """Why a transaction of groups alone touches no package: what they need is already in place, so dnf only
    records the change of the groups. Without it the review looks broken: a group and "0 B"."""
    n = len(preview.groups)
    actions = {g.action for g in preview.groups}
    if actions == {"install"}:
        return ngettext("All packages of the group are already installed: dnf only records the group as installed.",
                        "All packages of the groups are already installed: dnf only records the groups as installed.",
                        n)
    if actions == {"remove"}:
        return ngettext("No package goes with the group (you installed them yourself, or something else needs "
                        "them): dnf only records the group as removed.",
                        "No package goes with the groups (you installed them yourself, or something else needs "
                        "them): dnf only records the groups as removed.", n)
    return _("No package changes: dnf only updates its record of the groups.")


def removal_warning(preview: TransactionPreview, session: tuple[str, frozenset[str]] | None = None) -> str:
    """A loud warning when essential packages, the desktop of the running session (`session`: see
    kram.core.session.current_session) or very many packages go away; "" otherwise."""
    # a rotated removal (the oldest kernel, next to a new one) leaves the package installed: no warning for it
    going = [i for i in preview.items if i.action == "remove" and not i.rotated]
    critical = sorted({i.name for i in going if i.name in CRITICAL})
    desktop, session_names = session if session is not None else current_session()
    ending = sorted({i.name for i in going if i.name in session_names})
    removed = len(going)
    warnings = []
    if ending:
        warnings.append(_("This removes the desktop you are using now ({desktop}: {names}): the session may stop "
                          "working, and you may not be able to log in to it again.").format(
            desktop=desktop, names=", ".join(ending)))
    if critical:
        warnings.append(_("Essential system packages will be removed: {names}.").format(names=", ".join(critical)))
    older = sorted({i.name for i in going if i.before})
    if older:
        shown = ", ".join(older[:8]) + (", …" if len(older) > 8 else "")
        warnings.append(ngettext(
            "{n} package was installed before the group that takes it, with the system or for something else: {names}.",
            "{n} packages were installed before the group that takes them, with the system or for something else: "
            "{names}.", len(older)).format(n=len(older), names=shown))
    if removed >= 20:
        warnings.append(ngettext("{n} package will be removed.", "{n} packages will be removed.", removed).format(n=removed))
    return "⚠ " + " ".join(warnings) + " " + _("Make sure this is what you want.") if warnings else ""


def size_line(preview: TransactionPreview) -> list[Span]:
    return (filled(_("To download: {size}."), size=bold(human_size(preview.download_size))) + ["   "]
            + filled(_("Disk space change: {size}."), size=bold(signed_size(preview.size_change))))


def skipped_title(preview: TransactionPreview) -> str:
    """Above the marked changes the resolver left out (TransactionPreview.skipped), or why there is nothing."""
    nothing = not preview.items and not preview.groups
    if preview.skipped:
        return (_("⚠ None of the marked changes can be carried out:") if nothing else
                _("⚠ Some marked changes cannot be carried out and are left out; the rest can be applied:"))
    return _("Nothing to do: the marked changes are already in place.") if nothing else ""


def space_text(preview: TransactionPreview, download_only: bool) -> str:
    """Why Apply is off when the disk is too full: rpm would refuse only after the download. "" when it fits."""
    short = shortfall(preview, download_only)
    if not short:
        return ""
    mount, missing = short[0]
    text = "⚠ " + _("Not enough disk space on {mount}: {size} more is needed.").format(
        mount=mount, size=human_size(missing))
    if not download_only and not shortfall(preview, True):
        text += " " + _("The download alone fits: “Download packages only” can fetch the packages now.")
    return text


# ---------------------------------------------------------------- recommendations


def rec_label(rec: Recommendation) -> str:
    """What a recommendation installs, by package name; "name >= 1.2" becomes "name"."""
    if rec.brings:
        return ", ".join(rec.brings)
    m = re.fullmatch(r"([^\s()]+)(\s*[<>=]+.*)?", rec.what)
    return m.group(1) if m else rec.what.removeprefix("(").removesuffix(")")


@dataclass(frozen=True)
class RecRow:
    rec: Recommendation
    label: str
    by: str
    adds: str
    tip: str


class Recommendations:
    """A checkbox per recommendation of the packages being installed. Unchecking one puts every package that
    provides it in `exclude`; the owner resolves again and shows the rows of the result."""

    def __init__(self, exclude: set[str]):
        self.exclude = set(exclude)
        self._sizes: dict[str, tuple] | None = None  # what each adds, from the first resolve: later ones skip it

    def rows(self, preview: TransactionPreview) -> tuple[list[RecRow], list[RecRow]]:
        """(the recommendations of the marked packages, those of their dependencies)."""
        if self._sizes is None:
            self._sizes = {r.what: (r.size, r.count, r.exact) for r in preview.recommendations}
        direct, nested = [], []
        for rec in preview.recommendations:
            tip = rec.what if rec.by else _("Pulled in because it complements packages being installed "
                                            "(language support, plugins).")
            row = RecRow(rec, rec_label(rec), ", ".join(rec.by) or "—", self._adds(rec), tip)
            (direct if rec.direct else nested).append(row)
        return direct, nested

    @staticmethod
    def nested_title(n: int) -> str:
        return _("Recommended by dependencies ({n})").format(n=n)

    def _adds(self, rec: Recommendation) -> str:
        if not rec.checked:
            return _("still installed: something else requires it") if rec.needed else "—"
        size, count, exact = rec.size, rec.count, rec.exact
        if not exact and self._sizes.get(rec.what, (None, 0, False))[2]:
            size, count, exact = self._sizes[rec.what]
        if size is None:
            return ""
        if exact:
            return ngettext("+{size}, {n} package", "+{size}, {n} packages", count).format(size=human_size(size), n=count)
        return f"+{human_size(size)}"

    def set_checked(self, rec: Recommendation, checked: bool) -> None:
        if checked:
            self.exclude -= set(rec.excludes)
        else:
            self.exclude |= set(rec.excludes)

    def request(self, request: dict) -> dict:
        """`request` with the packages left out."""
        request = {k: v for k, v in request.items() if k != "exclude_weak"}
        if self.exclude:
            request["exclude_weak"] = sorted(self.exclude)
        return request


# ---------------------------------------------------------------- the review


class ApplyReviewView(Protocol):
    def show_preview(self, preview: TransactionPreview, sections: list[ChangeSection],
                     recs: tuple[list[RecRow], list[RecRow]]) -> None:
        """The changes and the recommendations of a (new) preview."""
        ...

    def show_texts(self, sizes: list[Span], note: str, warning: str, skipped_title: str, skipped: str) -> None: ...

    def show_space(self, text: str) -> None: ...

    def show_command(self, text: str) -> None: ...

    def set_can_apply(self, on: bool) -> None: ...

    def set_resolving(self, busy: bool, text: str | None = None) -> None:
        """`busy`: the recommendations resolve again, the list is off. `text`, when given, replaces the size line:
        what is going on, or why it could not be done."""
        ...


class ApplyReview:
    def __init__(self, preview: TransactionPreview, request: dict, basearch: str, view: ApplyReviewView,
                 resolve: Resolver | None = None):
        self.request = request
        self.preview = preview
        self.download_only = False
        self.recs = Recommendations(set(request.get("exclude_weak", ())))
        self._basearch, self._view, self._resolve = basearch, view_ref(view), resolve
        self._generation = 0
        self._closed = False

    def start(self) -> None:
        self._show(self.preview)

    def close(self) -> None:
        self._closed = True  # results that arrive later are for a dialog that is gone

    def result(self) -> dict:
        """The request to run: with the recommendations left out, and download only if chosen."""
        return {**self.request, "download_only": True} if self.download_only else self.request

    def set_download_only(self, on: bool) -> None:
        self.download_only = on
        self._show_command()
        self._check_space()

    def recs_changed(self) -> None:
        """A recommendation was checked or unchecked (`recs.set_checked`): resolve again without what is left out."""
        self.request = self.recs.request(self.request)
        if self._resolve is None:
            return
        self._generation += 1
        generation = self._generation
        self._view.set_can_apply(False)
        self._view.set_resolving(True, _("Resolving dependencies…"))

        def done(preview: TransactionPreview) -> None:
            if self._closed or generation != self._generation:
                return
            if preview.ok:
                self._view.set_resolving(False)
                self._show(preview)  # enables Apply when something is left to do
            else:
                self._view.set_resolving(False, _("These choices cannot be carried out:") + " " + preview.problems[0][:300])

        def failed(error: BaseException) -> None:
            if not self._closed and generation == self._generation:
                self._view.set_resolving(False, _("Could not resolve the changes:\n\n{error}").format(error=error))

        self._resolve(self.request, done, failed)

    def _show(self, preview: TransactionPreview) -> None:
        self.preview = preview
        self._view.show_preview(preview, change_sections(preview, self._basearch), self.recs.rows(preview))
        note = groups_only_note(preview) if preview.groups and not preview.items else ""
        self._view.show_texts(size_line(preview), note, removal_warning(preview), skipped_title(preview),
                              "\n".join(preview.skipped))
        self._show_command()
        self._check_space()

    def _show_command(self) -> None:
        self._view.show_command(dnf5_command({**self.request, "download_only": self.download_only}))

    def _check_space(self) -> None:
        text = space_text(self.preview, self.download_only)
        self._view.show_space(text)
        self._view.set_can_apply(bool(self.preview.items or self.preview.groups) and not text)
