"""What the empty package list says instead: why it is empty and what would fill it, with links that do it.

The links are `action` links (kram.app.doc.Link) the window acts on: ALL (the same search in "All"), DESCRIPTIONS
(search the descriptions), RELOAD (download the metadata), REPOS (Settings → Repositories), RETRY (load the catalog
again). Each paragraph is a line of its own, with a blank line between them."""
from dataclasses import dataclass

from ..i18n import _, ngettext
from .doc import Doc, link, para

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


def explain(e: EmptyList) -> Doc:
    if not e.text:
        lines = [para(_("No packages in “{filter}”.").format(filter=e.filter))]
        if e.hint:
            lines.append(para(e.hint))
    elif e.in_all:
        lines = [para(_("Nothing found for “{text}”.").format(text=e.text))]
    else:
        lines = [para(_("Nothing found for “{text}” in “{filter}”.").format(text=e.text, filter=e.filter))]
    if e.text and not e.in_all and e.found_in_all:
        n = e.found_in_all
        lines.append(para(link("action", ALL, ngettext("Show {n} result in “{all}”", "Show {n} results in “{all}”",
                                                       n).format(n=n, all=_("All")))))
    elif e.found_in_descriptions:
        n = e.found_in_descriptions
        lines.append(para(link("action", DESCRIPTIONS, ngettext("Show {n} result found in descriptions",
                                                                "Show {n} results found in descriptions",
                                                                n).format(n=n))))
    elif e.file_search:
        lines.append(para(_("Of the packages that are not installed only some files are known: the programs in the "
                            "bin folders and the files in /etc.")))
    if e.missing_repos:
        n = e.missing_repos
        lines.append(para(ngettext("{n} repository has no metadata, so its packages are missing from the list.",
                                   "{n} repositories have no metadata, so their packages are missing from the list.",
                                   n).format(n=n)))
        lines.append(para(link("action", RELOAD, _("Reload")), "\xa0\xa0·\xa0\xa0",
                          link("action", REPOS, _("Repositories"))))
    return Doc(lines)


def loading() -> Doc:
    return Doc([para(_("Loading the package catalog…"))])


def failed() -> Doc:
    return Doc([para(_("Could not load the package catalog.")), para(link("action", RETRY, _("Try again")))])


def message(text: str) -> Doc:
    """Any other text in place of the list (a search that is still running)."""
    return Doc([para(text)])
