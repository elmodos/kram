"""The package list's table: set up like the tree view it replaced, and it takes that view's saved columns."""
import os

import pytest

from kram.app.parity import Feature  # noqa: E402  (the feature marks of the parity tests)

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QApplication, QTreeView

from kram.core.model import Origin, PkgRow, Status
from kram.qt.package_model import PackageTableModel
from kram.qt.package_view import PackageView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def rows(n):
    return [PkgRow(f"pkg{i:05}", "x86_64", "summary", "", "1-1", "fedora", 1, Origin.FEDORA, Status.NOT_INSTALLED)
            for i in range(n)]


def view_with(n):
    model = PackageTableModel()
    view = PackageView()
    view.setModel(model)
    model.set_rows(rows(n), "x86_64")
    return view, model


def test_it_looks_and_behaves_like_the_tree_view(app):
    view, _model = view_with(3)
    assert view.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert view.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
    assert not view.showGrid() and view.alternatingRowColors() and not view.tabKeyNavigation()
    assert view.verticalHeader().isHidden()
    header = view.header()
    assert header is view.horizontalHeader()
    assert header.sectionsMovable() and header.stretchLastSection() and not header.highlightSections()
    assert header.defaultAlignment() & Qt.AlignmentFlag.AlignLeft


def test_rows_are_as_tall_as_the_tree_views(app):
    view, model = view_with(0)  # no rows yet: nothing to measure
    model.set_rows(rows(5), "x86_64")
    tree = QTreeView()
    tree.setUniformRowHeights(True)
    tree.setModel(model)
    assert view.rowHeight(0) == view.sizeHintForRow(0) == tree.sizeHintForRow(0)


@pytest.mark.feature(Feature.LIST_COLUMNS, front="qt")
def test_the_tree_views_saved_columns_still_apply(app):
    model = PackageTableModel()
    model.set_rows(rows(3), "x86_64")
    tree = QTreeView()
    tree.setModel(model)
    tree.setColumnWidth(2, 333)
    tree.header().setSectionHidden(4, True)
    tree.header().moveSection(3, 1)
    saved = tree.header().saveState()
    view = PackageView()
    view.setModel(model)
    assert view.header().restoreState(saved)
    assert view.columnWidth(2) == 333
    assert view.header().isSectionHidden(4)
    assert view.header().visualIndex(3) == 1


def test_a_reset_does_not_cost_more_with_more_rows(app):
    """What the switch was for: QTreeView did per-row work on every reset. A loose check, not a benchmark."""
    import time

    view, model = view_with(60000)
    view.resize(800, 400)
    view.show()

    def reset(n):
        start = time.perf_counter()
        model.set_visible(list(range(n)), ranked=True)
        app.processEvents()
        return time.perf_counter() - start
    reset(10)
    small = min(reset(10) for _ in range(3))
    large = min(reset(60000) for _ in range(3))
    assert large < small * 5 + 0.05


def test_the_mouse_highlights_the_whole_row(app):
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

    view, model = view_with(5)
    view.resize(500, 200)
    pos = view.visualRect(model.index(2, 3)).center()
    view.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(pos), QPointF(pos), Qt.MouseButton.NoButton,
                                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
    assert view.hover_row == 2

    def hovered(row, column):
        option = QStyleOptionViewItem()
        option.state = QStyle.StateFlag.State_Enabled
        if (row, column) == (2, 3):  # what the view itself marks
            option.state |= QStyle.StateFlag.State_MouseOver
        view.itemDelegate().initStyleOption(option, model.index(row, column))
        return bool(option.state & QStyle.StateFlag.State_MouseOver)
    assert all(hovered(2, c) for c in range(model.columnCount()))
    assert not any(hovered(1, c) for c in range(model.columnCount()))

    view.viewportEvent(QEvent(QEvent.Type.Leave))
    assert view.hover_row == -1


def test_the_repository_column_names_where_an_installed_package_came_from(app):
    from kram.qt.package_model import COL_REPO

    copr = "copr:copr.fedorainfracloud.org:elmodos:Kram"
    model = PackageTableModel()
    model.set_rows([
        PkgRow("kram", "noarch", "", "1-1", "2-1", "updates", 1, Origin.COPR, Status.UPGRADABLE, True, copr),
        PkgRow("bash", "x86_64", "", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED, False, "fedora"),
        PkgRow("fish", "x86_64", "", "", "1-1", "fedora", 1, Origin.FEDORA, Status.NOT_INSTALLED, False),
    ], "x86_64")
    cells = {model.data(model.index(i, 2)): model.index(i, COL_REPO) for i in range(3)}
    assert cells["kram"].data() == "elmodos/Kram → updates"
    assert cells["kram"].data(Qt.ItemDataRole.ToolTipRole) == ("Installed from elmodos/Kram; the latest version "
                                                               "comes from updates")
    assert [cells[n].data() for n in ("bash", "fish")] == ["fedora", "fedora"]
    assert cells["bash"].data(Qt.ItemDataRole.ToolTipRole) is None


