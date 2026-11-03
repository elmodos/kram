"""'Apply changes' preview: everything the transaction will do, dependencies included, before anything runs."""
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..core.marks import dnf5_command
from ..core.model import TransactionPreview
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


def _signed_size(n: int) -> str:
    return ("+" if n >= 0 else "−") + human_size(abs(n))


class ApplyDialog(QDialog):
    def __init__(self, preview: TransactionPreview, request: dict, basearch: str = "x86_64", parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Apply changes"))
        self.resize(820, 620)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>{}</b> {}".format(_("The following changes will be made."), _("Review the list before applying."))))

        tree = QTreeWidget()
        tree.setHeaderLabels([_("Package"), _("Version"), _("Repository"), _("Size")])
        tree.setColumnWidth(0, 300)
        tree.setColumnWidth(1, 240)
        tree.setColumnWidth(2, 150)
        bold = QFont(tree.font())
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
                name = i.name if i.arch in ("noarch", basearch) else f"{i.name}.{i.arch}"
                if i.action == "reason":
                    version = f"→ {_(REASON_TEXT[i.reason]) if i.reason in REASON_TEXT else i.reason}"
                else:
                    version = f"{i.old_evr} → {i.evr}" if i.old_evr else i.evr
                size = human_size(i.download_size if i.download_size else i.install_size)
                QTreeWidgetItem(top, [name, version, display_repo(i.repo_id), size])
            tree.addTopLevelItem(top)
            top.setExpanded(True)
        lay.addWidget(tree, 1)

        lay.addWidget(QLabel(
            _("To download: {size}.").format(size=f"<b>{human_size(preview.download_size)}</b>") + "   "
            + _("Disk space change: {size}.").format(size=f"<b>{_signed_size(preview.size_change)}</b>")))

        critical = sorted({i.name for i in preview.items if i.action == "remove" and i.name in CRITICAL})
        removed = sum(1 for i in preview.items if i.action == "remove")
        warnings = []
        if critical:
            warnings.append(_("Essential system packages will be removed: {names}.").format(names=", ".join(critical)))
        if removed >= 20:
            warnings.append(ngettext("{n} package will be removed.", "{n} packages will be removed.", removed).format(n=removed))
        if warnings:
            w = QLabel("⚠ " + " ".join(warnings) + " " + _("Make sure this is what you want."))
            w.setWordWrap(True)
            w.setStyleSheet("color: #c03030; font-weight: bold")
            lay.addWidget(w)

        cmd = QPlainTextEdit(dnf5_command(request))
        cmd.setReadOnly(True)
        cmd.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        cmd.setFixedHeight(80)
        box = QGroupBox(_("Equivalent command"))
        QVBoxLayout(box).addWidget(cmd)
        lay.addWidget(box)

        self.download_only = QCheckBox(_("Download packages only"))
        lay.addWidget(self.download_only)

        buttons = QDialogButtonBox()
        ok = buttons.addButton(_("Apply"), QDialogButtonBox.AcceptRole)
        ok.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        ok.setDefault(True)
        buttons.addButton(QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
