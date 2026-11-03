"""gettext setup. Source strings are English; translations live in po/<lang>.po.

The language follows the usual environment (LANGUAGE, LC_ALL, LC_MESSAGES, LANG). Importing this module
installs the translation, so module-level constants that call _() are already translated.

    from kram.i18n import _, ngettext
    _("Reload")
    ngettext("{n} package", "{n} packages", n).format(n=n)
"""
import gettext
import shutil
import subprocess
from pathlib import Path

DOMAIN = "kram"
_PACKAGE = Path(__file__).resolve().parent
_SOURCE_PO = _PACKAGE.parent / "po"          # present only when running from a source checkout
_LOCAL_LOCALEDIR = _PACKAGE / "locale"       # compiled .mo files for source checkouts (gitignored)


def _compile_source_translations() -> None:
    """Running from git: build missing/stale .mo files so translations work without a build step."""
    if not _SOURCE_PO.is_dir() or shutil.which("msgfmt") is None:
        return
    for po in _SOURCE_PO.glob("*.po"):
        mo = _LOCAL_LOCALEDIR / po.stem / "LC_MESSAGES" / f"{DOMAIN}.mo"
        if mo.exists() and mo.stat().st_mtime >= po.stat().st_mtime:
            continue
        mo.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["msgfmt", "--check", "-o", str(mo), str(po)], check=False, capture_output=True)


def _load() -> gettext.NullTranslations:
    _compile_source_translations()
    for localedir in (_LOCAL_LOCALEDIR, None):  # None: the system default, /usr/share/locale
        t = gettext.translation(DOMAIN, localedir, fallback=True)
        if type(t) is not gettext.NullTranslations:  # found a catalog
            return t
    return gettext.NullTranslations()


translation = _load()
_ = translation.gettext
ngettext = translation.ngettext
pgettext = translation.pgettext  # pgettext(context, msg): same English word, different translations


def N_(message: str) -> str:
    """Mark a string for extraction without translating it here (translate it with _() where it is shown)."""
    return message


def language() -> str | None:
    """Language code of the active translation (e.g. "uk"), None for the English source strings."""
    info = translation.info() if type(translation) is not gettext.NullTranslations else {}
    lang = info.get("language")
    return lang or None
