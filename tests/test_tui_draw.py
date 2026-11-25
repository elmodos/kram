"""The functions that draw the terminal front end, without an app (docs/TUI_SPEC.md §14.2, level 1): the list's
lines, the top line, hints, `palette.over`. Colours are a scheme's real roles (tests/tui_kit.py, `scheme`).
"""
import pytest

pytest.importorskip("textual")

from rich.style import Style  # noqa: E402
from rich.text import Text  # noqa: E402
from tui_kit import assert_snapshot, cells, grid, plain, scheme, styles_at  # noqa: E402, F401 - scheme: a fixture

from kram import __version__  # noqa: E402
from kram.app.columns import COL_NAME  # noqa: E402
from kram.app.package_list import PackageList  # noqa: E402
from kram.core.marks import Action, MarkSet  # noqa: E402
from kram.core.model import Origin, PkgRow, Status  # noqa: E402
from kram.tui.app import root_badge, top_line_text  # noqa: E402
from kram.tui.glyphs import ASCII, LETTERS, SYMBOLS, UNICODE  # noqa: E402
from kram.tui.package_list import Columns, header_segments, row_segments, visible_line  # noqa: E402
from kram.tui.palette import over, role  # noqa: E402
from kram.tui.widgets import hint  # noqa: E402

ALL_SCHEMES = ("textual-ansi", "kram-turbo", "kram-console", "textual-dark", "textual-light")


def row(name: str, status: Status, installed: str = "1.0-1", latest: str = "1.0-1") -> PkgRow:
    return PkgRow(name, "x86_64", f"The {name} package", installed, latest, "fedora", 2048, Origin.FEDORA, status)


ROWS = [row("bash", Status.INSTALLED), row("vim-enhanced", Status.UPGRADABLE, latest="2.0-1"),
        row("zsh", Status.NOT_INSTALLED, installed=""), row("htop", Status.INSTALLED), row("tree", Status.NOT_INSTALLED, installed="")]


def packages(marks: dict[str, Action] | None = None) -> PackageList:
    p = PackageList()
    p.set_rows(list(ROWS), "x86_64")
    p.marks = MarkSet()
    for r in ROWS:
        if marks and r.name in marks:
            p.marks.set(r, marks[r.name])
    return p


def list_lines(p: PackageList, width: int = 100, cursor: int | None = 0, focus: bool = True,
               selection: set[int] = frozenset(), ansi: bool = True, symbols=SYMBOLS, glyphs=UNICODE):
    columns = Columns().layout(width, 14)
    lines = [visible_line(*header_segments(columns, (COL_NAME, False), glyphs), width, 0, 0)]
    for pos in range(len(p)):
        state = None if pos != cursor else ("focus" if focus else "blur")
        segments, base = row_segments(p, pos, columns, state, pos in selection and len(selection) > 1, glyphs,
                                      symbols, ansi)
        lines.append(visible_line(segments, base, width, 0, 0))
    return lines


# ---------------------------------------------------------------- the package list (§7.3)

@pytest.mark.parametrize("scheme", ALL_SCHEMES, indirect=True)
def test_the_list_in_every_scheme(scheme):
    """The header, the cursor on the first row, an upgradable row and marks of every kind, as each scheme draws
    them: the snapshot shows every cell's role."""
    p = packages({"vim-enhanced": Action.UPGRADE, "zsh": Action.INSTALL, "htop": Action.REMOVE})
    assert_snapshot(f"list-{scheme.scheme}", grid(list_lines(p, ansi=scheme.ansi), scheme))


def test_the_list_header_names_the_columns_and_the_sort(scheme):
    header = plain(list_lines(packages())[0])
    assert header.split()[:3] == ["S", "Package", UNICODE.up]
    assert "Installed" in header and "Summary" in header


def test_the_cursor_and_the_blurred_cursor(scheme):
    focused, blurred = list_lines(packages())[1], list_lines(packages(), focus=False)[1]
    assert styles_at(focused, "bash") == {role("cursor")}
    assert styles_at(blurred, "bash") == {role("cursor-blurred")}
    assert styles_at(list_lines(packages())[4], "htop") == {Style()}


def test_turbo_cursor_is_black_on_green_and_glyphs_that_would_not_show_take_its_black(scheme):
    cursor = role("cursor")
    assert (cursor.bgcolor.number, cursor.color.number) == (2, 0) and not cursor.reverse
    installed = cells(list_lines(packages())[1])[1:3]  # the margin, then S: its glyph and its flag
    assert installed[0][0] == SYMBOLS.status[Status.INSTALLED] and installed[0][1].color.number == 0  # bright green on green: black
    assert over(cursor, Style(color="bright_white")).color.number == 15  # shows: kept
    assert over(Style(), role("installed")).color.number == 10  # off the cursor: its own colour


