"""The Files tab: the folder tree, the filter, the tree and list views."""
import os

import pytest

from kram.core.file_tree import build_tree, path_filter

PATHS = [
    "/usr/bin/kram",
    "/usr/lib64/libkram.so.1",
    "/usr/lib64/libkram.so.1.2",
    "/usr/share/doc/kram",
    "/usr/share/doc/kram/README.md",
    "/usr/share/applications/io.github.elmodos.Kram.desktop",
    "/etc/kram.conf",
    "/usr/share/kram/empty",  # a folder the package owns and leaves empty: the metadata cannot tell
]


def filter_paths(paths, text):
    f = path_filter(text)
    return paths if f is None else [p for p in paths if f.match(p)]


def names(node):
    return [c.name for c in node.children]


def test_tree_has_every_folder_above_the_files_folders_first():
    root = build_tree(PATHS)
    assert root.path == "/" and names(root) == ["etc", "usr"]
    usr = root.children[1]
    assert names(usr) == ["bin", "lib64", "share"]
    share = usr.children[2]
    assert names(share) == ["applications", "doc", "kram"]
    doc = share.children[1].children[0]
    assert doc.path == "/usr/share/doc/kram" and doc.is_dir and names(doc) == ["README.md"]
    empty = share.children[2].children[0]
    assert empty.path == "/usr/share/kram/empty" and not empty.is_dir
    assert names(root.children[0]) == ["kram.conf"]


def test_tree_rows_and_parents_match():
    root = build_tree(PATHS)
    stack = [root]
    while stack:
        node = stack.pop()
        for i, child in enumerate(node.children):
            assert child.row == i and child.parent is node
            assert child.path == f"{node.path.rstrip('/')}/{child.name}"
        stack.extend(node.children)


def test_tree_takes_any_order_and_duplicates():
    root = build_tree(["/a/b/c", "/a/b", "/a/b/c", "/z", "/a/b/"])
    assert names(root) == ["a", "z"]
    assert names(root.children[0].children[0]) == ["c"]
    assert build_tree([]).children == []


@pytest.mark.parametrize(("text", "kept"), [
    ("", PATHS),
    ("   ", PATHS),
    ("DOC", ["/usr/share/doc/kram", "/usr/share/doc/kram/README.md"]),
    ("share/doc", ["/usr/share/doc/kram", "/usr/share/doc/kram/README.md"]),
    ("*.so", []),  # a pattern is the whole name: libkram.so.1 does not end in .so
    ("*.so*", ["/usr/lib64/libkram.so.1", "/usr/lib64/libkram.so.1.2"]),
    ("libkram*", ["/usr/lib64/libkram.so.1", "/usr/lib64/libkram.so.1.2"]),
    ("/usr/bin/*", ["/usr/bin/kram"]),
    ("*.desktop", ["/usr/share/applications/io.github.elmodos.Kram.desktop"]),
    ("kram.so.1.?", []),  # a pattern is the whole name or path, not a part of it
    ("*kram.so.1.?", ["/usr/lib64/libkram.so.1.2"]),
])
def test_filter(text, kept):
    assert filter_paths(PATHS, text) == kept


@pytest.mark.parametrize(("text", "path", "start", "spans"), [
    # a text: each place it is found, in this entry's name only
    ("kram", "/usr/share/doc/kram/README.md", 20, []),  # the README is there for its folder
    ("kram", "/usr/share/doc/kram", 15, [(0, 4)]),
    ("KRAM", "/usr/lib64/libkram.so.1", 11, [(3, 7)]),
    ("a", "/usr/share/data", 11, [(1, 2), (3, 4)]),
    # across a "/": bold in the folder where the match ends, the one that is there because of it
    ("share/doc", "/usr/share", 5, []),
    ("share/doc", "/usr/share/doc", 11, [(0, 3)]),
    ("share/doc", "/usr/share/doc", 0, [(5, 14)]),  # the list shows the whole path
    # a pattern: the whole name of what matched, nothing for the folders above it
    ("*.so*", "/usr/lib64/libkram.so.1", 11, [(0, 12)]),
    ("*.so*", "/usr/lib64", 5, []),
    ("/usr/bin/*", "/usr/bin/kram", 9, [(0, 4)]),
    ("/usr/bin/*", "/usr/bin/kram", 0, [(0, 13)]),
])
def test_spans(text, path, start, spans):
    assert path_filter(text).spans(path, start) == spans


