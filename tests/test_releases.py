"""What's New reads the release notes from the AppStream metainfo."""
from pathlib import Path

import kram
from kram.core import releases


def test_release_notes_from_the_metainfo():
    found = releases.load()
    assert found, "data/*.metainfo.xml has no <releases>"
    assert found[0].version == kram.__version__, "add a <release> for the current version to the metainfo"
    assert all(r.version and r.date and (r.paragraphs or r.items) for r in found)
    assert all("  " not in text for r in found for text in r.paragraphs + r.items)  # wrapped XML text joined


def test_no_metainfo(tmp_path):
    assert releases.load((tmp_path / "missing.xml",)) == []
