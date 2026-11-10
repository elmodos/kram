"""Settings → Repositories: columns that fit what they show, and the menu of a repository's file."""
import os
from collections import Counter

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QUrl
from PySide6.QtWidgets import QApplication

from kram.core.model import Origin, RepoInfo
from kram.ui import files, repos_dialog
from kram.ui.repos_dialog import COL_FILE, COL_ID, COL_NAME, ReposDialog

COPR_ID = "copr:copr.fedorainfracloud.org:wezfurlong:wezterm-nightly"
COPR_FILE = f"/etc/yum.repos.d/_{COPR_ID}.repo"
REPOS = [RepoInfo("fedora", "Fedora 44 - x86_64", True, Origin.FEDORA, 60, 99, "/etc/yum.repos.d/fedora.repo"),
         RepoInfo(COPR_ID, "Copr repo for wezterm-nightly owned by wezfurlong", True, Origin.COPR, 60, 99, COPR_FILE),
         RepoInfo("code", "Visual Studio Code", True, Origin.THIRD_PARTY, 60, 99, "/etc/yum.repos.d/vscode.repo")]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def shown(app, width):
    dlg = ReposDialog(REPOS, Counter(), None)
    dlg.resize(width, 620)
    dlg.show()
    for _ in range(5):
        app.processEvents()
    return dlg


def text_width(dlg, text):
    return dlg.table.fontMetrics().horizontalAdvance(text)


def test_the_id_and_the_path_fit_when_the_window_is_wide(app):
    dlg = shown(app, 1700)
    assert dlg.table.columnWidth(COL_ID) >= text_width(dlg, COPR_ID)
    assert dlg.table.columnWidth(COL_FILE) >= text_width(dlg, COPR_FILE)
    assert not dlg.table.horizontalScrollBar().isVisible()


@pytest.mark.parametrize("width", [1100, 1180])
def test_a_narrower_window_cuts_the_path_not_the_id_and_does_not_scroll(app, width):
    dlg = shown(app, width)
    assert dlg.table.columnWidth(COL_ID) >= text_width(dlg, COPR_ID)  # the id is always whole
    assert repos_dialog.FILE_MIN <= dlg.table.columnWidth(COL_FILE) < text_width(dlg, COPR_FILE)
    assert dlg.table.columnWidth(COL_NAME) >= repos_dialog.NAME_MIN
    assert not dlg.table.horizontalScrollBar().isVisible()


def test_every_column_can_be_dragged_and_the_table_scrolls_sideways(app):
    from PySide6.QtWidgets import QAbstractItemView, QHeaderView

    dlg = shown(app, 1180)
    header = dlg.table.horizontalHeader()
    assert all(header.sectionResizeMode(c) == QHeaderView.Interactive for c in range(dlg.table.columnCount()))
    assert not header.stretchLastSection()
    assert dlg.table.horizontalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert not dlg._user_sized  # the start sizes are not the user's doing
    assert dlg.table.horizontalScrollBar().maximum() == 0  # and they need no scrolling
    header.resizeSection(COL_NAME, 900)  # what a drag does
    for _ in range(3):
        app.processEvents()
    assert dlg._user_sized and dlg.table.columnWidth(COL_NAME) == 900
    assert dlg.table.horizontalScrollBar().maximum() > 0  # now it scrolls instead of squeezing the rest


def test_the_users_sizes_are_left_alone_when_the_window_changes(app):
    dlg = shown(app, 1180)
    dlg.table.horizontalHeader().resizeSection(COL_FILE, 700)
    dlg.table.horizontalHeader().resizeSection(COL_NAME, 333)
    dlg.resize(1500, 620)
    for _ in range(5):
        app.processEvents()
    assert (dlg.table.columnWidth(COL_FILE), dlg.table.columnWidth(COL_NAME)) == (700, 333)


def test_the_path_column_follows_the_window(app):
    dlg = shown(app, 1700)
    wide = dlg.table.columnWidth(COL_FILE)
    dlg.resize(1150, 620)
    for _ in range(5):
        app.processEvents()
    assert dlg.table.columnWidth(COL_FILE) < wide