@pytest.mark.parametrize("scheme", ["kram-console"], indirect=True)
def test_a_16_colour_reverse_cursor_keeps_a_glyph_s_colour(scheme):
    glyph = cells(list_lines(packages())[1])[1][1]
    assert glyph.reverse and glyph.bgcolor == role("installed").color


@pytest.mark.parametrize("scheme", ["textual-dark"], indirect=True)
def test_marked_rows_are_tinted_in_high_colour(scheme):
    lines = list_lines(packages({"zsh": Action.INSTALL, "htop": Action.REMOVE}), cursor=None, ansi=False)
    assert role("tint-marked").bgcolor in {s.bgcolor for s in styles_at(lines[3], "zsh")}
    assert role("tint-danger").bgcolor in {s.bgcolor for s in styles_at(lines[4], "htop")}


def test_a_selection_marks_its_rows_in_the_margin(scheme):
    lines = list_lines(packages(), selection={1, 2})
    assert [cells(line)[0][0] for line in lines[1:]] == [" ", UNICODE.selected, UNICODE.selected, " ", " "]


def test_letters_and_ascii_where_the_terminal_is_not_utf8(scheme):
    line = list_lines(packages(), symbols=LETTERS, glyphs=ASCII)
    assert plain(line[1])[1] == LETTERS.status[Status.INSTALLED] and ASCII.up in plain(line[0])


def test_a_narrower_list_cuts_the_summary_with_an_ellipsis(scheme):
    p = PackageList()
    p.set_rows([PkgRow("bash", "x86_64", "The GNU Bourne Again shell, with every one of its many options", "1.0-1",
                       "1.0-1", "fedora", 2048, Origin.FEDORA, Status.INSTALLED)], "x86_64")
    wide, narrow = plain(list_lines(p, width=160)[1]), plain(list_lines(p, width=100)[1])
    assert "many options" in wide and "many options" not in narrow
    assert "The GNU Bourne" in narrow and narrow.rstrip().endswith(UNICODE.ellipsis) and len(narrow) == 100


def test_a_line_scrolls_sideways_with_frozen_cells_on_the_left(scheme):
    p = packages()
    segments, base = row_segments(p, 0, Columns().layout(100, 14), None, False, UNICODE, SYMBOLS, True)
    whole = plain(visible_line(segments, base, 100, 0, 0))
    scrolled = plain(visible_line(segments, base, 40, 10, 20))
    assert scrolled[:10] == whole[:10] and scrolled[10:] == whole[30:60]


# ---------------------------------------------------------------- the top line (§5.4)

def test_the_top_line_starts_with_the_version_and_the_status(scheme):
    line = top_line_text(Text("All  300"), [], False, 80)
    assert plain(line).startswith(f"Kram TUI v{__version__}  All  300")


def test_the_top_line_drops_from_the_right_what_does_not_fit(scheme):
    right = [Text("stale"), Text("3 days ago")]
    assert plain(top_line_text(Text("All"), right, False, 80)).rstrip().endswith("stale  3 days ago")
    assert plain(top_line_text(Text("All"), right, False, 35)).rstrip().endswith("stale")
    assert "stale" not in plain(top_line_text(Text("All"), right, False, 25))


def test_the_root_badge_goes_last_its_note_first(scheme):
    wide = plain(top_line_text(Text("All"), [], True, 80))
    assert "ROOT" in wide and "changes need no password" in wide
    narrow = plain(top_line_text(Text("All"), [], True, 30))
    assert "ROOT" in narrow and "password" not in narrow


def test_turbo_draws_the_top_line_s_text_black_and_red_on_its_grey(scheme):
    assert role("muted", bar=True).color.number == 0 and role("key", bar=True).color.number == 1
    badge = root_badge(False)[0]
    assert (badge.style.bgcolor.number, badge.style.color.number) == (1, 15)  # bright white on red


@pytest.mark.parametrize("scheme", ["kram-console"], indirect=True)
def test_other_schemes_draw_bars_as_the_rest(scheme):
    for name in ("muted", "key", "info", "danger", "marked", "badge"):
        assert role(name, bar=True) == role(name), name


# ---------------------------------------------------------------- hints (§6.8)

def test_a_hint_is_each_key_in_the_key_role_then_its_word(scheme):
    h = hint(("s", "sort"), ("y", "copy"))
    assert plain(h) == "s sort  y copy"
    assert styles_at(h, "s") == {role("key")} and styles_at(h, "sort") == {Style()}
    assert styles_at(hint(("q", "quit"), bar=True), "q") == {role("key", bar=True)}
