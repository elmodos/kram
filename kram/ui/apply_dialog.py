"""'Apply changes' preview: everything the transaction will do, dependencies included, before anything runs."""
import re
from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.marks import dnf5_command
from ..core.model import Recommendation, TransactionPreview
from ..core.origin import display_repo
from ..core.session import current_session
from ..helper.kram_helper import space_shortfall
from ..i18n import N_, _, ngettext
from .group_icons import group_icon
from .package_model import human_size

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


def _rec_label(rec: Recommendation) -> str:
    """What a recommendation installs, by package name; "name >= 1.2" becomes "name"."""
    if rec.brings:
        return ", ".join(rec.brings)
    m = re.fullmatch(r"([^\s()]+)(\s*[<>=]+.*)?", rec.what)
    return m.group(1) if m else rec.what.removeprefix("(").removesuffix(")")


def _fit_columns(tree: QTreeWidget, flexible: int = 0) -> None:
    """Column `flexible` takes the spare width as the window resizes, and gives up room first when it is short;
    the others fit their contents."""
    header = tree.header()
    header.setStretchLastSection(False)
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(flexible, QHeaderView.ResizeMode.Stretch)


class ChangesTree(QTreeWidget):
    """Every package a transaction touches, grouped by what happens to it."""

    def __init__(self, basearch: str = "x86_64", parent=None):
        super().__init__(parent)
        self._basearch = basearch
        self.setHeaderLabels([_("Package"), _("Version"), _("Repository"), _("Size")])
        # the name is what the user reads; a long version ("1:9.18.51^git20261003.d0a87358-2 → …") gives way instead
        _fit_columns(self, flexible=1)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)  # keeps both ends of "old → new"

    def set_basearch(self, basearch: str) -> None:
        self._basearch = basearch

    def fill(self, preview: TransactionPreview) -> None:
        self.clear()
        bold = QFont(self.font())
        bold.setBold(True)
        for action, title, color in GROUP_SECTIONS:
            groups = [g for g in preview.groups if g.action == action]
            if not groups:
                continue
            top = QTreeWidgetItem([f"{_(title)} ({len(groups)})"])
            top.setFont(0, bold)
            top.setForeground(0, QBrush(QColor(color)))
            for g in groups:
                row = QTreeWidgetItem(top, [g.name])
                row.setIcon(0, group_icon(g.id))
                row.setToolTip(0, g.id)
            self.addTopLevelItem(top)
            for item in (top, *(top.child(n) for n in range(top.childCount()))):
                item.setFirstColumnSpanned(True)  # spanned only once in the tree; names must not widen the column
            top.setExpanded(True)
        for title, color, pred in GROUPS:
            items = [i for i in preview.items if pred(i)]
            if not items:
                continue
            top = QTreeWidgetItem([f"{_(title)} ({len(items)})"])
            top.setFont(0, bold)
            if color:
                top.setForeground(0, QBrush(QColor(color)))
            for i in items:
                name = i.name if i.arch in ("noarch", self._basearch) else f"{i.name}.{i.arch}"
                if i.action == "reason":
                    version = f"→ {_(REASON_TEXT[i.reason]) if i.reason in REASON_TEXT else i.reason}"
                else:
                    version = f"{i.old_evr} → {i.evr}" if i.old_evr else i.evr
                size = human_size(i.download_size if i.download_size else i.install_size)
                row = QTreeWidgetItem(top, [name, version, display_repo(i.repo_id), size])
                row.setToolTip(1, version)  # in full, whatever is left of it on screen
                if i.before:
                    row.setIcon(0, QIcon.fromTheme("dialog-warning"))
                    row.setToolTip(0, _("Installed before “{group}”: it was there with the system or for something "
                                        "else, and removing the group takes it too.").format(group=i.before))
            self.addTopLevelItem(top)
            top.setFirstColumnSpanned(True)  # a group title must not widen the name column
            top.setExpanded(True)


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


