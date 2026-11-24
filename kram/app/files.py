"""The Files tab's words and rules, the same in every front end: which paths the filter keeps, what the count says,
which part of a name is bold, and when a file can be shown in the file manager. The tree itself and the filter are
kram.core.file_tree."""
import os

from ..core.file_tree import PathFilter
from ..i18n import _, ngettext

FILES_VIEW_KEY = "details/files-view"  # the setting: "tree" or "list"


def filter_placeholder() -> str:
    return _("Filter files: text, or a pattern like *.so")


def partial_notice() -> str:
    """Above the files of a package that is not installed."""
    return _("Not installed: repository metadata lists only some of the files.")


def shown_paths(paths: list[str], f: PathFilter | None) -> list[str]:
    return paths if f is None else [p for p in paths if f.match(p)]


def count_text(shown: int, total: int) -> str:
    """"3 files", or "1 of 3 files" while the filter leaves some out."""
    if shown == total:
        return ngettext("{n} file", "{n} files", total).format(n=total)
    return ngettext("{shown} of {n} file", "{shown} of {n} files", total).format(shown=shown, n=total)


def name_spans(name: str, path: str, f: PathFilter | None) -> list[tuple[int, int]]:
    """The parts of `name` (the last part of `path`, or all of it in the flat list) the filter matched, to show in
    bold: in the tree a file can be shown only because a folder above it matched, and then nothing in the file's own
    name is."""
    return f.spans(path, len(path) - len(name)) if f is not None and name and path else []


def can_show_in_file_manager(installed: bool, path: str) -> bool:
    """Only the files of an installed package are on the disk; a folder it owns but left empty may be gone too."""
    return installed and bool(path) and os.path.lexists(path)
