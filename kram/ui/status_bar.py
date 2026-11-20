"""The main window's status bar: what is listed and marked, missing repositories, the age of the metadata."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QStatusBar

from ..core.model import CatalogSnapshot
from ..i18n import _, ngettext


def metadata_age(seconds: int | None) -> str:
    if seconds is None:
        return _("Metadata: unknown age")
    if seconds < 3600:
        return _("Metadata: {minutes} min ago").format(minutes=seconds // 60)
    if seconds < 2 * 86400:
        return _("Metadata: {hours} h {minutes} min ago").format(hours=seconds // 3600, minutes=seconds % 3600 // 60)
    return _("Metadata: {days} d ago").format(days=seconds // 86400)


class MainStatusBar(QStatusBar):
    reposClicked = Signal()  # the warning about repositories without metadata

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = QLabel()
        self.addWidget(self._text, 1)
        # enabled repositories that could not be loaded; clicking opens Settings → Repositories
        self._repo_warning = QLabel()
        self._repo_warning.setVisible(False)
        self._repo_warning.linkActivated.connect(lambda _link: self.reposClicked.emit())
        self.addPermanentWidget(self._repo_warning)
        self._age = QLabel()
        self.addPermanentWidget(self._age)

    def text(self) -> str:
        return self._text.text()

    def set_text(self, text: str) -> None:
        self._text.setText(text)

    def show_error(self, error: BaseException) -> None:
        self.set_text(_("Error: {error}").format(error=error))

    def show_catalog(self, snap: CatalogSnapshot) -> None:
        """What stays the same until the next load: the metadata age and the repositories that have none."""
        self._age.setText(metadata_age(snap.metadata_age) + "  ")
        missing = snap.unavailable_repos
        self._repo_warning.setVisible(bool(missing))
        if not missing:
            return
        n = len(missing)
        text = ngettext("{n} repository has no metadata", "{n} repositories have no metadata", n).format(n=n)
        self._repo_warning.setText(f"⚠ <a href='repos'>{text}</a>  ")
        self._repo_warning.setToolTip(
            _("Not loaded, so their packages are missing from the list:\n{names}\n\n"
              "Use Reload to download them. If a repository keeps failing (for example it has no packages for "
              "this Fedora release yet), disable it in Settings → Repositories.").format(
                names="\n".join(f"• {r.name} ({r.id})" for r in missing)))

    def show_counts(self, snap: CatalogSnapshot, shown: int, to_install: int, to_remove: int,
                    ms: float | None = None) -> None:
        """The packages listed and marked; `ms`, the time the filter and search took, goes into the tooltip."""
        upgrades = ngettext("{n} upgrade", "{n} upgrades", snap.n_upgradable).format(n=snap.n_upgradable)
        listed = ngettext("{shown} listed, {installed} installed, {upgrades}.",
                          "{shown} listed, {installed} installed, {upgrades}.", shown).format(
            shown=shown, installed=snap.n_installed, upgrades=upgrades)
        marked = ngettext("{install} to install/upgrade, {remove} to remove.",
                          "{install} to install/upgrade, {remove} to remove.", to_install).format(
            install=to_install, remove=to_remove)
        self.set_text(listed + " " + marked)
        if ms is not None:
            self._text.setToolTip(_("Catalog: {load:.2f} s, filter and search: {ms:.0f} ms").format(
                load=snap.load_seconds, ms=ms))
