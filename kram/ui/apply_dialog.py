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
from ..i18n import N_, _, ngettext
from .package_model import human_size

# Removing any of these leaves a system that may not boot or log in; worth a loud warning even if dnf allows it.
CRITICAL = frozenset({
    "bash", "coreutils", "dnf5", "glibc", "kernel-core", "NetworkManager", "pam", "polkit", "rpm", "sddm",
    "shadow-utils", "sudo", "systemd", "util-linux", "plasma-workspace", "plasma-desktop", "kwin",
})

# (title, color, predicate over PreviewItem)
GROUPS = [
    (N_("To be installed"), "#2f7a1f", lambda i: i.action == "install" and i.reason == "user"),
    (N_("To be installed as dependencies"), "#2f7a1f", lambda i: i.action == "install" and i.reason != "user"),
    (N_("To be upgraded"), "#1f5fa8", lambda i: i.action == "upgrade"),
    (N_("To be downgraded"), "#a86f1f", lambda i: i.action == "downgrade"),
    (N_("To be reinstalled"), "#1f5fa8", lambda i: i.action == "reinstall"),
    (N_("To be removed"), "#b02020", lambda i: i.action == "remove" and i.reason == "user"),
    (N_("To be removed as dependent or no longer needed"), "#b02020",
     lambda i: i.action == "remove" and i.reason != "user"),
    (N_("Install reason changes"), None, lambda i: i.action == "reason"),
]
REASON_TEXT = {"user": N_("user"), "dependency": N_("dependency"), "weak": N_("weak dependency"), "clean": N_("unneeded")}


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


def _fit_columns(tree: QTreeWidget) -> None:
    """The first (name) column takes the spare width as the window resizes; the others fit their contents."""
    header = tree.header()
    header.setStretchLastSection(False)
    header.setSectionResizeMode(QHeaderView.ResizeToContents)
    header.setSectionResizeMode(0, QHeaderView.Stretch)


class ChangesTree(QTreeWidget):
    """Every package a transaction touches, grouped by what happens to it."""

    def __init__(self, basearch: str = "x86_64", parent=None):
        super().__init__(parent)
        self._basearch = basearch
        self.setHeaderLabels([_("Package"), _("Version"), _("Repository"), _("Size")])
        _fit_columns(self)

    def set_basearch(self, basearch: str) -> None:
        self._basearch = basearch

    def fill(self, preview: TransactionPreview) -> None:
        self.clear()
        bold = QFont(self.font())
        bold.setBold(True)
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
                QTreeWidgetItem(top, [name, version, display_repo(i.repo_id), size])
            self.addTopLevelItem(top)
            top.setExpanded(True)


def removal_warning(preview: TransactionPreview) -> str:
    """A loud warning when essential packages or very many go away; "" otherwise."""
    critical = sorted({i.name for i in preview.items if i.action == "remove" and i.name in CRITICAL})
    removed = sum(1 for i in preview.items if i.action == "remove")
    warnings = []
    if critical:
        warnings.append(_("Essential system packages will be removed: {names}.").format(names=", ".join(critical)))
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
            parent.setFlags(Qt.ItemIsEnabled)
        for rec in preview.recommendations:
            item = QTreeWidgetItem([_rec_label(rec), ", ".join(rec.by) or "—", self._adds(rec)])
            item.setData(0, Qt.UserRole, rec)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if rec.checked else Qt.Unchecked)
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
        rec = item.data(0, Qt.UserRole)
        if rec is None or column != 0:
            return
        if item.checkState(0) == Qt.Checked:
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

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>{}</b> {}".format(_("The following changes will be made."), _("Review the list before applying."))))

        self.tree = ChangesTree(basearch)
        self.recs_box = RecommendationsList(set(request.get("exclude_weak", ())))
        self.recs_box.toggled.connect(self._rec_toggled)
        self.recs = self.recs_box.tree

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.tree)
        split.addWidget(self.recs_box)
        split.setChildrenCollapsible(False)
        split.setSizes([360, 240])
        lay.addWidget(split, 1)

        self.sizes = QLabel()
        lay.addWidget(self.sizes)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #c03030; font-weight: bold")
        lay.addWidget(self.warning)

        self.cmd = QPlainTextEdit()
        self.cmd.setReadOnly(True)
        self.cmd.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.cmd.setFixedHeight(80)
        box = QGroupBox(_("Equivalent command"))
        QVBoxLayout(box).addWidget(self.cmd)
        lay.addWidget(box)

        self.download_only = QCheckBox(_("Download packages only"))
        lay.addWidget(self.download_only)

        buttons = QDialogButtonBox()
        self.ok = buttons.addButton(_("Apply"), QDialogButtonBox.AcceptRole)
        self.ok.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        self.ok.setDefault(True)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self._show(preview)
        self.recs_box.setVisible(bool(preview.recommendations))

    def _show(self, preview: TransactionPreview) -> None:
        self._preview = preview
        self.tree.fill(preview)
        self.recs_box.fill(preview)
        self.sizes.setText(
            _("To download: {size}.").format(size=f"<b>{human_size(preview.download_size)}</b>") + "   "
            + _("Disk space change: {size}.").format(size=f"<b>{signed_size(preview.size_change)}</b>"))

        warning = removal_warning(preview)
        self.warning.setText(warning)
        self.warning.setVisible(bool(warning))
        self.cmd.setPlainText(dnf5_command(self.request))

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
            if generation != self._generation:
                return
            self.recs.setEnabled(True)
            if preview.ok:
                self.ok.setEnabled(True)
                self._show(preview)
            else:
                self.sizes.setText(_("These choices cannot be carried out:") + " " + preview.problems[0][:300])

        def failed(error: BaseException) -> None:
            if generation == self._generation:
                self.recs.setEnabled(True)
                self.sizes.setText(_("Could not resolve the changes:\n\n{error}").format(error=error))

        self._resolve(request, done, failed)
