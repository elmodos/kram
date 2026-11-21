"""Qt's rendering of kram.app.doc: the HTML QTextBrowser and QLabel show. It is the HTML Kram wrote by hand before
the document model existed, byte for byte (tests/test_doc.py)."""
from html import escape
from urllib.parse import quote

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

_PARA_STYLE = {
    "": "<p>",
    "error": f"<p style='color:{ADVISORY_COLOR['important']}'>",
    "mono": "<p style='font-family:monospace; font-size:small; white-space:pre-wrap'>",
}


def _href(link: Link) -> str:
    if link.kind in ("pkg", "dep"):
        return f"{link.kind}:{quote(link.target)}"
    if link.kind == "web":
        return escape(link.target)
    return link.target


def spans_html(spans) -> str:
    out = []
    for s in spans:
        if isinstance(s, str):
            out.append(escape(s).replace("\xa0", "&nbsp;"))
        elif isinstance(s, Break):
            out.append("<br>")
        elif isinstance(s, Bold):
            out.append(f"<b>{spans_html(s.children)}</b>")
        elif isinstance(s, Italic):
            out.append(f"<i>{spans_html(s.children)}</i>")
        elif isinstance(s, Small):
            out.append(f"<small>{spans_html(s.children)}</small>")
        elif isinstance(s, Colored):
            out.append(f"<span style='color:{s.color}'>{spans_html(s.children)}</span>")
        elif isinstance(s, Link):
            out.append(f"<a href='{_href(s)}'>{spans_html(s.children)}</a>")
    return "".join(out)


def _block(b) -> str:
    if isinstance(b, Heading):
        return f"<h{b.level}>{spans_html(b.spans)}</h{b.level}>"
    if isinstance(b, Para):
        return f"{_PARA_STYLE[b.role]}{spans_html(b.spans)}</p>"
    if isinstance(b, Table):
        return "<table>" + "".join(f"<tr><td style='padding-right:16px'><b>{spans_html(label)}</b></td>"
                                   f"<td>{spans_html(value)}</td></tr>" for label, value in b.rows) + "</table>"
    if isinstance(b, Section) and b.marked:
        return f"<p style='margin:8px 0 2px 0'><b>{escape(b.title)} ({b.count})</b></p>" + "".join(
            f"<p style='margin:0 0 0 16px'>{spans_html(item)}</p>" for item in b.items)
    if isinstance(b, Section):
        items = "".join(f"<li>{spans_html(item)}</li>" for item in b.items)
        if b.more_text:
            items += f"<li><i>{escape(b.more_text)}</i></li>"
        return f"<b>{escape(b.title)} ({b.count})</b><ul style='margin-top:2px'>{items}</ul>"
    if isinstance(b, Bullets):
        return "<ul>" + "".join(f"<li>{spans_html(item)}</li>" for item in b.items) + "</ul>"
    if isinstance(b, Rule):
        return "<hr>"
    if isinstance(b, Inline):
        return spans_html(b.spans)
    raise TypeError(b)


def to_html(doc: Doc, compact: bool = False) -> str:
    """`compact`: paragraphs as lines with a blank line between them, for a label (the empty list)."""
    if compact:
        return "<br><br>".join(spans_html(b.spans) for b in doc.blocks)
    return "".join(_block(b) for b in doc.blocks)
