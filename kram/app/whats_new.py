"""Help → About → What's New: the release notes, newest first, as a document."""
from .. import __version__
from ..core.releases import Release
from ..i18n import _
from .doc import Bullets, Doc, Heading, Inline, italic, para


def whats_new_doc(releases: list[Release], current: str = __version__) -> Doc:
    blocks = []
    for r in releases:
        mark = (" ", italic(f"({_('this version')})")) if r.version == current else ()
        blocks.append(Heading((f"{r.version} — {r.date}", *mark)))
        blocks += [para(p) for p in r.paragraphs]
        if r.items:
            blocks.append(Bullets(tuple((i,) for i in r.items)))
    return Doc(blocks or [Inline((italic(_("The list of changes is not available.")),))])
