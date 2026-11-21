"""A small document model for the text Kram shows in its detail tabs, the empty list and What's New: exactly what
those need, no general rich text. Each front end renders a `Doc` its own way (Qt: HTML for QTextBrowser, in
kram.qt.doc_html; GTK: labels with Pango markup), so the content is written once.

    Doc    = list[Block]
    Block  = Heading | Para | Table | Section | Bullets | Rule | Inline
    Span   = str | Bold | Italic | Small | Colored | Link | Break

A plain `str` is text: front ends escape it. Line breaks inside a text are not breaks; a `Break` is.
"""
import string
from dataclasses import dataclass, field
from typing import Literal, Union

# ---------------------------------------------------------------- inline


@dataclass(frozen=True)
class Bold:
    children: tuple["Span", ...]


@dataclass(frozen=True)
class Italic:
    children: tuple["Span", ...]


@dataclass(frozen=True)
class Small:
    children: tuple["Span", ...]


@dataclass(frozen=True)
class Colored:
    """Text in a colour of its own ("#2f7a1f", "gray"): the install dialog's marks of what satisfies a requirement."""
    color: str
    children: tuple["Span", ...]


@dataclass(frozen=True)
class Break:
    pass


LinkKind = Literal["pkg", "dep", "web", "action"]


@dataclass(frozen=True)
class Link:
    """`pkg`: a package, target "name.arch"; `dep`: a requirement string, to look up what provides it; `web`: a web
    address (only http/https are opened, kram.app.ports.is_web_link); `action`: something the window does (the
    empty list's links, kram.app.empty_list)."""
    kind: LinkKind
    target: str
    children: tuple["Span", ...]


Span = Union[str, Bold, Italic, Small, Colored, Link, Break]


def bold(*children: Span) -> Bold:
    return Bold(children)


def italic(*children: Span) -> Italic:
    return Italic(children)


def small(*children: Span) -> Small:
    return Small(children)


def colored(color: str, *children: Span) -> Colored:
    return Colored(color, children)


def link(kind: LinkKind, target: str, *children: Span) -> Link:
    return Link(kind, target, children or (target,))


BR = Break()


def lines(text: str) -> list[Span]:
    """`text` with its line breaks as `Break`s."""
    out: list[Span] = []
    for i, line in enumerate(text.split("\n")):
        if i:
            out.append(BR)
        if line:
            out.append(line)
    return out


def filled(template: str, **values: Span) -> list[Span]:
    """A translated `str.format` template with spans for its fields: `filled(_("To download: {size}."),
    size=bold("12 MB"))`. The translation decides where the fields go."""
    out: list[Span] = []
    for text, name, _spec, _conv in string.Formatter().parse(template):
        if text:
            out.append(text)
        if name is not None:
            value = values[name]
            out.append(value if not isinstance(value, (int, float)) else str(value))
    return out


def joined(items: list[list[Span]], separator: list[Span]) -> list[Span]:
    out: list[Span] = []
    for i, item in enumerate(items):
        if i:
            out += separator
        out += item
    return out


# ---------------------------------------------------------------- blocks

ParaRole = Literal["", "error", "mono"]


@dataclass(frozen=True)
class Heading:
    spans: tuple[Span, ...]
    level: int = 3


@dataclass(frozen=True)
class Para:
    """`role`: "error" in the error colour (a title that says something cannot be done); "mono": a tool's message,
    small and monospaced, its line breaks kept."""
    spans: tuple[Span, ...]
    role: ParaRole = ""


@dataclass(frozen=True)
class Table:
    """Label / value rows (the General tab)."""
    rows: tuple[tuple[tuple[Span, ...], tuple[Span, ...]], ...]


@dataclass(frozen=True)
class Section:
    """A titled list of items with its count ("Requires (12)"), cut short with "…and {n} more" (`more_text`).
    `marked`: each item starts with a mark of its own, so it gets no bullet."""
    title: str
    count: int
    items: tuple[tuple[Span, ...], ...]
    more_text: str = ""
    marked: bool = False


@dataclass(frozen=True)
class Bullets:
    items: tuple[tuple[Span, ...], ...]


@dataclass(frozen=True)
class Rule:
    pass


@dataclass(frozen=True)
class Inline:
    """Text on its own, without a paragraph (a one-line note such as "No dependencies")."""
    spans: tuple[Span, ...]


Block = Union[Heading, Para, Table, Section, Bullets, Rule, Inline]


@dataclass
class Doc:
    blocks: list[Block] = field(default_factory=list)

    def __add__(self, other: "Doc") -> "Doc":
        return Doc(self.blocks + other.blocks)

    def __bool__(self) -> bool:
        return bool(self.blocks)


def para(*spans: Span, role: ParaRole = "") -> Para:
    return Para(tuple(spans), role)


def plain_text(doc: Doc) -> str:
    """The visible text, without markup: for tests, and for a toolkit that needs the words alone."""
    def spans(items) -> str:
        out = []
        for s in items:
            if isinstance(s, str):
                out.append(s)
            elif isinstance(s, Break):
                out.append("\n")
            else:
                out.append(spans(s.children))
        return "".join(out)

    parts = []
    for b in doc.blocks:
        if isinstance(b, (Heading, Para, Inline)):
            parts.append(spans(b.spans))
        elif isinstance(b, Table):
            parts += [f"{spans(label)}\t{spans(value)}" for label, value in b.rows]
        elif isinstance(b, Section):
            parts.append(f"{b.title} ({b.count})")
            parts += [spans(item) for item in b.items]
            if b.more_text:
                parts.append(b.more_text)
        elif isinstance(b, Bullets):
            parts += [spans(item) for item in b.items]
    return "\n".join(parts)
