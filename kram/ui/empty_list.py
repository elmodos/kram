"""What the empty package list says instead: why it is empty and what would fill it, with links that do it.

The links are `href`s the window acts on: ALL (the same search in "All"), DESCRIPTIONS (search the descriptions),
RELOAD (download the metadata), REPOS (Settings → Repositories), RETRY (load the catalog again)."""
from dataclasses import dataclass
from html import escape

from ..i18n import _, ngettext

ALL, DESCRIPTIONS, RELOAD, REPOS, RETRY = "all", "descriptions", "reload", "repos", "retry"


@dataclass(frozen=True, slots=True)
class EmptyList:
    filter: str                 # the sidebar entry's label
    in_all: bool                # the entry lets every package in: there is nowhere wider to look
    text: str = ""              # the search, "" for none
    file_search: bool = False   # a File search: little is known about the files of packages not installed
    found_in_all: int = 0       # what the same search finds in "All"
    found_in_descriptions: int = 0  # what a description search finds under the same filter
    missing_repos: int = 0      # enabled repositories without metadata: their packages are not in the list
    hint: str = ""              # what fills the filter, for one that is empty until the user does something


def _link(href: str, text: str) -> str:
    return f"<a href='{href}'>{escape(text)}</a>"


def explain(e: EmptyList) -> str:
    """Rich text for the empty list."""
    filter_, text = escape(e.filter), escape(e.text)
    if not e.text:
        lines = [_("No packages in “{filter}”.").format(filter=filter_)]
        if e.hint:
            lines.append(escape(e.hint))
    elif e.in_all:
        lines = [_("Nothing found for “{text}”.").format(text=text)]
    else:
        lines = [_("Nothing found for “{text}” in “{filter}”.").format(text=text, filter=filter_)]
    if e.text and not e.in_all and e.found_in_all:
        n = e.found_in_all
        lines.append(_link(ALL, ngettext("Show {n} result in “{all}”", "Show {n} results in “{all}”", n).format(
            n=n, all=_("All"))))
    elif e.found_in_descriptions:
        n = e.found_in_descriptions
        lines.append(_link(DESCRIPTIONS, ngettext("Show {n} result found in descriptions",
                                                  "Show {n} results found in descriptions", n).format(n=n)))
    elif e.file_search:
        lines.append(escape(_("Of the packages that are not installed only some files are known: the programs in the "
                              "bin folders and the files in /etc.")))
    if e.missing_repos:
        n = e.missing_repos
        lines.append(escape(ngettext("{n} repository has no metadata, so its packages are missing from the list.",
                                     "{n} repositories have no metadata, so their packages are missing from the list.",
                                     n).format(n=n)))
        lines.append(f"{_link(RELOAD, _('Reload'))}&nbsp;&nbsp;·&nbsp;&nbsp;{_link(REPOS, _('Repositories'))}")
    return "<br><br>".join(lines)


def loading() -> str:
    return escape(_("Loading the package catalog…"))


def failed() -> str:
    return f"{escape(_('Could not load the package catalog.'))}<br><br>{_link(RETRY, _('Try again'))}"
