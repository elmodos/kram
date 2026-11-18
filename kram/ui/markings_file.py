"""File → Save Markings As… and Read Markings…: the marked changes in a text file."""
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from ..core.marks import MarkSet, dump_marks, parse_marks
from ..core.model import GroupInfo, PkgRow
from ..i18n import _, ngettext


def _file_filter() -> str:
    return _("Text files (*.txt);;All files (*)")


def _markings_dir() -> str:
    return QSettings().value("markings/dir", str(Path.home()))


def _remember_dir(path: str) -> None:
    QSettings().setValue("markings/dir", str(Path(path).parent))


def save_markings(parent: QWidget, marks: MarkSet) -> str | None:
    """Ask where, and save: the path saved to, None when cancelled or failed (after saying why)."""
    path, _filter = QFileDialog.getSaveFileName(parent, _("Save Markings"),
                                                str(Path(_markings_dir()) / "kram-markings.txt"), _file_filter())
    if not path:
        return None
    try:
        Path(path).write_text(dump_marks(marks), encoding="utf-8")
    except OSError as e:
        QMessageBox.critical(parent, _("Save Markings"), _("Could not save {path}:\n\n{error}").format(
            path=path, error=e.strerror or e))
        return None
    _remember_dir(path)
    return path


def ask_markings_file(parent: QWidget) -> str | None:
    path, _filter = QFileDialog.getOpenFileName(parent, _("Read Markings"), _markings_dir(), _file_filter())
    return path or None


def read_markings(parent: QWidget, path: str, marks: MarkSet, rows: dict[tuple[str, str], PkgRow],
                  group: Callable[[str], GroupInfo | None], marked: Callable[[int], None]) -> None:
    """Add the marks from a markings file to `marks`, call `marked` with the number of packages and groups marked
    (not when the file could not be read), then report what could not be marked."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        QMessageBox.critical(parent, _("Read Markings"), _("Could not read {path}:\n\n{error}").format(
            path=path, error=getattr(e, "strerror", None) or e))
        return
    _remember_dir(path)
    package_marks, group_marks, bad_lines = parse_marks(text)
    skipped = [f"{name}.{arch}" for (name, arch), mark in package_marks
               if not ((row := rows.get((name, arch))) and marks.set(row, mark.action, mark.evr))]
    skipped += [f"@{gid}" for gid, action in group_marks
                if not ((g := group(gid)) and marks.set_group(g, action))]
    n = len(package_marks) + len(group_marks) - len(skipped)
    marked(n)
    if skipped or bad_lines:
        problems = []
        if skipped:
            problems.append(ngettext(
                "{n} marking no longer applies (package not found, already in that state, …):",
                "{n} markings no longer apply (packages not found, already in that state, …):",
                len(skipped)).format(n=len(skipped)) + "\n" + ", ".join(skipped))
        if bad_lines:
            problems.append(ngettext("{n} line is not a valid marking: {lines}",
                                     "{n} lines are not valid markings: {lines}", len(bad_lines))
                            .format(n=len(bad_lines), lines=", ".join(map(str, bad_lines))))
        QMessageBox.warning(parent, _("Read Markings"),
                            ngettext("{n} package marked.", "{n} packages marked.", n).format(n=n) + "\n\n"
                            + "\n\n".join(problems))
