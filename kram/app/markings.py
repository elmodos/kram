"""File → Save Markings As… and Read Markings…: the marked changes in a text file, chosen and reported through the
Ui port."""
from collections.abc import Callable
from pathlib import Path

from ..core.marks import MarkSet, dump_marks, parse_marks
from ..core.model import PkgRow
from ..core.settings import store as settings
from ..i18n import _, ngettext
from .ports import Ui

DIR_KEY = "markings/dir"


def _file_filter() -> str:
    return _("Text files (*.txt);;All files (*)")


def _markings_dir() -> str:
    return settings.get(DIR_KEY, str(Path.home()))


def _remember_dir(path: str) -> None:
    settings.set(DIR_KEY, str(Path(path).parent))


def save_markings(ui: Ui, marks: MarkSet, done: Callable[[str], None]) -> None:
    """Ask where, and save; `done(path)` once saved. Nothing when cancelled; a failure says why."""
    def chosen(path: str | None) -> None:
        if not path:
            return
        try:
            Path(path).write_text(dump_marks(marks), encoding="utf-8")
        except OSError as e:
            ui.error(_("Save Markings"), _("Could not save {path}:\n\n{error}").format(
                path=path, error=e.strerror or e))
            return
        _remember_dir(path)
        done(path)
    ui.choose_save_file(_("Save Markings"), str(Path(_markings_dir()) / "kram-markings.txt"), _file_filter(), chosen)


def ask_markings_file(ui: Ui, done: Callable[[str], None]) -> None:
    ui.choose_open_file(_("Read Markings"), _markings_dir(), _file_filter(), lambda path: path and done(path))


def read_markings(ui: Ui, path: str, marks: MarkSet, rows: dict[tuple[str, str], PkgRow],
                  marked: Callable[[int], None]) -> None:
    """Add the marks from a markings file to `marks`, call `marked` with the number of packages marked
    (not when the file could not be read), then report what could not be marked."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        ui.error(_("Read Markings"), _("Could not read {path}:\n\n{error}").format(
            path=path, error=getattr(e, "strerror", None) or e))
        return
    _remember_dir(path)
    package_marks, bad_lines = parse_marks(text)
    skipped = [f"{name}.{arch}" for (name, arch), mark in package_marks
               if not ((row := rows.get((name, arch))) and marks.set(row, mark.action, mark.evr))]
    n = len(package_marks) - len(skipped)
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
        ui.warn(_("Read Markings"), ngettext("{n} package marked.", "{n} packages marked.", n).format(n=n) + "\n\n"
                + "\n\n".join(problems))
