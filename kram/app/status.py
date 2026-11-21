"""The main window's status line: what is listed and marked, repositories without metadata, the metadata's age."""
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


def counts_text(snap: CatalogSnapshot, shown: int, to_install: int, to_remove: int) -> str:
    upgrades = ngettext("{n} upgrade", "{n} upgrades", snap.n_upgradable).format(n=snap.n_upgradable)
    listed = ngettext("{shown} listed, {installed} installed, {upgrades}.",
                      "{shown} listed, {installed} installed, {upgrades}.", shown).format(
        shown=shown, installed=snap.n_installed, upgrades=upgrades)
    marked = ngettext("{install} to install/upgrade, {remove} to remove.",
                      "{install} to install/upgrade, {remove} to remove.", to_install).format(
        install=to_install, remove=to_remove)
    return listed + " " + marked


def timings_tip(snap: CatalogSnapshot, ms: float) -> str:
    """The time the catalog load and the filter and search took."""
    return _("Catalog: {load:.2f} s, filter and search: {ms:.0f} ms").format(load=snap.load_seconds, ms=ms)


def missing_repos(snap: CatalogSnapshot) -> tuple[str, str] | None:
    """The warning about enabled repositories that could not be loaded, and its tooltip; None when all loaded."""
    missing = snap.unavailable_repos
    if not missing:
        return None
    n = len(missing)
    text = ngettext("{n} repository has no metadata", "{n} repositories have no metadata", n).format(n=n)
    tip = _("Not loaded, so their packages are missing from the list:\n{names}\n\n"
            "Use Reload to download them. If a repository keeps failing (for example it has no packages for "
            "this Fedora release yet), disable it in Settings → Repositories.").format(
        names="\n".join(f"• {r.name} ({r.id})" for r in missing))
    return text, tip


def error_text(error: BaseException) -> str:
    return _("Error: {error}").format(error=error)