def test_empty_filter_keeps_the_same_list():
    assert path_filter("") is None and path_filter("  ") is None
    assert filter_paths(PATHS, "") is PATHS


# ---------------------------------------------------------------- the widget

@pytest.fixture
def files():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from kram.qt.file_list import FileList
    widget = FileList()
    widget.show()
    yield widget
    widget.close()


def rows(widget):
    """The visible rows as indented names: what the user sees."""
    from kram.qt.file_list import PATH_ROLE
    model, out = widget.view.model(), []

    def walk(parent, depth):
        for r in range(model.rowCount(parent)):
            index = model.index(r, 0, parent)
            out.append("  " * depth + index.data())
            assert index.data(PATH_ROLE).endswith(index.data())
            if widget.tree_mode:
                assert widget.view.isExpanded(index) or not model.hasChildren(index)  # all open, old-school
            walk(index, depth + 1)
    walk(widget.view.rootIndex(), 0)
    return out


def test_tree_view_open_to_the_last_file(files):
    files.set_files(["/usr/bin/kram", "/etc/kram.conf"], True)
    assert rows(files) == ["etc", "  kram.conf", "usr", "  bin", "    kram"]
    assert files.count.text() == "2 files"
    assert not files.notice.isVisibleTo(files)


def test_list_view_and_back(files):
    files.set_files(["/usr/bin/kram", "/etc/kram.conf"], False)
    assert files.notice.isVisibleTo(files)  # not installed: only some of the files
    files.tree_mode = False
    assert rows(files) == ["/usr/bin/kram", "/etc/kram.conf"]  # in the package's own order
    files.tree_mode = True
    assert rows(files) == ["etc", "  kram.conf", "usr", "  bin", "    kram"]


def test_filter_waits_for_the_typing_to_pause(files):
    files.set_files(PATHS, True)
    files.filter.setText("readme")
    assert files._timer.active and len(rows(files)) > 3  # not filtered yet
    files._rebuild_now()
    assert rows(files) == ["usr", "  share", "    doc", "      kram", "        README.md"]
    assert files.count.text() == f"1 of {len(PATHS)} files"
    files.set_files(["/opt/readme.txt", "/opt/other"], True)  # the filter stays for the next package
    assert rows(files) == ["opt", "  readme.txt"]


def test_not_built_while_hidden(files):
    files.hide()
    files.set_files(["/usr/bin/kram"], True)
    assert files.view.model().rowCount() == 0
    files.show()
    assert rows(files) == ["usr", "  bin", "    kram"]


def test_copy_paths(files):
    from PySide6.QtGui import QGuiApplication
    files.set_files(["/usr/bin/kram", "/etc/kram.conf"], True)
    files.tree_mode = False
    files.view.selectAll()
    files.copy_paths()
    assert QGuiApplication.clipboard().text() == "/usr/bin/kram\n/etc/kram.conf"


def test_empty_folder_of_an_installed_package_is_a_folder(files, tmp_path):
    from types import SimpleNamespace

    from PySide6.QtCore import Qt
    icons = SimpleNamespace(folder="folder", file=lambda name: "file")
    files.tree_model._icons = files.flat_model._icons = icons
    (tmp_path / "empty").mkdir()
    paths = [str(tmp_path / "empty"), str(tmp_path / "file")]
    (tmp_path / "file").touch()

    def icons_shown():
        model = files.view.model()
        index, out = model.index(0, 0), []
        while model.hasChildren(index) and files.tree_mode:  # down to the two entries
            index = model.index(0, 0, index)
        parent = index.parent()
        for r in range(model.rowCount(parent)):
            out.append(model.index(r, 0, parent).data(Qt.ItemDataRole.DecorationRole))
        return out

    for tree in (True, False):
        files.tree_mode = tree
        files.set_files(paths, True)
        assert icons_shown() == ["folder", "file"]
        files.set_files(paths, False)  # not installed: the metadata cannot tell, and the disk is not this package's
        assert icons_shown() == ["file", "file"]


def test_bold_matches_paint(files):
    """The delegate draws the rows with a match in pieces; it has to draw them all, in both views."""
    files.resize(400, 300)
    files.set_files(PATHS, True)
    for tree in (True, False):
        files.tree_mode = tree
        files.filter.setText("kram")
        files._rebuild_now()
        assert files.delegate.filter is not None
        files.view.selectAll()
        assert not files.grab().isNull()
    files.filter.clear()
    files._rebuild_now()
    assert files.delegate.filter is None
