"""Translation catalogs stay in sync with the code and compile cleanly."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PO_DIR = ROOT / "po"

pytestmark = pytest.mark.skipif(shutil.which("xgettext") is None, reason="gettext tools not installed")


def msgids(pot_text: str) -> set[str]:
    """msgid (with context) of every entry, joined across continuation lines."""
    ids, cur, ctx = set(), None, ""
    for line in pot_text.splitlines() + [""]:
        if line.startswith("msgctxt "):
            ctx, cur = line[8:], "ctx"
        elif line.startswith("msgid "):
            cur, mid = "id", line[6:]
        elif line.startswith('"') and cur == "id":
            mid += line
        elif line.startswith('"') and cur == "ctx":
            ctx += line
        elif cur == "id":
            ids.add(ctx + "\x04" + mid)
            cur, ctx = None, ""
    ids.discard('\x04""')
    return ids


def test_pot_is_up_to_date(tmp_path):
    fresh = tmp_path / "kram.pot"
    sources = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "kram").rglob("*.py") if "helper" not in p.parts)
    subprocess.run(["xgettext", "--language=Python", "--from-code=UTF-8", "--keyword=_", "--keyword=N_",
                    "--keyword=ngettext:1,2", "--keyword=pgettext:1c,2", "-o", str(fresh), *sources],
                   cwd=ROOT, check=True)
    assert msgids(fresh.read_text()) == msgids((PO_DIR / "kram.pot").read_text()), \
        "po/kram.pot is stale: run scripts/i18n.sh update"


@pytest.mark.parametrize("po", sorted(PO_DIR.glob("*.po")), ids=lambda p: p.stem)
def test_po_compiles_and_is_complete(po):
    out = subprocess.run(["msgfmt", "--check", "--statistics", "-o", "/dev/null", str(po)],
                         capture_output=True, text=True, env={"LC_ALL": "C"}, check=False)
    assert out.returncode == 0, out.stderr
    assert "untranslated" not in out.stderr and "fuzzy" not in out.stderr, out.stderr


@pytest.mark.parametrize("po", sorted(PO_DIR.glob("*.po")), ids=lambda p: p.stem)
def test_placeholders_match(po):
    """str.format placeholders in a translation must be the ones in the source, or .format() raises."""
    import polib_lite

    for entry in polib_lite.entries(po.read_text()):
        source = set(re.findall(r"\{(\w+)[^}]*\}", entry["msgid"] + entry.get("msgid_plural", "")))
        for msgstr in entry["msgstr"]:
            if msgstr:
                assert set(re.findall(r"\{(\w+)[^}]*\}", msgstr)) <= source, (entry["msgid"], msgstr)
