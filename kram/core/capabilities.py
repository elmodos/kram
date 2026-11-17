"""Capability names -> the catalog's packages that provide them, for Provides searches by part of a name or a glob.

libdnf5 answers those by scanning every capability in the pool: 0.7-1 s per query here, without giving Python a
chance to run meanwhile, so the window froze for that long (and much longer on old laptops). Built once from the
installed and candidate version of every catalog row; a search over it takes tens of milliseconds. No Qt, no libdnf5.
"""
import fnmatch
import re

Key = tuple[str, str]  # (name, arch) of a catalog row
GLOB_CHARS = "*?["


def is_glob(text: str) -> bool:
    return any(c in text for c in GLOB_CHARS)


def match(index: dict[str, set[Key]], text: str) -> set[Key]:
    """Packages with a capability matching `text`: as a glob when it has one (case-sensitive, like libdnf5),
    otherwise as a substring of the capability's name."""
    if is_glob(text):
        rx = re.compile(fnmatch.translate(text))
        names = (n for n in index if rx.match(n))
    else:
        names = (n for n in index if text in n)
    found: set[Key] = set()
    for name in names:
        found |= index[name]
    return found


RICH_KEYWORDS = frozenset({"and", "or", "if", "else", "with", "without", "unless"})
VERSION_OPERATORS = frozenset({"<", ">", "=", "<=", ">=", "<>"})


def dependency_names(requirement: str) -> set[str]:
    """The capability names a requirement can be met by. A rich dependency, "(python3dist(aiohttp) >= 3.9 with
    python3dist(aiohttp) < 4)", names several; versions and keywords are left out. Names keep their own
    parentheses: only the ones a name does not open are grouping."""
    if not requirement.startswith("("):
        return {requirement.split(" ", 1)[0]}
    names = set()
    for token in requirement.split():
        token = token.lstrip("(")
        while token.endswith(")") and token.count(")") > token.count("("):
            token = token[:-1]
        if token and token not in RICH_KEYWORDS and token not in VERSION_OPERATORS and not token[0].isdigit():
            names.add(token)
    return names
