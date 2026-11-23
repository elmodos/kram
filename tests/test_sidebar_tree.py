"""The sidebar's tree: the selection spans the whole row, and a long entry scrolls sideways instead of being
elided."""
import os

import pytest

from kram.app.parity import Feature  # noqa: E402  (the feature marks of the parity tests)

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTreeWidgetItem, QVBoxLayout, QWidget

from kram.qt.sidebar import _Tree


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_the_column_is_never_narrower_than_the_view(app):
    box = QWidget()
    tree = _Tree()
    tree.setHeaderHidden(True)
    QVBoxLayout(box).addWidget(tree)
    tree.addTopLevelItem(QTreeWidgetItem(["Installed"]))
    box.resize(400, 300)
    box.show()
    app.processEvents()
    assert tree.header().sectionSize(0) == tree.viewport().width()
    box.resize(600, 300)  # and follows the view when the panel grows
    app.processEvents()
    assert tree.header().sectionSize(0) == tree.viewport().width()
    tree.addTopLevelItem(QTreeWidgetItem(["x" * 200]))
    app.processEvents()
    assert tree.header().sectionSize(0) > tree.viewport().width() and tree.horizontalScrollBar().maximum() > 0


@pytest.mark.feature(Feature.SIDEBAR_VIEWS, front="qt")
def test_an_empty_entry_goes_once_the_selection_leaves_it(app):
    """Kept while selected, as a restored selection; hidden again when another entry is picked."""
    from kram.core.model import CatalogSnapshot
    from kram.qt.sidebar import Sidebar

    bar = Sidebar()
    bar.marked, bar.blocked = set(), {}
    bar.set_snapshot(CatalogSnapshot([], 0, 0, 0.0))
    assert bar.item_of("status:blocked") is None
    bar.select("status", "status:blocked")
    assert bar.item_of("status:blocked") is not None
    bar.list.setCurrentItem(bar.item_of("status:upgradable"))
    app.processEvents()
    assert bar.item_of("status:blocked") is None
    assert bar.current_entry_id == "status:upgradable"


@pytest.mark.feature(Feature.SIDEBAR_SECTION_ICONS, front="qt")
def test_every_section_button_has_its_view_icon(app):
    from PySide6.QtGui import QIcon

    from kram.app.sidebar import VIEW_ICONS, VIEWS
    from kram.qt.sidebar import Sidebar

    QIcon.setThemeSearchPaths(["/usr/share/icons", *QIcon.themeSearchPaths()])
    assert [view_id for view_id, _label, _b in VIEWS] == list(VIEW_ICONS)
    for theme in ("breeze", "Adwaita"):  # every name is in both
        QIcon.setThemeName(theme)
        if all(QIcon.hasThemeIcon(name) for name in VIEW_ICONS.values()):
            break
    else:
        pytest.skip("neither Breeze nor Adwaita is installed")
    bar = Sidebar()
    assert all(not btn.icon().isNull() for btn in bar._buttons.buttons())
