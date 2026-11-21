"""GTK's rendering of kram.app.doc: a column of Gtk.Labels with Pango markup, the counterpart of kram.qt.doc_html.

Links are <a href> in the markup, handled in the label's activate-link: every link goes to `on_link(kind, target)`,
as Qt's anchorClicked does. A Section (the Dependencies tab's "Requires (n)", up to 1000 items each) is a few
unwrapped labels of CHUNK lines, not a widget per item: one wrapping label of 1000 link lines took GTK 2 s to lay
out for kernel-core, these take ~60 ms (spike S6).
"""
from collections.abc import Callable
from urllib.parse import quote, unquote

from gi.repository import GLib, Gtk, Pango

from ..app.doc import (
    Bold,
    Break,
    Bullets,
    Colored,
    Doc,
    Heading,
    Inline,
    Italic,
    Link,
    Para,
    Rule,
    Section,
    Small,
    Table,
)
from ..app.icons import ADVISORY_COLOR

BULLET = "•"
CHUNK = 50  # lines per label in a section
_HEADING_SIZE = {1: "x-large", 2: "large", 3: "large", 4: "medium"}


def _href(link: Link) -> str:
    if link.kind in ("pkg", "dep"):
        return f"{link.kind}:{quote(link.target)}"
    if link.kind == "web":
        return link.target
    return f"action:{link.target}"


def spans_markup(spans) -> str:
    out = []
    for s in spans:
        if isinstance(s, str):
            out.append(GLib.markup_escape_text(s))
        elif isinstance(s, Break):
            out.append("\n")
        elif isinstance(s, Bold):
            out.append(f"<b>{spans_markup(s.children)}</b>")
        elif isinstance(s, Italic):
            out.append(f"<i>{spans_markup(s.children)}</i>")
        elif isinstance(s, Small):
            out.append(f"<small>{spans_markup(s.children)}</small>")
        elif isinstance(s, Colored):
            out.append(f"<span foreground='{GLib.markup_escape_text(s.color)}'>{spans_markup(s.children)}</span>")
        elif isinstance(s, Link):
            href = GLib.markup_escape_text(_href(s))
            out.append(f"<a href=\"{href}\">{spans_markup(s.children)}</a>")
    return "".join(out)


def parse_href(href: str) -> tuple[str, str]:
    """(kind, target) of a link this module wrote."""
    kind, sep, rest = href.partition(":")
    if sep and kind in ("pkg", "dep"):
        return kind, unquote(rest)
    if sep and kind == "action":
        return "action", rest
    return "web", href


class DocView(Gtk.Box):
    """Shows a Doc. `on_link(kind, target)` is called for every link clicked."""

    def __init__(self, margin: int = 12):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=margin, margin_end=margin,
                         margin_top=margin, margin_bottom=margin)
        self.on_link: Callable[[str, str], None] = lambda kind, target: None

    def set_doc(self, doc: Doc) -> None:
        while (child := self.get_first_child()) is not None:
            self.remove(child)
        for block in doc.blocks:
            for widget in self._block(block):
                self.append(widget)

    def _label(self, markup: str, css: str = "") -> Gtk.Label:
        label = Gtk.Label(xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, selectable=True,
                          use_markup=True)
        label.set_markup(markup)
        if css:
            label.add_css_class(css)
        label.connect("activate-link", self._activated)
        return label

    def _activated(self, _label: Gtk.Label, href: str) -> bool:
        self.on_link(*parse_href(href))
        return True  # handled: GTK would open it otherwise

    def _block(self, b) -> list[Gtk.Widget]:
        if isinstance(b, Heading):
            size = _HEADING_SIZE.get(b.level, "medium")
            return [self._label(f"<span size='{size}' weight='bold'>{spans_markup(b.spans)}</span>")]
        if isinstance(b, Para):
            if b.role == "error":
                return [self._label(f"<span foreground='{ADVISORY_COLOR['important']}'>"
                                    f"{spans_markup(b.spans)}</span>")]
            if b.role == "mono":
                return [self._label(f"<small><tt>{spans_markup(b.spans)}</tt></small>")]
            return [self._label(spans_markup(b.spans))]
        if isinstance(b, Inline):
            return [self._label(spans_markup(b.spans))]
        if isinstance(b, Table):
            grid = Gtk.Grid(column_spacing=16, row_spacing=2)
            for row, (label, value) in enumerate(b.rows):
                grid.attach(self._label(f"<b>{spans_markup(label)}</b>"), 0, row, 1, 1)
                v = self._label(spans_markup(value))
                v.set_hexpand(True)
                grid.attach(v, 1, row, 1, 1)
            return [grid]
        if isinstance(b, Section):
            title = self._label(f"<b>{GLib.markup_escape_text(b.title)} ({b.count})</b>")
            prefix = "" if b.marked else f"{BULLET} "
            lines = [prefix + spans_markup(item) for item in b.items]
            if b.more_text:
                lines.append(f"{prefix}<i>{GLib.markup_escape_text(b.more_text)}</i>")
            items = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_start=16)
            for start in range(0, len(lines), CHUNK):
                chunk = self._label("\n".join(lines[start:start + CHUNK]))
                chunk.set_wrap(False)
                items.append(chunk)
            return [title, items] if lines else [title]
        if isinstance(b, Bullets):
            return [self._label("\n".join(f"{BULLET} {spans_markup(item)}" for item in b.items))]
        if isinstance(b, Rule):
            return [Gtk.Separator()]
        raise TypeError(b)


def release_notes(releases) -> str:
    """kram.core.releases' notes, newest first, in the AppStream markup Adw.AboutDialog's What's New page takes."""
    out = []
    for r in releases:
        out.append(f"<p><em>{GLib.markup_escape_text(f'{r.version} — {r.date}')}</em></p>")
        out += [f"<p>{GLib.markup_escape_text(p)}</p>" for p in r.paragraphs]
        if r.items:
            out.append("<ul>" + "".join(f"<li>{GLib.markup_escape_text(i)}</li>" for i in r.items) + "</ul>")
    return "".join(out)
