"""The package list's table: set up like the tree view it replaced, and it takes that view's saved columns."""
import os

import pytest

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QApplication, QTreeView

from kram.core.model import Origin, PkgRow, Status
from kram.ui.package_model import PackageTableModel
from kram.ui.package_view import PackageView


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
    assert view.selectionBehavior() == QAbstractItemView.SelectRows
    assert view.selectionMode() == QAbstractItemView.ExtendedSelection
    assert not view.showGrid() and view.alternatingRowColors() and not view.tabKeyNavigation()
    assert view.verticalHeader().isHidden()
    header = view.header()
    assert header is view.horizontalHeader()
    assert header.sectionsMovable() and header.stretchLastSection() and not header.highlightSections()
    assert header.defaultAlignment() & Qt.AlignLeft


def test_rows_are_as_tall_as_the_tree_views(app):
    view, model = view_with(0)  # no rows yet: nothing to measure
    model.set_rows(rows(5), "x86_64")
    tree = QTreeView()
    tree.setUniformRowHeights(True)
    tree.setModel(model)
    assert view.rowHeight(0) == view.sizeHintForRow(0) == tree.sizeHintForRow(0)


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
    view.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(pos), QPointF(pos), Qt.NoButton, Qt.NoButton,
                                    Qt.NoModifier))
    assert view.hover_row == 2

    def hovered(row, column):
        option = QStyleOptionViewItem()
        option.state = QStyle.State_Enabled
        if (row, column) == (2, 3):  # what the view itself marks
            option.state |= QStyle.State_MouseOver
        view.itemDelegate().initStyleOption(option, model.index(row, column))
        return bool(option.state & QStyle.State_MouseOver)
    assert all(hovered(2, c) for c in range(model.columnCount()))
    assert not any(hovered(1, c) for c in range(model.columnCount()))

    view.viewportEvent(QEvent(QEvent.Leave))
    assert view.hover_row == -1


def test_the_repository_column_names_where_an_installed_package_came_from(app):
    from kram.ui.package_model import COL_REPO

    copr = "copr:copr.fedorainfracloud.org:elmodos:Kram"
    model = PackageTableModel()
    model.set_rows([
        PkgRow("kram", "noarch", "", "1-1", "2-1", "updates", 1, Origin.COPR, Status.UPGRADABLE, True, copr),
        PkgRow("bash", "x86_64", "", "1-1", "1-1", "fedora", 1, Origin.FEDORA, Status.INSTALLED, False, "fedora"),
        PkgRow("fish", "x86_64", "", "", "1-1", "fedora", 1, Origin.FEDORA, Status.NOT_INSTALLED, False),
    ], "x86_64")
    cells = {model.data(model.index(i, 2)): model.index(i, COL_REPO) for i in range(3)}
    assert cells["kram"].data() == "elmodos/Kram → updates"
    assert cells["kram"].data(Qt.ToolTipRole) == ("Installed from elmodos/Kram; the latest version comes from "
                                                  "updates")
    assert [cells[n].data() for n in ("bash", "fish")] == ["fedora", "fedora"]
    assert cells["bash"].data(Qt.ToolTipRole) is None
