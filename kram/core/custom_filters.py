"""User-defined sidebar filters (Synaptic's "Custom filters"): named lists of conditions. No Qt.

A filter is stored as plain JSON-able data and compiled against a catalog snapshot into the same kind of
predicate the built-in filters use, so counting and filtering stay in-memory and instant.
"""
import fnmatch
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from ..i18n import N_, _, pgettext
from .model import CatalogSnapshot, Origin, PkgRow, Status

Predicate = Callable[[PkgRow], bool]

INSTALLED_LIKE = (Status.INSTALLED, Status.UPGRADABLE, Status.NEWER, Status.ORPHAN, Status.UNNEEDED)
MB = 1024 * 1024


class Field(Enum):
    NAME = "name"
    NAME_SUMMARY = "name_summary"
    DESCRIPTION = "description"
    STATUS = "status"
    ORIGIN = "origin"
    REPO = "repo"
    GROUP = "group"
    REASON = "reason"
    ARCH = "arch"
    SIZE = "size"


class Op(Enum):
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES = "matches"          # glob: * and ?, case-insensitive, whole value
    IS = "is"
    IS_NOT = "is_not"
    GREATER = "gt"
    LESS = "lt"


TEXT_FIELDS = (Field.NAME, Field.NAME_SUMMARY, Field.DESCRIPTION)
CHOICE_FIELDS = (Field.STATUS, Field.ORIGIN, Field.REPO, Field.GROUP, Field.REASON, Field.ARCH)

FIELD_LABELS = {
    Field.NAME: _("Name"),
    Field.NAME_SUMMARY: _("Name or summary"),
    Field.DESCRIPTION: pgettext("filter field", "Description"),
    Field.STATUS: _("Status"),
    Field.ORIGIN: _("Origin"),
    Field.REPO: _("Repository"),
    Field.GROUP: _("Group"),
    Field.REASON: _("Install reason"),
    Field.ARCH: _("Architecture"),
    Field.SIZE: _("Installed size (MB)"),
}

OP_LABELS = {
    Op.CONTAINS: _("contains"),
    Op.NOT_CONTAINS: _("does not contain"),
    Op.MATCHES: _("matches (* ?)"),
    Op.IS: _("is"),
    Op.IS_NOT: _("is not"),
    Op.GREATER: _("greater than"),
    Op.LESS: _("less than"),
}

# "status" values: the Status enum plus "installed" meaning any installed state
STATUS_ANY_INSTALLED = "any_installed"
STATUS_CHOICES = {
    STATUS_ANY_INSTALLED: N_("Installed (any)"),
    Status.NOT_INSTALLED.value: N_("Not installed"),
    Status.INSTALLED.value: N_("Installed, up to date"),
    Status.UPGRADABLE.value: N_("Upgradable"),
    Status.NEWER.value: N_("Newer than repository"),
    Status.ORPHAN.value: N_("Orphaned (no repository)"),
    Status.UNNEEDED.value: N_("Unneeded dependency"),
}
REASON_CHOICES = {"user": N_("Installed by user"), "dependency": N_("Installed as a dependency")}
ORIGIN_CHOICES = {
    Origin.FEDORA.value: N_("Fedora (official)"), Origin.COPR.value: "COPR",
    Origin.THIRD_PARTY.value: N_("Third-party"), Origin.LOCAL.value: N_("Local (@commandline)"),
    Origin.UNKNOWN.value: N_("Unknown (not recorded)"),
}


def ops_for(f: Field) -> list[Op]:
    if f in TEXT_FIELDS:
        return [Op.CONTAINS, Op.NOT_CONTAINS, Op.MATCHES, Op.IS]
    if f is Field.SIZE:
        return [Op.GREATER, Op.LESS]
    return [Op.IS, Op.IS_NOT]


def choices(f: Field, snap: CatalogSnapshot | None) -> list[tuple[str, str]] | None:
    """(value, label) for fields with a fixed set of values; None for free text/number fields."""
    if f is Field.STATUS:
        return [(v, _(label)) for v, label in STATUS_CHOICES.items()]
    if f is Field.REASON:
        return [(v, _(label)) for v, label in REASON_CHOICES.items()]
    if f is Field.ORIGIN:
        return [(v, _(label)) for v, label in ORIGIN_CHOICES.items()]
    if snap is None:
        return []
    if f is Field.REPO:
        repos = {r.origin_repo for r in snap.rows} | {r.repo_id for r in snap.rows}
        return [(r, r) for r in sorted(repos - {""})]
    if f is Field.GROUP:
        return [(g.id, g.name) for g in snap.groups]
    if f is Field.ARCH:
        return [(a, a) for a in sorted({r.arch for r in snap.rows})]
    return None