class RecommendationsList(QWidget):
    """A checkbox per recommendation of the packages being installed. Unchecking one puts every package that
    provides it in `exclude`; the owner resolves again and calls `fill` with the result."""
    toggled = Signal()

    def __init__(self, exclude: set[str], parent=None):
        super().__init__(parent)
        self.exclude = set(exclude)
        self._sizes: dict[str, tuple] | None = None  # what each adds, from the first resolve: later ones skip it
        # a label over a plain list, like the changes above: a group box frame nests badly in some styles
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        hint = QLabel("<b>{}</b> {}".format(
            _("Recommended packages."),
            _("Not required, but suggested by the packages being installed. Uncheck what you do not want.")))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Recommended package"), _("Recommended by"), _("Adds")])
        _fit_columns(self.tree)
        self.tree.itemChanged.connect(self._on_changed)
        lay.addWidget(self.tree)

    def fill(self, preview: TransactionPreview) -> None:
        if self._sizes is None:
            self._sizes = {r.what: (r.size, r.count, r.exact) for r in preview.recommendations}
        tree = self.tree
        nested_open = any(tree.topLevelItem(i).childCount() and tree.topLevelItem(i).isExpanded()
                          for i in range(tree.topLevelItemCount()))
        tree.blockSignals(True)
        tree.clear()
        nested = [r for r in preview.recommendations if not r.direct]
        parent = None
        if nested:
            parent = QTreeWidgetItem([_("Recommended by dependencies ({n})").format(n=len(nested))])
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)
        for rec in preview.recommendations:
            item = QTreeWidgetItem([_rec_label(rec), ", ".join(rec.by) or "—", self._adds(rec)])
            item.setData(0, Qt.ItemDataRole.UserRole, rec)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if rec.checked else Qt.CheckState.Unchecked)
            tip = rec.what if rec.by else _("Pulled in because it complements packages being installed "
                                            "(language support, plugins).")
            item.setToolTip(0, tip)
            if rec.direct:
                tree.addTopLevelItem(item)
            else:
                parent.addChild(item)
        if parent is not None:
            tree.addTopLevelItem(parent)
            parent.setExpanded(nested_open or not any(r.direct for r in preview.recommendations))
        tree.blockSignals(False)

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

    def _on_changed(self, item: QTreeWidgetItem, column: int) -> None:
        rec = item.data(0, Qt.ItemDataRole.UserRole)
        if rec is None or column != 0:
            return
        if item.checkState(0) == Qt.CheckState.Checked:
            self.exclude -= set(rec.excludes)
        else:
            self.exclude |= set(rec.excludes)
        self.toggled.emit()