def test_every_long_cell_has_its_full_text_in_a_tooltip(app):
    dlg = shown(app, 1180)
    row = next(r for r in range(dlg.table.rowCount()) if dlg.table.item(r, COL_ID).text() == COPR_ID)
    for col, text in ((COL_ID, COPR_ID), (COL_NAME, REPOS[1].name), (COL_FILE, COPR_FILE)):
        assert dlg.table.item(row, col).text() == text == dlg.table.item(row, col).toolTip()


def test_the_path_menu_copies_and_shows(app, monkeypatch):
    dlg = shown(app, 1180)
    shown_paths = []
    monkeypatch.setattr(repos_dialog, "show_in_file_manager", shown_paths.append)
    copy, show = dlg._file_actions(COPR_FILE)
    assert [text for text, _action in (copy, show)] == ["Copy Path", "Show in File Manager"]
    copy[1]()
    assert QApplication.clipboard().text() == COPR_FILE
    show[1]()
    assert shown_paths == [COPR_FILE]


def test_only_the_path_cell_has_a_menu(app, monkeypatch):
    dlg = shown(app, 1180)
    opened = []

    class Menu:
        def __init__(self, _parent):
            opened.append(self)
            self.entries = []

        def addAction(self, text, _slot):
            self.entries.append(text)

        def exec(self, _pos):
            pass
    monkeypatch.setattr(repos_dialog, "QMenu", Menu)
    row = 0
    for col in range(dlg.table.columnCount()):
        pos = dlg.table.visualItemRect(dlg.table.item(row, col)).center()
        dlg._context_menu(pos)
        assert len(opened) == (1 if col >= COL_FILE else 0)  # only the last column, the file
    assert opened[0].entries == ["Copy Path", "Show in File Manager"]
    dlg._context_menu(QPoint(-5, -5))  # nowhere: no menu
    assert len(opened) == 1


def test_show_in_file_manager_selects_the_file_or_falls_back_to_its_folder():
    asked, opened = [], []
    files.show_in_file_manager(COPR_FILE, lambda uri: asked.append(uri) or True, opened.append)
    assert asked == [QUrl.fromLocalFile(COPR_FILE).toString()] and opened == []
    files.show_in_file_manager(COPR_FILE, lambda uri: False, opened.append)
    assert [u.toLocalFile() for u in opened] == ["/etc/yum.repos.d"]
    opened.clear()
    files.show_in_file_manager("/file.repo", lambda uri: False, opened.append)
    assert [u.toLocalFile() for u in opened] == ["/"]


def test_a_cut_path_keeps_its_start_and_its_end(app):
    dlg = shown(app, 1180)
    metrics = dlg.table.fontMetrics()
    cut = repos_dialog.elide_middle(COPR_FILE, 300, metrics)
    assert cut.startswith("/etc/yum.repos.d/") and cut.endswith("nightly.repo") and "…" in cut
    assert metrics.horizontalAdvance(cut) <= 300
    assert repos_dialog.elide_middle("/etc/yum.repos.d/fedora.repo", 600, metrics) == "/etc/yum.repos.d/fedora.repo"
    assert repos_dialog.elide_middle(COPR_FILE, -5, metrics) in ("", "…")


def test_the_origin_column_holds_its_icon_and_its_label(app):
    from kram.ui.icons import ORIGIN_LABEL

    dlg = shown(app, 1180)
    shown_origins = {r.origin for r in REPOS}
    widest = max(text_width(dlg, ORIGIN_LABEL[o]) for o in shown_origins)
    assert dlg.table.columnWidth(repos_dialog.COL_ORIGIN) >= widest + 16 + repos_dialog.COLUMN_PAD  # icon, gap, text


def test_the_dialog_can_be_shown_and_thrown_away(app):
    """An event filter object that held on to the dialog crashed the interpreter in the garbage collector, long after
    the test that made it: the crash must come here instead."""
    import gc

    dlg = shown(app, 1180)
    dlg.resize(1100, 620)
    for _ in range(3):
        app.processEvents()
    del dlg
    gc.collect()
    gc.collect()
