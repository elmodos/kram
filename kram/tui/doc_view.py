"""The terminal's rendering of kram.app.doc (docs/TUI_SPEC.md §7.4.2, §7.4.5), the counterpart of kram.gtk.doc_view:
a document as lines of text for a width. Headings are bold, labels muted, links underlined in the info role; long
text wraps, a word longer than the line is folded.

Each link carries its number in the document as the style's meta (`LINK`), which survives the wrapping: the panel
finds the line of a link from it, highlights the focused one and knows which link a click hit. A web link is also
written as an OSC 8 hyperlink (`Style(link=…)`, which Textual passes on to the terminal), so that terminals that
know them make it clickable.
"""
from dataclasses import dataclass, field

from rich.cells import cell_len
from rich.console import Console
from rich.style import Style
from rich.text import Text

from ..app.doc import Bold, Break, Bullets, Doc, Heading, Inline, Italic, Link, Para, Rule, Section, Small, Table
from ..app.ports import is_web_link
from .glyphs import Glyphs
from .palette import role

LINK = "kram-link"  # the meta key of a link's number
LABEL_MAX = 24      # a table's label column at most, and at most a third of the width
INDENT = 2          # the items of a section


@dataclass
class DocLines:
    """A document laid out for a width: its lines, its links in reading order and the first line of each."""
    lines: list[Text] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    link_lines: list[int] = field(default_factory=list)


def link_of(style: Style | None) -> int | None:
    """The number of the link a style belongs to, or None."""
    if style is None:
        return None
    return style.meta.get(LINK) if style._meta else None


def spans_text(spans, links: list[Link], base: Style = Style(), keep_newlines: bool = False) -> Text:  # noqa: B008
    """Spans as one Text; their links are appended to `links`. A line break inside a text is a space (the doc model's
    rule; descriptions are wrapped for 80 columns and wrap again here), unless `keep_newlines` (a tool's message)."""
    text = Text()

    def add(items, style: Style) -> None:
        for s in items:
            if isinstance(s, str):
                text.append(s if keep_newlines else s.replace("\n", " "), style)
            elif isinstance(s, Break):
                text.append("\n", style)
            elif isinstance(s, Bold):
                add(s.children, style + Style(bold=True))
            elif isinstance(s, Italic):
                add(s.children, style + Style(italic=True))
            elif isinstance(s, Small):
                add(s.children, style + role("muted"))
            elif isinstance(s, Link):
                link_style = style + role("info") + Style(underline=True) + Style.from_meta({LINK: len(links)})
                if s.kind == "web" and is_web_link(s.target):
                    link_style += Style(link=s.target)
                links.append(s)
                add(s.children, link_style)
            else:  # Colored: no colour of its own in a terminal (§9.1)
                add(s.children, style)
    add(spans, base)
    return text


def wrapped(text: Text, width: int, console: Console) -> list[Text]:
    if not text.plain:
        return [text]
    return list(text.wrap(console, max(1, width), overflow="fold"))


class _Writer:
    def __init__(self, width: int, glyphs: Glyphs, console: Console):
        self.width, self.glyphs, self.console = max(1, width), glyphs, console
        self.out = DocLines()

    def lines(self, texts: list[Text]) -> None:
        self.out.lines += texts

    def text(self, text: Text, indent: int = 0, first: Text | None = None) -> None:
        """`text` wrapped, `indent` cells in; `first` stands before its first line (a bullet, a label) instead of
        that many spaces."""
        for i, line in enumerate(wrapped(text, self.width - indent, self.console)):
            lead = first if i == 0 and first is not None else Text(" " * indent)
            self.out.lines.append(lead + line if indent else line)

    def block(self, b) -> None:
        links = self.out.links
        if isinstance(b, Heading):
            self.text(spans_text(b.spans, links, Style(bold=True)))
        elif isinstance(b, Para):
            if b.role == "error":
                self.text(spans_text(b.spans, links, role("danger")))
            elif b.role == "mono":
                self.text(spans_text(b.spans, links, role("muted"), keep_newlines=True))
            else:
                self.text(spans_text(b.spans, links))
        elif isinstance(b, Inline):
            self.text(spans_text(b.spans, links))
        elif isinstance(b, Table):
            self.table(b)
        elif isinstance(b, Section):
            self.section(b)
        elif isinstance(b, Bullets):
            for item in b.items:
                self.item(spans_text(item, links))
        elif isinstance(b, Rule):
            self.out.lines.append(Text(self.glyphs.rule * self.width, role("rule")))
        else:
            raise TypeError(b)

    def item(self, text: Text, marked: bool = False) -> None:
        """An item of a list: a bullet, or none for one that starts with a mark of its own."""
        bullet = "" if marked else self.glyphs.item + " "
        indent = INDENT + cell_len(bullet)
        if cell_len(text.plain) <= self.width - indent and "\n" not in text.plain:
            self.out.lines.append(Text(" " * INDENT + bullet) + text)  # most are: no wrapping to do
        else:
            self.text(text, indent, Text(" " * INDENT + bullet))

    def table(self, b: Table) -> None:
        """Label / value rows: the labels muted in a column of their own; on a narrow panel each label stands on its
        own line above its value."""
        links = self.out.links
        labels = [spans_text(label, links, role("muted")) for label, _value in b.rows]
        column = min(max((t.cell_len for t in labels), default=0), LABEL_MAX, self.width // 3)
        for label, (_label, value) in zip(labels, b.rows, strict=True):
            value_text = spans_text(value, links)
            if self.width < 40 or column < 8:
                self.text(label)
                self.text(value_text, INDENT)
                continue
            if label.cell_len > column:
                label.truncate(column - cell_len(self.glyphs.ellipsis))
                label.append(self.glyphs.ellipsis, role("muted"))
            label.pad_right(column - label.cell_len + 2)
            self.text(value_text, column + 2, label)

    def section(self, b: Section) -> None:
        links = self.out.links
        self.out.lines.append(Text(f"{b.title} ({b.count})", Style(bold=True)))
        for item in b.items:
            self.item(spans_text(item, links), b.marked)
        if b.more_text:
            self.item(Text(b.more_text, role("muted") + Style(italic=True)), b.marked)


def doc_lines(doc: Doc, width: int, glyphs: Glyphs, console: Console) -> DocLines:
    """`doc` laid out for `width` cells: its blocks with an empty line between them."""
    w = _Writer(width, glyphs, console)
    for i, block in enumerate(doc.blocks):
        if i:
            w.out.lines.append(Text())
        w.block(block)
    out = w.out
    out.link_lines = [0] * len(out.links)
    seen: set[int] = set()
    for n, line in enumerate(out.lines):
        for span in line.spans:
            number = link_of(span.style) if isinstance(span.style, Style) else None
            if number is not None and number not in seen:
                seen.add(number)
                out.link_lines[number] = n
    return out