class ApplyDialog(QDialog):
    def __init__(self, preview: TransactionPreview, request: dict, basearch: str = "x86_64", parent=None,
                 resolve: Resolver | None = None):
        super().__init__(parent)
        self.setWindowTitle(_("Apply changes"))
        self.resize(820, 680)
        self.request = request
        self._resolve = resolve
        self._preview = preview
        self._generation = 0
        self._closed = False

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>{}</b> {}".format(_("The following changes will be made."), _("Review the list before applying."))))

        # marked changes the resolver left out (see TransactionPreview.skipped): above the list, so it is not missed
        self.skipped_label = QLabel()
        self.skipped_label.setWordWrap(True)
        self.skipped_label.setStyleSheet("color: #c03030; font-weight: bold")
        lay.addWidget(self.skipped_label)
        self.skipped_text = QPlainTextEdit()
        self.skipped_text.setReadOnly(True)
        self.skipped_text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.skipped_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.skipped_text.setFixedHeight(110)
        lay.addWidget(self.skipped_text)

        self.tree = ChangesTree(basearch)
        self.recs_box = RecommendationsList(set(request.get("exclude_weak", ())))
        self.recs_box.toggled.connect(self._rec_toggled)
        self.recs = self.recs_box.tree

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.tree)
        split.addWidget(self.recs_box)
        split.setChildrenCollapsible(False)
        split.setSizes([360, 240])
        lay.addWidget(split, 1)

        self.sizes = QLabel()
        lay.addWidget(self.sizes)
        # groups whose packages are already in place: why the list has no packages (see groups_only_note)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setVisible(False)
        lay.addWidget(self.note)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #c03030; font-weight: bold")
        lay.addWidget(self.warning)
        # not enough free space: Apply stays off (see _check_space)
        self.space = QLabel()
        self.space.setWordWrap(True)
        self.space.setStyleSheet("color: #c03030; font-weight: bold")
        self.space.setVisible(False)
        lay.addWidget(self.space)

        self.cmd = QPlainTextEdit()
        self.cmd.setReadOnly(True)
        self.cmd.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.cmd.setFixedHeight(80)
        box = QGroupBox(_("Equivalent command"))
        QVBoxLayout(box).addWidget(self.cmd)
        lay.addWidget(box)

        self.download_only = QCheckBox(_("Download packages only"))
        self.download_only.toggled.connect(self._show_command)
        self.download_only.toggled.connect(self._check_space)
        lay.addWidget(self.download_only)

        buttons = QDialogButtonBox()
        self.ok = buttons.addButton(_("Apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        self.ok.setDefault(True)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._show(preview)
        self.recs_box.setVisible(bool(preview.recommendations))

    def done(self, result: int) -> None:
        self._closed = True  # results that arrive later are for a dialog that is gone (it is deleted after use)
        super().done(result)

    def _show(self, preview: TransactionPreview) -> None:
        self._preview = preview
        self.tree.fill(preview)
        self.recs_box.fill(preview)
        self.sizes.setText(
            _("To download: {size}.").format(size=f"<b>{human_size(preview.download_size)}</b>") + "   "
            + _("Disk space change: {size}.").format(size=f"<b>{signed_size(preview.size_change)}</b>"))

        note = groups_only_note(preview) if preview.groups and not preview.items else ""
        self.note.setText(note)
        self.note.setVisible(bool(note))
        warning = removal_warning(preview)
        self.warning.setText(warning)
        self.warning.setVisible(bool(warning))
        self._show_skipped(preview)
        self._show_command()
        self._check_space()

    def _check_space(self) -> None:
        """Say when the disk is too full for the transaction, and keep Apply off then: rpm would refuse it only
        after the download. A download alone may still fit."""
        preview = self._preview
        download_only = self.download_only.isChecked()
        short = shortfall(preview, download_only)
        text = ""
        if short:
            mount, missing = short[0]
            text = "⚠ " + _("Not enough disk space on {mount}: {size} more is needed.").format(
                mount=mount, size=human_size(missing))
            if not download_only and not shortfall(preview, True):
                text += " " + _("The download alone fits: “Download packages only” can fetch the packages now.")
        self.space.setText(text)
        self.space.setVisible(bool(text))
        self.ok.setEnabled(bool(preview.items or preview.groups) and not short)

    def _show_skipped(self, preview: TransactionPreview) -> None:
        nothing = not preview.items and not preview.groups
        self.ok.setEnabled(not nothing)
        if preview.skipped:
            text = (_("⚠ None of the marked changes can be carried out:") if nothing else
                    _("⚠ Some marked changes cannot be carried out and are left out; the rest can be applied:"))
        elif nothing:
            text = _("Nothing to do: the marked changes are already in place.")
        else:
            text = ""
        self.skipped_label.setText(text)
        self.skipped_label.setVisible(bool(text))
        self.skipped_text.setPlainText("\n".join(preview.skipped))
        self.skipped_text.setVisible(bool(preview.skipped))

    def _show_command(self) -> None:
        self.cmd.setPlainText(dnf5_command({**self.request, "download_only": self.download_only.isChecked()}))

    def _rec_toggled(self) -> None:
        request = {k: v for k, v in self.request.items() if k != "exclude_weak"}
        if self.recs_box.exclude:
            request["exclude_weak"] = sorted(self.recs_box.exclude)
        self.request = request
        if self._resolve is None:
            return
        self._generation += 1
        generation = self._generation
        self.recs.setEnabled(False)
        self.ok.setEnabled(False)
        self.sizes.setText(_("Resolving dependencies…"))

        def done(preview: TransactionPreview) -> None:
            if self._closed or generation != self._generation:
                return
            self.recs.setEnabled(True)
            if preview.ok:
                self._show(preview)  # enables Apply when something is left to do
            else:
                self.sizes.setText(_("These choices cannot be carried out:") + " " + preview.problems[0][:300])

        def failed(error: BaseException) -> None:
            if not self._closed and generation == self._generation:
                self.recs.setEnabled(True)
                self.sizes.setText(_("Could not resolve the changes:\n\n{error}").format(error=error))

        self._resolve(request, done, failed)