@pytest.mark.feature(Feature.LIST_LOCK_PADLOCK, front="qt")
def test_a_locked_package_shows_the_padlock_and_the_upgrade_it_holds_back(app):
    from kram.core.marks import Action
    from kram.core.model import Advisory, VersionLock
    from kram.qt.icons import locked_icon, mark_icon, status_icon
    from kram.qt.package_model import COL_ADVISORY, COL_CANDIDATE, COL_STATUS

    fix = Advisory("FEDORA-2026-1", "security", "important", "tmux fix", 0)
    lock = (VersionLock("evr = 3.6a-1.fc44"),)
    model = PackageTableModel()
    model.set_rows([
        PkgRow("tmux", "x86_64", "", "3.6a-1.fc44", "3.6a-1.fc44", "fedora", 1, Origin.FEDORA, Status.INSTALLED,
               locks=lock, held_evr="3.8-2.fc44", held_advisories=(fix,)),
        PkgRow("jq", "x86_64", "", "", "1.8-1", "fedora", 1, Origin.FEDORA, Status.NOT_INSTALLED, locks=lock),
        PkgRow("less", "x86_64", "", "679-1", "679-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED),
    ], "x86_64")
    deco = Qt.ItemDataRole.DecorationRole
    assert model.index(0, COL_STATUS).data(deco).cacheKey() == locked_icon(True).cacheKey()
    assert model.index(1, COL_STATUS).data(deco).cacheKey() == locked_icon(False).cacheKey()
    assert model.index(2, COL_STATUS).data(deco).cacheKey() == status_icon(Status.INSTALLED).cacheKey()
    held = model.index(0, COL_CANDIDATE)
    assert held.data() == "3.8-2.fc44" and held.data(Qt.ItemDataRole.FontRole).italic()
    assert "3.8-2.fc44 is held back by the version lock" in held.data(Qt.ItemDataRole.ToolTipRole)
    assert model.index(0, COL_ADVISORY).data() == "Security: important"
    assert "evr = 3.6a-1.fc44" in model.index(0, COL_STATUS).data(Qt.ItemDataRole.ToolTipRole)
    model.marks.set(model.rows[0], Action.REINSTALL)  # a mark still shows over the padlock
    assert model.index(0, COL_STATUS).data(deco).cacheKey() == mark_icon(Action.REINSTALL).cacheKey()


def test_the_download_size_column_is_hidden_after_the_installed_size(app):
    from kram.qt.package_model import COL_DOWNLOAD, COL_SIZE, HEADERS

    view, model = view_with(0)
    header = view.header()
    assert header.isSectionHidden(COL_DOWNLOAD) and not header.isSectionHidden(COL_SIZE)
    assert header.visualIndex(COL_DOWNLOAD) == header.visualIndex(COL_SIZE) + 1
    assert (HEADERS[COL_SIZE], HEADERS[COL_DOWNLOAD]) == ("Installed size", "Download size")
    model.set_rows([
        PkgRow("vlc", "x86_64", "", "", "3-1", "fedora", 4096, Origin.FEDORA, Status.NOT_INSTALLED,
               download_size=2048),
        PkgRow("gone", "x86_64", "", "1-1", "", "fedora", 1, Origin.FEDORA, Status.ORPHAN),  # nothing to download
    ], "x86_64")
    assert [model.data(model.index(i, COL_DOWNLOAD)) for i in range(2)] == ["2.0 kB", ""]
    model.sort(COL_DOWNLOAD, Qt.SortOrder.DescendingOrder)
    assert model.data(model.index(0, 2)) == "vlc"


@pytest.mark.feature(Feature.LIST_COLUMNS, front="qt")
def test_a_header_state_saved_before_the_download_size_keeps_it_hidden(app, tmp_path):
    from PySide6.QtCore import QSettings

    from kram.qt.package_model import COL_DOWNLOAD, COL_SIZE
    from kram.qt.package_view import ADVISORY_COLUMN_KEY, HEADER_STATE_KEY, SIZE_COLUMN_WIDTH

    old = QTreeView()  # ten columns, as Kram 0.9.0 saved them
    old.setModel(QStandardItemModel(1, 10))
    old.setColumnWidth(COL_SIZE, 80)
    old.setColumnWidth(2, 333)
    old.header().setSectionHidden(4, True)
    old.header().moveSection(3, 1)
    old.header().setSortIndicator(COL_SIZE, Qt.SortOrder.DescendingOrder)
    settings = QSettings(str(tmp_path / "kram.conf"), QSettings.Format.IniFormat)
    settings.setValue(HEADER_STATE_KEY, old.header().saveState())
    settings.setValue(ADVISORY_COLUMN_KEY, True)

    view, _model = view_with(1)
    view.restore_columns(settings)
    header = view.header()
    assert header.isSectionHidden(COL_DOWNLOAD) and header.isSectionHidden(4)
    assert header.visualIndex(COL_DOWNLOAD) == header.visualIndex(COL_SIZE) + 1
    assert view.columnWidth(COL_SIZE) == SIZE_COLUMN_WIDTH and view.columnWidth(2) == 333
    assert header.visualIndex(3) == 1
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (COL_SIZE, Qt.SortOrder.DescendingOrder)

    header.setSectionHidden(COL_DOWNLOAD, False)  # shown by the user: stays shown
    view.save_columns(settings)
    again, _model = view_with(1)
    again.restore_columns(settings)  # Qt takes the state saved after the move back
    assert not again.header().isSectionHidden(COL_DOWNLOAD) and again.header().isSectionHidden(4)
    assert again.columnWidth(2) == 333 and again.header().visualIndex(3) == 1


def test_marking_every_row_is_one_change_and_finds_rows_at_once(app):
    """Marking thousands of rows: one repaint for the whole list, and each row found without a scan of the list."""
    import time

    _view, model = view_with(20000)
    signals = []
    model.dataChanged.connect(lambda *args: signals.append(args))
    keys = [r.key for r in model.rows]
    t0 = time.perf_counter()
    model.marks_changed(keys)
    assert time.perf_counter() - t0 < 0.5
    assert len(signals) == 1
    idx = model.index_of_key(keys[12345])
    assert idx.isValid() and idx.row() == 12345
    model.marks_changed(keys[:3])
    assert len(signals) == 4  # three rows, one signal each
    assert not model.index_of_key(("no-such", "x86_64")).isValid()
