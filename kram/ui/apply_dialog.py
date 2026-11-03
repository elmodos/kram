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
from .package_model import human_size

# Removing any of these leaves a system that may not boot or log in; worth a loud warning even if dnf allows it.
CRITICAL = frozenset({
    "bash", "coreutils", "dnf5", "glibc", "kernel-core", "NetworkManager", "pam", "polkit", "rpm", "sddm",
    "shadow-utils", "sudo", "systemd", "util-linux", "plasma-workspace", "plasma-desktop", "kwin",
})

# (title, color, predicate over PreviewItem)
GROUPS = [
    ("Буде встановлено", "#2f7a1f", lambda i: i.action == "install" and i.reason == "user"),
    ("Буде встановлено як залежності", "#2f7a1f", lambda i: i.action == "install" and i.reason != "user"),
    ("Буде оновлено", "#1f5fa8", lambda i: i.action == "upgrade"),
    ("Буде понижено", "#a86f1f", lambda i: i.action == "downgrade"),
    ("Буде перевстановлено", "#1f5fa8", lambda i: i.action == "reinstall"),
    ("Буде видалено", "#b02020", lambda i: i.action == "remove" and i.reason == "user"),
    ("Буде видалено як залежні або більше не потрібні", "#b02020",
     lambda i: i.action == "remove" and i.reason != "user"),
    ("Зміниться причина встановлення", None, lambda i: i.action == "reason"),
]
REASON_TEXT = {"user": "вручну", "dependency": "залежність", "weak": "слабка залежність", "clean": "непотрібний"}


def _signed_size(n: int) -> str:
    return ("+" if n >= 0 else "−") + human_size(abs(n))


class ApplyDialog(QDialog):
    def __init__(self, preview: TransactionPreview, request: dict, basearch: str = "x86_64", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Застосувати зміни")
        self.resize(820, 620)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>Буде виконано такі зміни.</b> Перевірте список перед застосуванням."))

        tree = QTreeWidget()
        tree.setHeaderLabels(["Пакунок", "Версія", "Репозиторій", "Розмір"])
        tree.setColumnWidth(0, 300)
        tree.setColumnWidth(1, 240)
        tree.setColumnWidth(2, 150)
        bold = QFont(tree.font())
        bold.setBold(True)
        for title, color, pred in GROUPS:
            items = [i for i in preview.items if pred(i)]
            if not items:
                continue
            top = QTreeWidgetItem([f"{title} ({len(items)})"])
            top.setFont(0, bold)
            if color:
                top.setForeground(0, QBrush(QColor(color)))
            for i in items:
                name = i.name if i.arch in ("noarch", basearch) else f"{i.name}.{i.arch}"
                if i.action == "reason":
                    version = f"→ {REASON_TEXT.get(i.reason, i.reason)}"
                else:
                    version = f"{i.old_evr} → {i.evr}" if i.old_evr else i.evr
                size = human_size(i.download_size if i.download_size else i.install_size)
                QTreeWidgetItem(top, [name, version, display_repo(i.repo_id), size])
            tree.addTopLevelItem(top)
            top.setExpanded(True)
        lay.addWidget(tree, 1)

        lay.addWidget(QLabel(
            f"Буде завантажено: <b>{human_size(preview.download_size)}</b>.   "
            f"Зміна зайнятого місця на диску: <b>{_signed_size(preview.size_change)}</b>."))

        critical = sorted({i.name for i in preview.items if i.action == "remove" and i.name in CRITICAL})
        removed = sum(1 for i in preview.items if i.action == "remove")
        warnings = []
        if critical:
            warnings.append(f"Буде видалено системно важливі пакунки: {', '.join(critical)}.")
        if removed >= 20:
            warnings.append(f"Буде видалено {removed} пакунків.")
        if warnings:
            w = QLabel("⚠ " + " ".join(warnings) + " Переконайтеся, що ви цього хочете.")
            w.setWordWrap(True)
            w.setStyleSheet("color: #c03030; font-weight: bold")
            lay.addWidget(w)

        cmd = QPlainTextEdit(dnf5_command(request))
        cmd.setReadOnly(True)
        cmd.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        cmd.setFixedHeight(80)
        box = QGroupBox("Еквівалентна команда")
        QVBoxLayout(box).addWidget(cmd)
        lay.addWidget(box)

        self.download_only = QCheckBox("Лише завантажити пакунки")
        lay.addWidget(self.download_only)

        buttons = QDialogButtonBox()
        ok = buttons.addButton("Застосувати", QDialogButtonBox.AcceptRole)
        ok.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        ok.setDefault(True)
        buttons.addButton("Скасувати", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
