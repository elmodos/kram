"""RPM version ordering for sorting table columns."""
import functools
from collections.abc import Iterable

import rpm


def split_evr(evr: str) -> tuple[str, str, str]:
    """'1:2.3-4.fc44' -> ('1', '2.3', '4.fc44'); epoch defaults to '0'."""
    epoch, sep, rest = evr.partition(":")
    if not sep:
        epoch, rest = "0", evr
    version, _, release = rest.rpartition("-")
    if not version:  # no release part
        version, release = release, ""
    return epoch, version, release


def evr_ranks(evrs: Iterable[str]) -> dict[str, int]:
    """Map each EVR to its position in RPM order. Sorting ~20k unique EVRs once is far cheaper than calling
    rpm.labelCompare inside every table sort."""
    unique = sorted(set(evrs) - {""})
    unique.sort(key=functools.cmp_to_key(lambda a, b: rpm.labelCompare(split_evr(a), split_evr(b))))
    return {evr: i for i, evr in enumerate(unique)}
