"""File → Export List as CSV…: the rows of the package list, in its order. No Qt.

For scripts and spreadsheets alike: the column names and the values are the same in every language (statuses,
origins and reasons as Kram's own identifiers, the size in bytes), whatever columns the table shows."""
import csv
from collections.abc import Iterable
from typing import TextIO

from .marks import MarkSet
from .model import PkgRow

COLUMNS = ("name", "arch", "status", "installed_version", "latest_version", "latest_arch", "repository",
           "installed_from", "origin", "reason", "update_type", "advisories", "size", "summary", "marked")


def row_values(r: PkgRow, marks: MarkSet) -> list[str | int]:
    mark = marks.get(r.key)
    latest_arch = r.candidate_arch or (r.arch if r.candidate_evr else "")  # noarch -> x86_64 upgrades change it
    return [
        r.name, r.arch, r.status.value, r.installed_evr, r.candidate_evr, latest_arch, r.repo_id, r.from_repo_id, r.origin.value, r.reason.value if r.reason else "",
        r.advisory.level if r.advisory else "", " ".join(a.id for a in r.advisories), r.size, r.summary,
        "" if mark is None else f"{mark.action.value} {mark.evr}".strip(),
    ]


def write_csv(out: TextIO, rows: Iterable[PkgRow], marks: MarkSet) -> int:
    """The header and one line per row; `out` opened with newline="". Returns the number of rows."""
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    n = 0
    for r in rows:
        writer.writerow(row_values(r, marks))
        n += 1
    return n
