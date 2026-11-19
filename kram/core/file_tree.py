"""The files of a package as a tree of folders, and the filter of the Files tab. No Qt here."""
import fnmatch
import re
from collections.abc import Iterable


class Node:
    """A folder or a file. The root is "/"; `name` is the last component of `path`."""
    __slots__ = ("_by_name", "children", "name", "parent", "path", "row")

    def __init__(self, name: str, path: str, parent: "Node | None" = None, row: int = 0):
        self.name = name
        self.path = path
        self.parent = parent
        self.children: list[Node] = []
        self.row = row  # its index in parent.children, for the Qt model's parent()
        self._by_name: dict[str, Node] | None = {}  # None once the tree is built

    @property
    def is_dir(self) -> bool:
        # the metadata do not say which entries are folders: a folder is what has files in it, so a folder the
        # package owns but leaves empty shows as a file
        return bool(self.children)


def build_tree(paths: Iterable[str]) -> Node:
    """The folders of `paths` with their files, every folder above them included, from "/" down. In each folder the
    subfolders come first, then the files, each by name."""
    root = Node("/", "/")
    folders = {"": root, "/": root}  # by path: the files of a package come mostly folder by folder

    def folder(path: str) -> Node:
        node = folders.get(path)
        if node is None:
            up, _slash, name = path.rpartition("/")
            node = _child(folder(up), name, path)
            folders[path] = node
        return node

    for path in paths:
        path = path.rstrip("/")
        up, _slash, name = path.rpartition("/")
        if not name:
            continue
        parent = folder(up)
        if parent._by_name.get(name) is None:
            folders[path] = _child(parent, name, path)
    _finish(root)
    return root


def _child(parent: Node, name: str, path: str) -> Node:
    node = parent._by_name.get(name)
    if node is None:
        node = Node(name, path, parent)
        parent._by_name[name] = node
        parent.children.append(node)
    return node


def _finish(root: Node) -> None:
    stack = [root]
    while stack:
        node = stack.pop()
        node._by_name = None
        node.children.sort(key=lambda c: (not c.children, c.name))
        for i, child in enumerate(node.children):
            child.row = i
        stack.extend(node.children)


class PathFilter:
    """What the filter field keeps, ignoring case: paths with the text anywhere in them; with `*`, `?` or `[…]` a
    shell pattern for the whole file name or the whole path ("*.so", "libfoo*", "/usr/lib*/*.so"), where `*` also
    crosses "/".

    `spans` says what to show in bold: in a tree a file can be there only because a folder above it matched."""

    def __init__(self, text: str):
        self.pattern = "*" in text or "?" in text or "[" in text
        source = fnmatch.translate(text) if self.pattern else re.escape(text)
        self._regex = re.compile(source, re.IGNORECASE | re.DOTALL)

    def match(self, path: str) -> bool:
        if self.pattern:
            return self._regex.match(path) is not None or self._regex.match(path.rpartition("/")[2]) is not None
        return self._regex.search(path) is not None

    def spans(self, path: str, start: int = 0) -> list[tuple[int, int]]:
        """The matched parts of `path[start:]` (one entry's name in the tree), as (begin, end) in that name. A
        pattern matches a whole entry or nothing; a text that runs across a "/" ("share/doc") is bold in the folder
        where it ends ("doc"), the one it brought into the tree."""
        if self.pattern:
            return [(0, len(path) - start)] if self.match(path) else []
        out = []
        for m in self._regex.finditer(path):
            begin, end = max(m.start(), start), m.end()
            if begin < end:
                out.append((begin - start, end - start))
        return out


def path_filter(text: str) -> PathFilter | None:
    """None for an empty filter: everything stays."""
    text = text.strip()
    return PathFilter(text) if text else None

