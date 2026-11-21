"""The document model renders to the HTML Kram 0.11.3 wrote by hand, byte for byte (recorded from that version's
code for the inputs in tests/doc_fixtures.py)."""
import json
import os
import time
from pathlib import Path

import doc_fixtures as F
import pytest

from kram.app.details import advisories_doc, blocked_doc, changelog_doc, dependencies_doc, description_doc, general_doc
from kram.app.empty_list import EmptyList, explain, failed, loading
from kram.app.whats_new import whats_new_doc

RECORDED = json.loads((Path(__file__).with_name("data") / "html_0.11.3.json").read_text())


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def rendered() -> dict[str, str]:
    from kram.qt.doc_html import to_html
    out = {}
    for name, row in F.ROWS.items():
        out[f"advisories/{name}"] = to_html(advisories_doc(row))
    for i, reason in enumerate(F.BLOCKED):
        out[f"blocked/{i}"] = to_html(blocked_doc(reason))
    for name, d in F.DETAILS.items():
        for rname in ("advisories", "held"):
            row = F.ROWS[rname]
            out[f"details/{name}/{rname}/desc"] = to_html(description_doc(d))
            out[f"details/{name}/{rname}/general"] = to_html(general_doc(row, d))
            out[f"details/{name}/{rname}/deps"] = to_html(dependencies_doc(d))
            out[f"details/{name}/{rname}/changelog"] = to_html(changelog_doc(d))
        out[f"details/{name}/blocked/deps"] = to_html(blocked_doc(F.BLOCKED[0]) + dependencies_doc(d))
    out["details/blocked-only/deps"] = to_html(blocked_doc(""))
    for i, kw in enumerate(F.EMPTY):
        out[f"empty/{i}"] = to_html(explain(EmptyList(**kw)), compact=True)
    out["empty/loading"] = to_html(loading(), compact=True)
    out["empty/failed"] = to_html(failed(), compact=True)
    out["whats_new/some"] = to_html(whats_new_doc(F.RELEASES, current="0.11.3"))
    out["whats_new/none"] = to_html(whats_new_doc([]))
    return out


def test_the_html_is_that_of_0_11_3():
    pytest.importorskip("PySide6")  # kram.qt is the Qt front end's package
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    got = rendered()
    assert got.keys() == RECORDED.keys()
    for key, html in RECORDED.items():
        assert got[key] == html, key


def test_plain_text_for_other_front_ends():
    from kram.app.doc import plain_text
    text = plain_text(dependencies_doc(F.DETAILS["full"]))
    assert "Provides (1003)" in text and "…and 3 more" in text and "cap999 = 1" in text and "cap1000" not in text
    assert plain_text(advisories_doc(F.ROWS["held"])).startswith("Version 2-1 is held back by the version lock\n")