@dataclass(slots=True)
class Condition:
    field: Field
    op: Op
    value: str

    def to_dict(self) -> dict:
        return {"field": self.field.value, "op": self.op.value, "value": self.value}

    @classmethod
    def from_dict(cls, d: dict) -> "Condition":
        c = cls(Field(d["field"]), Op(d["op"]), str(d.get("value", "")))
        if c.op not in ops_for(c.field):
            raise ValueError(f"{c.op.value} does not apply to {c.field.value}")
        return c


@dataclass(slots=True)
class CustomFilter:
    name: str
    conditions: list[Condition] = field(default_factory=list)
    match_all: bool = True   # False: any condition

    def to_dict(self) -> dict:
        return {"name": self.name, "match_all": self.match_all, "conditions": [c.to_dict() for c in self.conditions]}

    @classmethod
    def from_dict(cls, d: dict) -> "CustomFilter":
        return cls(str(d["name"]), [Condition.from_dict(c) for c in d.get("conditions", [])],
                   bool(d.get("match_all", True)))

    def compile(self, snap: CatalogSnapshot) -> Predicate:
        preds = [_compile(c, snap) for c in self.conditions]
        if not preds:
            return lambda _r: True
        if self.match_all:
            return lambda r: all(p(r) for p in preds)
        return lambda r: any(p(r) for p in preds)


def load_filters(data: list) -> list[CustomFilter]:
    """Filters from settings; entries that are malformed (e.g. from a newer version) are skipped."""
    out = []
    for d in data if isinstance(data, list) else []:
        try:
            out.append(CustomFilter.from_dict(d))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _text_test(op: Op, value: str) -> Callable[[str], bool]:
    v = value.lower()
    match op:
        case Op.CONTAINS:
            return lambda s: v in s.lower()
        case Op.NOT_CONTAINS:
            return lambda s: v not in s.lower()
        case Op.MATCHES:
            return lambda s: fnmatch.fnmatchcase(s.lower(), v)
        case _:
            return lambda s: s.lower() == v


def _compile(c: Condition, snap: CatalogSnapshot) -> Predicate:
    if c.field in TEXT_FIELDS:
        test = _text_test(c.op, c.value)
        if c.field is Field.NAME:
            return lambda r: test(r.name)
        if c.field is Field.NAME_SUMMARY:
            if c.op is Op.NOT_CONTAINS:  # neither of them contains it
                return lambda r: test(r.name) and test(r.summary)
            return lambda r: test(r.name) or test(r.summary)
        descriptions = {r.key: d for r, d in zip(snap.rows, snap.descriptions, strict=False)}
        return lambda r: test(descriptions.get(r.key, ""))

    if c.field is Field.SIZE:
        try:
            limit = float(c.value.replace(",", ".")) * MB
        except ValueError:
            return lambda _r: False
        return (lambda r: r.size > limit) if c.op is Op.GREATER else (lambda r: r.size < limit)

    match c.field:
        case Field.STATUS:
            if c.value == STATUS_ANY_INSTALLED:
                hit = lambda r: r.status in INSTALLED_LIKE
            else:
                hit = lambda r: r.status.value == c.value
        case Field.ORIGIN:
            hit = lambda r: r.origin.value == c.value
        case Field.REPO:
            hit = lambda r: c.value in (r.origin_repo, r.repo_id)
        case Field.GROUP:
            names = next((g.packages for g in snap.groups if g.id == c.value), frozenset())
            hit = lambda r: r.name in names
        case Field.REASON:
            want_user = c.value == "user"
            hit = lambda r: r.installed and r.user_installed == want_user
        case _:  # ARCH
            hit = lambda r: r.arch == c.value
    return hit if c.op is Op.IS else (lambda r: not hit(r))


def conditions_for_view(entry_id: str, search: str, search_field: Field | None) -> list[Condition]:
    """Conditions that reproduce a sidebar entry plus a search, for "New filter from current view"."""
    out: list[Condition] = []
    status_map = {
        "status:installed": (Field.STATUS, STATUS_ANY_INSTALLED),
        "status:not-installed": (Field.STATUS, Status.NOT_INSTALLED.value),
        "status:upgradable": (Field.STATUS, Status.UPGRADABLE.value),
        "status:unneeded": (Field.STATUS, Status.UNNEEDED.value),
        "status:orphan": (Field.STATUS, Status.ORPHAN.value),
        "status:newer": (Field.STATUS, Status.NEWER.value),
        "status:user": (Field.REASON, "user"),
    }
    kind, _sep, value = entry_id.partition(":")
    if entry_id in status_map:
        f, v = status_map[entry_id]
        out.append(Condition(f, Op.IS, v))
    elif kind == "origin" and value != "all":
        out.append(Condition(Field.ORIGIN, Op.IS, value))
    elif kind == "repo":
        out.append(Condition(Field.REPO, Op.IS, value))
    elif kind == "group" and value != "all":
        out.append(Condition(Field.GROUP, Op.IS, value))
    elif kind == "custom":
        pass  # the caller copies that filter's own conditions
    if search and search_field is not None:
        out.append(Condition(search_field, Op.CONTAINS, search))
    return out
