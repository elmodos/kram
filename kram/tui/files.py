"""The Files tab of the terminal front end (docs/TUI_SPEC.md §7.4.3): the package's files as a tree drawn with box
drawing, every folder open, or as a flat list of full paths; a filter; a cursor and a selection of several lines.
The tree and the filter are kram.core.file_tree's, the words and rules kram.app.files', as in the GUIs.

The rows are built when the tab is shown, not for every package the cursor passes; the lines are drawn only when
they are in sight (`line`), as a package can have tens of thousands of files.
"""
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text

from ..app.files import count_text, name_spans, partial_notice, shown_paths
from ..core.file_tree import Node, PathFilter, build_tree, path_filter
from .glyphs import Glyphs
from .palette import over, role


@dataclass(frozen=True)
class FileRow:
    prefix: str  # the tree's branches
    name: str    # the entry's name in the tree, the full path in the list
    path: str
    folder: bool


def tree_rows(root: Node, glyphs: Glyphs) -> list[FileRow]:
    """"/" and everything under it, depth first, each child after the branches that lead to it."""
    rows = [FileRow("", "/", "/", True)]

    def children(node: Node, lead: str) -> list[tuple[Node, str, bool]]:
        """(child, the branches before it, whether it is the last), in the reverse order, for the stack."""
        n = len(node.children)
        return [(c, lead, i == n - 1) for i, c in reversed(list(enumerate(node.children)))]
    stack = children(root, "")
    while stack:
        node, lead, last = stack.pop()
        rows.append(FileRow(lead + (glyphs.last if last else glyphs.branch), node.name, node.path, node.is_dir))
        if node.children:
            stack += children(node, lead + (" " * len(glyphs.through) if last else glyphs.through))
    return rows


def list_rows(paths: list[str]) -> list[FileRow]:
    return [FileRow("", p, p, False) for p in paths]


class FileState:
    """The tab's content: the paths of the package, tree or list, the filter, the cursor and the selection."""

    def __init__(self, glyphs: Glyphs):
        self.glyphs = glyphs
        self.paths: list[str] = []
        self.installed = True
        self.tree = True
        self.filter_text = ""
        self.filter: PathFilter | None = None
        self.rows: list[FileRow] = []
        self.shown = 0  # paths the filter keeps
        self.cursor = 0
        self.anchor: int | None = None
        self.selection: set[int] = set()
        self._stale = True

    def set_files(self, paths: list[str], installed: bool) -> None:
        """A package's files; the filter stays, to look for the same file in the next package."""
        self.paths, self.installed = list(paths), installed
        self._stale = True

    def set_filter(self, text: str) -> None:
        if text != self.filter_text:
            self.filter_text = text
            self._stale = True

    def set_tree(self, on: bool) -> None:
        if on != self.tree:
            self.tree = on
            self._stale = True

    def build(self) -> bool:
        """The rows, if something changed since they were built; True when they were built again."""
        if not self._stale:
            return False
        self._stale = False
        self.filter = f = path_filter(self.filter_text)
        paths = shown_paths(self.paths, f)
        self.shown = len(paths)
        if not paths:
            self.rows = []
        elif self.tree:
            self.rows = tree_rows(build_tree(paths), self.glyphs)
        else:
            self.rows = list_rows(paths)
        self.cursor = 0
        self.anchor = None
        self.selection = set()
        return True

    # ---------------------------------------------------------------- the cursor and the selection

    def go(self, pos: int, extend: bool = False) -> None:
        if not self.rows:
            return
        pos = max(0, min(len(self.rows) - 1, pos))
        if extend:
            if self.anchor is None:
                self.anchor = self.cursor
            low, high = sorted((self.anchor, pos))
            self.selection = set(range(low, high + 1))
        else:
            self.anchor = None
            self.selection = set()
        self.cursor = pos

    def selected_paths(self) -> list[str]:
        if not self.rows:
            return []
        positions = sorted(self.selection) if len(self.selection) > 1 else [self.cursor]
        return [self.rows[p].path for p in positions]

    def current_path(self) -> str:
        return self.rows[self.cursor].path if self.rows else ""

    # ---------------------------------------------------------------- drawing

    def info(self) -> Text:
        """The line above the files: how many, and that the metadata of a package not installed list only some."""
        text = Text(count_text(self.shown, len(self.paths)), role("muted"))
        if not self.installed:
            text.append("  ")
            text.append(partial_notice(), role("muted") + Style(italic=True))
        return text

    def line(self, pos: int, focused: bool) -> Text:
        """The row at `pos`: the selection's margin, the branches, the name with what the filter matched in bold, a
        "/" after a folder."""
        r = self.rows[pos]
        base = Style()
        if pos == self.cursor:
            base = role("cursor") if focused else role("cursor-blurred")
        selected = len(self.selection) > 1 and pos in self.selection
        text = Text(self.glyphs.selected if selected else " ", over(base, role("marked")) if selected else base)
        text.append(r.prefix, base if pos == self.cursor else role("muted"))
        name = Text(r.name, base)
        for begin, end in name_spans(r.name, r.path, self.filter):
            name.stylize(Style(bold=True), begin, end)
        text.append_text(name)
        if r.folder and r.path != "/":
            text.append("/", base)
        return text
