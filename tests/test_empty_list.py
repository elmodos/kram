"""The empty package list says why it is empty, with links that fill it; F5 reloads."""
import os

import pytest

from kram.ui.empty_list import ALL, DESCRIPTIONS, RELOAD, REPOS, EmptyList, explain


def test_no_search_names_the_filter():
    text = explain(EmptyList("Upgradable", in_all=False))
    assert text == "No packages in “Upgradable”."


def test_search_in_a_filter_offers_all():
    text = explain(EmptyList("Installed", False, "vlc", found_in_all=3))
    assert "Nothing found for “vlc” in “Installed”." in text
    assert f"<a href='{ALL}'>Show 3 results in “All”</a>" in text


def test_search_in_all_offers_the_descriptions():
    text = explain(EmptyList("All", True, "player", found_in_all=5, found_in_descriptions=1))
    assert text.startswith("Nothing found for “player”.")
    assert f"href='{ALL}'" not in text  # already everything
    assert f"<a href='{DESCRIPTIONS}'>Show 1 result found in descriptions</a>" in text


def test_file_search_explains_what_is_known():
    assert "/etc" in explain(EmptyList("All", True, "foo.conf", file_search=True))
    assert "/etc" not in explain(EmptyList("All", True, "foo"))


def test_missing_repositories_and_markup_in_names():
    text = explain(EmptyList("<b>", True, "a&b", missing_repos=2))
    assert "“a&amp;b”" in text and "<b>" not in text
    assert "2 repositories have no metadata" in text
    assert f"href='{RELOAD}'" in text and f"href='{REPOS}'" in text


# ---------------------------------------------------------------- in the window

@pytest.fixture
def window(monkeypatch):
    pytest.importorskip("libdnf5")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from kram.ui import main_window
    monkeypatch.setattr(main_window.MainWindow, "reload", lambda self: None)
    win = main_window.MainWindow()
    yield win
    win.dnf.shutdown()


def test_f5_reloads_too(window):
    from PySide6.QtGui import QKeySequence
    assert [s.toString() for s in window.acts.reload.shortcuts()] == ["Ctrl+R", "F5"]
    assert QKeySequence("F5") in window.acts.reload.shortcuts()


def test_the_empty_list_explains_and_its_link_shows_the_results(window, monkeypatch):
    from kram.core.filters import FilterEntry
    from kram.core.model import CatalogSnapshot, Origin, PkgRow, Status
    from kram.core.search import Mode, NarrowingSearch, SearchIndex

    rows = [PkgRow("vlc", "x86_64", "Media player", "", "3-1", "fedora", 1, Origin.FEDORA, Status.NOT_INSTALLED),
            PkgRow("mpv", "x86_64", "Video player", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED)]
    window.snapshot = CatalogSnapshot(rows, 1, 0, 0.0, descriptions=["", "plays vlc playlists"])
    window.model.set_rows(rows, "x86_64")
    window.index = SearchIndex(rows, window.snapshot.descriptions)
    window.narrowing = NarrowingSearch(window.index)
    window.key_index = {r.key: i for i, r in enumerate(rows)}
    window.filter = FilterEntry("status:installed", "Installed", lambda r: r.installed)
    window.search.set_query("vlc", Mode.NAME)
    window.apply_filter()
    assert window.model.rowCount() == 0
    shown = window.table.empty_text()
    assert "in “Installed”" in shown and "Show 1 result in “All”" in shown
    selected = []
    monkeypatch.setattr(window.sidebar, "select", lambda view, entry: selected.append(entry))
    window.table.emptyLinkActivated.emit(ALL)
    assert selected == ["status:all"]

    window.filter = FilterEntry("status:all", "All", lambda _r: True)
    window.search.set_query("playlists", Mode.NAME)
    window.apply_filter()
    assert "Show 1 result found in descriptions" in window.table.empty_text()
    window.table.emptyLinkActivated.emit(DESCRIPTIONS)  # switches the mode, which searches again
    assert window.search.mode() is Mode.DESCRIPTION
    assert window.model.rowCount() == 1 and window.table.empty_text() == ""
