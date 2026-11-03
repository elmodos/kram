from kram.core.model import Origin, PkgRow, Status
from kram.core.search import Mode, SearchIndex, Term


def row(name, summary="", installed=False):
    status = Status.INSTALLED if installed else Status.NOT_INSTALLED
    return PkgRow(name, "x86_64", summary, "1-1" if installed else "", "1-1", "fedora", 1, Origin.FEDORA, status)


ROWS = [
    row("angelfish", "Web browser"),
    row("fishbowl", "Helper methods"),
    row("fish", "Friendly interactive shell"),
    row("fish-completion-extra", "Completions for fish"),
    row("autojump-fish", "Autojump for fish shell", installed=True),
    row("zsh", "Powerful interactive shell", installed=True),
    row("bash", "The GNU Bourne Again shell", installed=True),
    row("python3-requests", "HTTP library"),
    row("python3-requests-toolbelt", "Utilities for requests"),
]
DESCS = ["", "", "", "", "", "Zsh is a shell designed for interactive use.", "", "", ""]


def names(indices):
    return [ROWS[i].name for i in indices]


def test_exact_then_prefix_then_substring():
    idx = SearchIndex(ROWS)
    # installed beats length inside the substring tier
    assert names(idx.search("fish", Mode.NAME)) == [
        "fish", "fishbowl", "fish-completion-extra", "autojump-fish", "angelfish"]


def test_summary_tier_comes_after_name_matches():
    idx = SearchIndex(ROWS)
    res = names(idx.search("shell", Mode.NAME_SUMMARY))
    assert res[:2] == ["zsh", "bash"]  # installed first among summary matches, then shorter name
    assert set(res) == {"bash", "zsh", "fish", "autojump-fish"}
    assert idx.search("shell", Mode.NAME) == []


def test_words_are_anded():
    idx = SearchIndex(ROWS)
    assert names(idx.search("python3 toolbelt", Mode.NAME)) == ["python3-requests-toolbelt"]
    assert names(idx.search("interactive zsh", Mode.NAME_SUMMARY)) == ["zsh"]


def test_anchors_and_globs():
    idx = SearchIndex(ROWS)
    assert names(idx.search("^fish", Mode.NAME)) == ["fish", "fishbowl", "fish-completion-extra"]
    assert names(idx.search("fish$", Mode.NAME)) == ["fish", "autojump-fish", "angelfish"]
    assert names(idx.search("^fish$", Mode.NAME)) == ["fish"]
    assert names(idx.search("python3-*-toolbelt", Mode.NAME)) == ["python3-requests-toolbelt"]
    assert names(idx.search("^?sh$", Mode.NAME)) == ["zsh"]


def test_description_only_when_loaded_and_requested():
    assert SearchIndex(ROWS).search("designed", Mode.DESCRIPTION) == []
    idx = SearchIndex(ROWS, DESCS)
    assert names(idx.search("designed", Mode.DESCRIPTION)) == ["zsh"]
    assert idx.search("designed", Mode.NAME_SUMMARY) == []


def test_candidates_restrict_results():
    idx = SearchIndex(ROWS)
    installed = [i for i, r in enumerate(ROWS) if r.installed]
    assert names(idx.search("fish", Mode.NAME, installed)) == ["autojump-fish"]


def test_case_insensitive_and_special_chars():
    assert Term.parse("FISH").text == "fish"
    idx = SearchIndex([row("libstdc++"), row("c++-gtk-utils")])
    assert len(idx.search("c++", Mode.NAME)) == 2


def test_evr_order():
    from kram.core.evr import evr_ranks, split_evr
    assert split_evr("1:2.3-4.fc44") == ("1", "2.3", "4.fc44")
    assert split_evr("2.3-4") == ("0", "2.3", "4")
    ranks = evr_ranks(["10.0-1", "9.0-1", "1:1.0-1", "9.0-10", "9.0-2", ""])
    assert sorted(ranks, key=ranks.get) == ["9.0-1", "9.0-2", "9.0-10", "10.0-1", "1:1.0-1"]
