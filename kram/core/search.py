"""In-memory package search with ranking. No Qt, no libdnf5.

Query syntax (case-insensitive):
  - several words: every word must match (AND)
  - ^word / word$: anchor to the start / end of the field
  - * and ?: glob wildcards
Ranking tiers (lower is better): exact name, name prefix, name substring, summary, description.
Within a tier: installed first, then shorter names, then alphabetical.
"""
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum

from ..i18n import _, pgettext
from .model import PkgRow


class Mode(IntEnum):
    NAME = 0
    NAME_SUMMARY = 1
    DESCRIPTION = 2
    PROVIDES = 3   # resolved by Catalog.search_provides (libdnf5 and its capability index)
    FILE = 4       # resolved by libdnf5 (Catalog.search_files)

    @property
    def local(self) -> bool:
        return self <= Mode.DESCRIPTION


MODE_LABELS = {
    Mode.NAME: _("Name"),
    Mode.NAME_SUMMARY: _("Name + summary"),
    Mode.DESCRIPTION: pgettext("search mode", "Description"),
    Mode.PROVIDES: _("Provides"),
    Mode.FILE: _("File"),
}

EXACT, PREFIX, NAME, SUMMARY, DESCRIPTION = range(5)
NO_MATCH = 99


@dataclass(frozen=True, slots=True)
class Term:
    text: str                        # lowercased; for plain terms the substring itself
    regex: re.Pattern | None = None  # set when the term uses ^, $ or globs

    @classmethod
    def parse(cls, word: str) -> "Term":
        word = word.lower()
        if not any(c in word for c in "*?^$"):
            return cls(word)
        start, end = word.startswith("^"), word.endswith("$") and len(word) > 1
        body = word[1 if start else 0: -1 if end else None]
        pattern = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in body)
        return cls(body, re.compile(("^" if start else "") + pattern + ("$" if end else "")))

    def tier(self, name: str, summary: str, description: str | None, mode: Mode) -> int:
        """Best tier at which this term matches the row, or NO_MATCH."""
        if self.regex is None:
            pos = name.find(self.text)
            if pos >= 0:
                return EXACT if name == self.text else PREFIX if pos == 0 else NAME
            if mode >= Mode.NAME_SUMMARY and self.text in summary:
                return SUMMARY
            if mode >= Mode.DESCRIPTION and description is not None and self.text in description:
                return DESCRIPTION
            return NO_MATCH
        m = self.regex.search(name)
        if m:
            return EXACT if m.start() == 0 and m.end() == len(name) else PREFIX if m.start() == 0 else NAME
        if mode >= Mode.NAME_SUMMARY and self.regex.search(summary):
            return SUMMARY
        if mode >= Mode.DESCRIPTION and description is not None and self.regex.search(description):
            return DESCRIPTION
        return NO_MATCH


def parse_query(text: str) -> list[Term]:
    return [Term.parse(w) for w in text.split() if w not in ("^", "$")]


class SearchIndex:
    """Lowercased copies of the searchable fields, aligned with the snapshot's row list."""

    def __init__(self, rows: list[PkgRow], descriptions: list[str] | None = None):
        self.rows = rows
        self.names = [r.name.lower() for r in rows]
        self.summaries = [r.summary.lower() for r in rows]
        self.descriptions = [d.lower() for d in descriptions] if descriptions is not None else None

    def search(self, text: str, mode: Mode, candidates: Iterable[int] | None = None) -> list[int]:
        """Indices of matching rows, best first."""
        terms = parse_query(text)
        if not terms:
            return list(candidates) if candidates is not None else list(range(len(self.rows)))
        names, summaries, descs, rows = self.names, self.summaries, self.descriptions, self.rows
        scored = []
        for i in candidates if candidates is not None else range(len(rows)):
            name = names[i]
            worst = 0
            for t in terms:
                tier = t.tier(name, summaries[i], descs[i] if descs is not None else None, mode)
                if tier > worst:
                    worst = tier
                    if worst == NO_MATCH:
                        break
            if worst != NO_MATCH:
                scored.append((worst, not rows[i].installed, len(name), name, i))
        scored.sort()
        return [s[-1] for s in scored]

    def rank_keys(self, indices: Iterable[int]) -> list[int]:
        """Order for results that came from libdnf5 (provides/file): installed first, then name."""
        return sorted(indices, key=lambda i: (not self.rows[i].installed, len(self.names[i]), self.names[i]))


class NarrowingSearch:
    """SearchIndex.search that reuses its last answer while the user keeps typing.

    Words are ANDed and an added character only makes a word stricter, so whatever matches "kern" also matched
    "ker": the next search only has to look at the rows that did, a few thousand instead of 70k. Not after a "$":
    "ab$" is anchored, "ab$c" is a literal, which may match rows "ab$" did not."""

    def __init__(self, index: SearchIndex):
        self.index = index
        self._last: tuple[Mode, str, set[int], list[int]] | None = None  # mode, text, candidates, what matched

    def search(self, text: str, mode: Mode, candidates: list[int]) -> list[int]:
        typed = text.strip().lower()
        allowed = set(candidates)
        pool = candidates
        if self._last is not None:
            last_mode, last_text, last_allowed, last_found = self._last
            # the last answer is complete for its candidates: a row the sidebar filter lets in now but did not then
            # (a new mark, a changed filter) was never looked at
            if (last_mode == mode and last_text and "$" not in last_text and typed.startswith(last_text)
                    and allowed <= last_allowed):
                pool = [i for i in last_found if i in allowed]
        found = self.index.search(text, mode, pool)
        self._last = (mode, typed, allowed, found)
        return found
