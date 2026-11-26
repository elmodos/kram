"""The terminal front end's details panel over a made-up catalog (docs/TUI_SPEC.md §7.4): the tab strip, every tab's
document, the remembered tab, the keys, the links, the Files and Versions tabs, the dimmed document while the next
one loads; and the list's cursor while another panel has the focus (§4.2).

Run with Textual's headless driver (`App.run_test`, `Pilot`), as tests/test_tui_window.py. Skipped without Textual.
"""
import asyncio

import pytest

pytest.importorskip("textual")

from rich.style import Style  # noqa: E402
from test_tui_window import rows  # noqa: E402
from test_tui_window import use_catalog as use_window_catalog  # noqa: E402

from kram.app.details import DETAILS_TAB_KEY  # noqa: E402
from kram.app.files import FILES_VIEW_KEY  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.core.model import Advisory, CatalogSnapshot, ChangelogEntry, PkgDetails, Status, VersionInfo  # noqa: E402
from kram.core.settings import store as settings  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.files import FileState, tree_rows  # noqa: E402
from kram.tui.glyphs import ASCII, UNICODE  # noqa: E402
from kram.tui.palette import role  # noqa: E402
from kram.tui.widgets import ChoiceList  # noqa: E402

WIDE, NARROW = (140, 36), (64, 22)
ADVISORY = Advisory("FEDORA-2026-1", "security", "important", "Fixes a hole", 1780000000, "The fix.",
                    (("cve", "CVE-2026-7", "https://cve.org/CVE-2026-7"),))
FILES = ["/usr/bin/{n}", "/usr/lib64/lib{n}.so.1", "/usr/share/doc/{n}/README", "/usr/share/doc/{n}/COPYING"]


def catalog_rows():
    found = rows(30)
    for i in (1, 4):  # upgradable, with an advisory
        r = found[i]
        r.status, r.installed_evr, r.candidate_evr, r.advisories = Status.UPGRADABLE, "0.9-1", "1.0-1", (ADVISORY,)
    return found


def fake_details(key: tuple[str, str]) -> PkgDetails:
    name, arch = key
    i = int(name[3:])
    installed = i % 3 == 0
    return PkgDetails(
        nevra=f"{name}-1.0-1.{arch}", summary=f"Summary {i}",
        description=f"Description of {name}, a line long enough to be wrapped where the panel is narrow."
                    f"\n\nSecond paragraph of {name}.",
        url=f"https://example.org/{name}", license="MIT", vendor="Fedora Project", packager="Fedora",
        source_rpm=f"{name}-1.0-1.src.rpm", build_time=1780000000, install_time=1780100000 if installed else None,
        repo_id="fedora", from_repo_id="fedora" if installed else "", install_size=1000 * i, download_size=500,
        user_installed=True if installed else None, requires=["libc.so.6()(64bit)", "pkg0002"], recommends=[],
        suggests=[], provides=[f"{name} = 1.0-1"], conflicts=[], obsoletes=[], required_by=[("pkg0005", "x86_64")],
        files=[f.format(n=name) for f in FILES], files_complete=installed,
        changelog=[ChangelogEntry(1780000000, f"Jane Doe <jane@example.org> - 1.0-1 of {name}", "- First build")],
        versions=[VersionInfo("1.0-1", "fedora", installed=installed, candidate=not installed),
                  VersionInfo("1.1-1", "updates-testing", locked_out=True)])


def use_catalog(monkeypatch, blocked=None, details=fake_details, reasons=None, threaded=False):
    """The window over a made-up catalog whose details are made up from the key, on a UTF-8 terminal (the tests
    check the box drawing; the ASCII set is tested on its own). The details' delay goes off on the test's clock,
    their job runs on the app's thread (test_tui_window.use_catalog), unless `threaded`."""
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    found = catalog_rows()
    snap = CatalogSnapshot(found, 10, 0, 0.1, descriptions=[""] * len(found))
    providers = {"pkg0002": ("pkg0002", "x86_64")}
    return use_window_catalog(monkeypatch, snap, blocked=blocked, clock=True, threaded=threaded, details=details,
                              find_provider=providers.get,
                              blocked_reason=lambda key: (reasons.append(key) if reasons is not None else None)
                              or "nothing provides libbar.so.2")


async def shown(app, pilot, key: tuple[str, str] = ("pkg0000", "x86_64")) -> None:
    """Until the details of `key` are shown, not the dimmed ones of a package the cursor was on before: the delay
    before they load goes off, their job's result comes in."""
    d = app.main.details
    clock = app.main.scheduler
    for _ in range(200):
        if d.shown_key == key and not d.stale:
            break
        if hasattr(clock, "fire"):
            clock.fire()
        await pilot.pause(0 if hasattr(clock, "fire") else 0.01)
    await pilot.pause()
    assert d.shown_key == key and not d.stale


def run(test, size=WIDE):
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await pilot.pause()
            await shown(app, pilot)
            await test(app, pilot)
    asyncio.run(go())
    return app


def details(app):
    return app.main.details


def strip(app) -> str:
    d = details(app)
    return d.strip_text(d.strip.size.width)[0].plain


def text(app) -> str:
    """The whole document of the shown tab, as laid out."""
    return "\n".join(line.plain for line in details(app).body.doc_lines().lines)


def body_lines(app) -> list[str]:
    body = details(app).body
    return [body.render_line(y).text for y in range(body.scrollable_content_region.height)]


async def focus_details(app, pilot) -> None:
    """`d`: the panel shown and focused."""
    if not app.has_focus_in("details"):
        app.action_toggle_panel("details")
    await pilot.pause()
    assert app.has_focus_in("details")


def tab(app, n: int) -> None:
    """A tab by its number, as `1`…`6` pick it."""
    details(app).action_tab_no(n)


def test_the_keys_of_the_panel():
    """The keys (§7.4): bound to the actions the tests call."""
    from kram.tui.details import Details, DetailsBody, FilterLine

    def keys(widget):
        return {key: b.action for b in widget.BINDINGS for key in b.key.split(",")}
    panel, body = keys(Details), keys(DetailsBody)
    assert panel["left_square_bracket"] == "tab(-1)" and panel["right_square_bracket"] == "tab(1)"
    assert [panel[str(i)] for i in range(1, 7)] == [f"tab_no({i})" for i in range(1, 7)]
    assert (panel["t"], panel["f"], panel["slash"], panel["y"], panel["o"]) == (
        "tabs", "files_mode", "filter", "copy", "show_file")
    assert (body["down"], body["up"], body["home"], body["end"]) == ("move(1)", "move(-1)", "jump(0)", "jump(-1)")
    assert (body["shift+down"], body["tab"], body["shift+tab"], body["enter"]) == (
        "extend(1)", "link(1)", "link(-1)", "follow")
    assert keys(FilterLine)["escape"] == "close"


# ---------------------------------------------------------------- the strip (§7.4.1)

@pytest.mark.feature(Feature.DETAILS_TABS, front="tui")
def test_the_strip_shows_every_tab_when_they_fit_and_the_current_one_when_not(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        assert strip(app) == " 1 Description │ 2 General │ 3 Dependencies │ 4 Files │ 5 Versions │ 6 Changelog "
        await focus_details(app, pilot)
        d = details(app)
        d.action_tab(1)  # ]
        assert d.tab == "general"
        current = [s for s in d.strip_text(200)[0].spans if s.style == role("current")]
        assert len(current) == 1
        await pilot.resize_terminal(*NARROW)  # the slide-over: the compact form
        await pilot.pause()
        assert strip(app) == "←  General  →  2/6"
        d.action_tab(-1)  # [
        assert strip(app) == "←  Description  →  1/6"
        d.action_tab(-1)  # round the end
        assert d.tab == "changelog"
    run(test)


@pytest.mark.feature(Feature.DETAILS_TABS, front="tui")
def test_keys_pick_tabs_and_t_lists_them(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        await focus_details(app, pilot)
        tab(app, 4)
        assert d.tab == "files"
        tab(app, 7)  # six tabs: no seventh
        assert d.tab == "files" and not d.check_action("tab_no", (7,)) and d.check_action("tab_no", (6,))
        d.action_tabs()  # t
        await pilot.pause()
        assert isinstance(app.screen, ChoiceList) and app.screen.current == "files"
        assert app.screen.labels == ["1  Description", "2  General", "3  Dependencies", "4  Files", "5  Versions",
                                     "6  Changelog"]
        app.screen.dismiss("versions")
        await pilot.pause()
        assert d.tab == "versions" and app.has_focus_in("details")
        assert "[ prev" in d.hints.plain and "t tabs" in d.hints.plain
    run(test)


# ---------------------------------------------------------------- the documents (§7.4.2)

@pytest.mark.feature(Feature.DETAILS_DESCRIPTION, front="tui")
@pytest.mark.feature(Feature.DETAILS_CHANGELOG, front="tui")
def test_each_tab_shows_its_document(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        lines = [line.plain for line in d.body.doc_lines().lines]
        assert lines[0] == "Summary 0" and lines[1] == ""
        assert lines[2].startswith("Description of pkg0000, a line long enough")
        heading = d.body.doc_lines().lines[0]
        assert any(isinstance(s.style, Style) and s.style.bold for s in heading.spans)
        await focus_details(app, pilot)
        tab(app, 2)
        general = text(app)
        assert "Package" in general and "pkg0000-1.0-1.x86_64" in general and "https://example.org/pkg0000" in general
        first = d.body.doc_lines().lines[0]
        assert first.spans[0].style == role("muted")  # the label
        tab(app, 3)
        deps = text(app)
        assert "Requires (2)" in deps and "• pkg0002" in deps and "Required by installed packages (1)" in deps
        tab(app, 6)
        assert "- First build" in text(app) and "Jane Doe" in text(app)
        tab(app, 5)
        versions = text(app).splitlines()
        assert versions[0].split() == ["Version", "Repository", "State"]
        assert versions[1].split() == ["1.0-1", "fedora", "installed"]
        assert "excluded by the version lock" in versions[2]
    run(test)


def test_long_text_wraps_and_the_panel_scrolls(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        body = d.body
        assert all(len(line) <= body.scrollable_content_region.width for line in body_lines(app))
        await focus_details(app, pilot)
        tab(app, 3)  # the dependencies: longer than the panel
        assert body.virtual_size.height > body.scrollable_content_region.height
        body.action_move(1)  # down
        assert body.scroll_offset.y == 1
        body.action_jump(-1)  # end
        assert body.scroll_offset.y == body.virtual_size.height - body.scrollable_content_region.height
        body.action_jump(0)  # home
        assert body.scroll_offset.y == 0
    run(test, NARROW)


@pytest.mark.feature(Feature.DETAILS_VERSIONS, front="tui")
def test_the_versions_table_has_the_installed_version_bold(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        d.choose("versions")
        await pilot.pause()
        lines = d.body.doc_lines().lines
        assert lines[0].style == role("header")
        assert lines[1].style.bold and "installed" in lines[1].plain
        assert lines[2].style.dim and not lines[2].style.bold
    run(test)


def test_the_old_document_stays_dimmed_while_the_next_one_loads(monkeypatch):
    catalog = use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        assert not any(s.style and s.style.dim for s in d.body.render_line(0))
        catalog.worker.hold()  # the next package's details are being looked up
        app.main.list.select(1)
        app.main.scheduler.fire()  # past the delay
        await pilot.pause()
        assert d.stale and "Summary 0" in d.body.render_line(0).text
        assert all(s.style.dim for s in d.body.render_line(0) if s.text.strip())
        catalog.worker.release()
        await shown(app, pilot, ("pkg0001", "x86_64"))
        assert not d.stale and "Summary 1" in d.body.render_line(0).text
        assert not any(s.style and s.style.dim for s in d.body.render_line(0))
    run(test)


# ---------------------------------------------------------------- advisories and the remembered tab

@pytest.mark.feature(Feature.DETAILS_ADVISORIES_TAB, front="tui")
def test_the_advisories_tab_comes_and_goes_and_comes_back(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        assert "Advisories" not in strip(app)
        app.main.select_key(("pkg0001", "x86_64"))
        await pilot.pause()
        assert strip(app).startswith(" 1 Description │ 2 General │ 3 Advisories │ 4 Dependencies")
        tabs = d.strip_text(200)[0]
        span = next(s for s in tabs.spans if "Advisories" in tabs.plain[s.start:s.end])
        assert span.style.color == role("upgradable").color
        await focus_details(app, pilot)
        tab(app, 3)
        assert d.tab == "advisories" and "FEDORA-2026-1" in text(app) and "CVE-2026-7" in text(app)
        app.main.select_key(("pkg0002", "x86_64"))  # none: the tab before stands in for it
        await pilot.pause()
        assert d.tab == "description" and "Advisories" not in strip(app)
        app.main.select_key(("pkg0004", "x86_64"))  # one again: TabChoice brings it back
        await pilot.pause()
        assert d.tab == "advisories"
        await pilot.resize_terminal(*NARROW)
        await pilot.pause()
        tab(app, 1)
        assert strip(app) == "←  Description  →  1/7  ! advisories"
    run(test)


@pytest.mark.feature(Feature.DETAILS_REMEMBER_TAB, front="tui")
def test_the_chosen_tab_is_saved_and_used_at_the_next_start(monkeypatch):
    use_catalog(monkeypatch)

    async def first(app, pilot):
        await focus_details(app, pilot)
        tab(app, 5)
        assert settings.get(DETAILS_TAB_KEY) == "versions"  # saved on change (§13.3)
    run(first)

    async def second(app, pilot):
        assert details(app).tab == "versions"
        app.main.select_key(("pkg0001", "x86_64"))
        await pilot.pause()
        await focus_details(app, pilot)
        tab(app, 3)
        assert settings.get(DETAILS_TAB_KEY) == "advisories"
    run(second)

    async def third(app, pilot):
        d = details(app)
        assert d.tab == "description"  # until a package has advisories, as in the GUIs
        app.main.select_key(("pkg0001", "x86_64"))
        await pilot.pause()
        assert d.tab == "advisories"
    run(third)


@pytest.mark.feature(Feature.DETAILS_BLOCKED_REASON, front="tui")
def test_a_blocked_upgrade_says_why_and_asks_the_resolver_once(monkeypatch):
    asked = []
    use_catalog(monkeypatch, blocked={("pkg0004", "x86_64"): ""}, reasons=asked)

    async def test(app, pilot):
        d = details(app)
        d.choose("dependencies")
        app.main.select_key(("pkg0004", "x86_64"))
        await shown(app, pilot, ("pkg0004", "x86_64"))
        for _ in range(100):
            if "libbar" in text(app):
                break
            await pilot.pause(0.01)
        doc = text(app)
        assert "nothing provides libbar.so.2" in doc and doc.index("libbar") < doc.index("Requires (2)")
        assert d.doc("dependencies").blocks[0].role == "error"
        app.main.select_key(("pkg0003", "x86_64"))
        await shown(app, pilot, ("pkg0003", "x86_64"))
        app.main.select_key(("pkg0004", "x86_64"))
        await shown(app, pilot, ("pkg0004", "x86_64"))
        assert asked == [("pkg0004", "x86_64")]  # kept, not asked again
    run(test)


# ---------------------------------------------------------------- links (§7.4.5)

@pytest.mark.feature(Feature.DETAILS_LINKS, front="tui")
def test_tab_moves_between_links_and_enter_follows_a_package(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        await focus_details(app, pilot)
        tab(app, 3)
        lines = d.body.doc_lines()
        assert [link.target for link in lines.links] == ["libc.so.6()(64bit)", "pkg0002", "pkg0005.x86_64",
                                                         "pkg0000 = 1.0-1"]
        assert "tab links" in d.hints.plain
        for _ in range(3):
            d.body.action_link(1)  # tab
        assert d.body.link == 2 and "enter open" in d.hints.plain
        focused = [s for s in d.body.render_line(lines.link_lines[2]) if s.style and s.style.reverse]
        assert "".join(s.text for s in focused) == "pkg0005.x86_64"
        d.body.action_follow()  # Enter
        await pilot.pause()
        assert app.main.current_key() == ("pkg0005", "x86_64") and app.has_focus_in("details")
        app.action_back()  # alt+left
        await shown(app, pilot)
        assert app.main.current_key() == ("pkg0000", "x86_64")
        d.body.action_link(1)
        d.body.action_link(1)  # a dependency: what provides it
        d.body.action_follow()
        for _ in range(100):
            if app.main.current_key() == ("pkg0002", "x86_64"):
                break
            await pilot.pause(0.01)
        assert app.main.current_key() == ("pkg0002", "x86_64")
    run(test)


def test_tab_past_the_last_link_goes_on_to_the_next_panel(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        await focus_details(app, pilot)
        await pilot.press("shift+tab")  # the description has no link: the focus moves on
        assert not app.has_focus_in("details")
        await focus_details(app, pilot)
        tab(app, 2)
        await pilot.press("tab")
        assert d.body.link == 0 and d.body.doc_lines().links[0].target == "https://example.org/pkg0000"
        await pilot.press("tab")
        assert d.body.link is None and not app.has_focus_in("details")
    run(test)


@pytest.mark.feature(Feature.DETAILS_LINKS, front="tui")
def test_a_web_link_without_a_desktop_is_copied(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        await focus_details(app, pilot)
        tab(app, 2)
        d.body.action_link(1)
        link = d.body.doc_lines().links[0]
        assert link.kind == "web"
        styled = [s for s in d.body.render_line(d.body.doc_lines().link_lines[0]) if s.style and s.style.link]
        assert styled and styled[0].style.link == "https://example.org/pkg0000"  # OSC 8
        d.body.action_follow()
        assert app.clipboard == "https://example.org/pkg0000"
        assert "the address is copied" in app.top_line.render().plain
    run(test)


# ---------------------------------------------------------------- the Files tab (§7.4.3)

def test_the_tree_has_box_drawing_branches_and_every_folder_open():
    from kram.core.file_tree import build_tree
    root = build_tree(["/usr/bin/tool", "/usr/share/doc/tool/README", "/etc/tool.conf"])
    assert [r.prefix + r.name for r in tree_rows(root, UNICODE)] == [
        "/", "├─ etc", "│  └─ tool.conf", "└─ usr", "   ├─ bin", "   │  └─ tool", "   └─ share", "      └─ doc",
        "         └─ tool", "            └─ README"]
    assert [r.prefix for r in tree_rows(root, ASCII)][1:6] == ["|- ", "|  \\- ", "\\- ", "   |- ", "   |  \\- "]


@pytest.mark.feature(Feature.DETAILS_FILES_TREE, front="tui")
@pytest.mark.feature(Feature.DETAILS_FILES_LIST, front="tui")
def test_f_switches_between_the_tree_and_the_list(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        await focus_details(app, pilot)
        tab(app, 4)
        lines = body_lines(app)
        assert lines[0].strip() == "4 files"
        assert [line.rstrip() for line in lines[1:5]] == [" /", " └─ usr/", "    ├─ bin/", "    │  └─ pkg0000"]
        d.action_files_mode()  # f
        lines = body_lines(app)
        assert [line.strip() for line in lines[1:5]] == [f.format(n="pkg0000") for f in FILES]
        assert settings.get(FILES_VIEW_KEY) == "list"
        assert "f tree" in d.hints.plain
        d.action_files_mode()
        assert d.files.tree and settings.get(FILES_VIEW_KEY) == "tree"
        app.main.select_key(("pkg0001", "x86_64"))  # not installed: the metadata list only some files
        await shown(app, pilot, ("pkg0001", "x86_64"))
        assert "Not installed" in body_lines(app)[0]
    run(test)


@pytest.mark.feature(Feature.DETAILS_FILES_FILTER, front="tui")
def test_the_filter_keeps_matching_files_with_the_match_bold(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        await focus_details(app, pilot)
        tab(app, 4)
        d.action_filter()  # /
        await pilot.pause()
        assert app.focused is d.filter and not d.filter.has_class("hidden")
        d.filter.value = "doc"
        await pilot.pause()
        # focused, it stays one line with no border: Input:focus's tall border once left no room for the text
        assert d.filter.size.height == 1 and "doc" in d.filter.render_line(0).text
        await d.filter.action_submit()  # Enter
        await pilot.pause()
        assert app.focused is d.body and not d.filter.has_class("hidden")
        lines = body_lines(app)
        assert lines[0].strip() == "2 of 4 files"
        assert "bin" not in "".join(lines)
        doc_line = 1 + [r.name for r in d.files.rows].index("doc")
        bold = [s.text for s in d.body.render_line(doc_line) if s.style and s.style.bold]
        assert "doc" in bold
        d.action_files_mode()  # a pattern, in the list
        d.action_filter()
        d.filter.value = "*.so*"
        await pilot.pause()
        await d.filter.action_submit()
        await pilot.pause()
        assert [line.strip() for line in body_lines(app)[:2]] == ["1 of 4 files", "/usr/lib64/libpkg0000.so.1"]
        d.action_filter()
        d.filter.action_close()  # Esc empties it
        await pilot.pause()
        assert d.filter.has_class("hidden") and body_lines(app)[0].strip() == "4 files"
    run(test)


@pytest.mark.feature(Feature.DETAILS_FILES_COPY_PATH, front="tui")
def test_y_copies_the_selected_paths(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        await focus_details(app, pilot)
        tab(app, 4)
        d.action_files_mode()
        d.body.action_move(1)
        d.action_copy()  # y
        assert app.clipboard == "/usr/lib64/libpkg0000.so.1"
        d.body.action_extend(1)  # shift+down
        d.body.action_extend(1)
        d.action_copy()
        assert app.clipboard == "/usr/lib64/libpkg0000.so.1\n/usr/share/doc/pkg0000/README\n" \
                                "/usr/share/doc/pkg0000/COPYING"
        assert "Copied" in app.top_line.render().plain
        assert body_lines(app)[3].startswith("▌")
    run(test)


def test_o_without_a_desktop_says_there_is_none(monkeypatch):
    monkeypatch.setattr("kram.tui.ui_port.has_desktop", lambda environ=None: False)
    use_catalog(monkeypatch)

    async def test(app, pilot):
        d = details(app)
        await focus_details(app, pilot)
        tab(app, 4)
        assert "o show" not in d.hints.plain
        d.action_show_file()  # o
        assert "No desktop to show it in" in app.top_line.render().plain
    run(test)


def test_o_with_a_desktop_shows_an_installed_file(monkeypatch, tmp_path):
    monkeypatch.setattr("kram.tui.ui_port.has_desktop", lambda environ=None: True)
    present = tmp_path / "tool"
    present.write_text("")
    shown_paths = []
    use_catalog(monkeypatch, details=lambda key: _with_files(fake_details(key), [str(present)]))

    async def test(app, pilot):
        d = details(app)
        monkeypatch.setattr(app.ui, "show_in_file_manager", shown_paths.append)
        await focus_details(app, pilot)
        tab(app, 4)
        d.action_files_mode()
        assert "o show" in d.hints.plain
        d.action_show_file()
        assert shown_paths == [str(present)]
    run(test)


def _with_files(d: PkgDetails, files: list[str]) -> PkgDetails:
    d.files = files
    return d


def test_the_file_state_keeps_its_filter_for_the_next_package():
    files = FileState(UNICODE)
    files.set_files(["/a/x.so", "/a/y"], True)
    files.set_filter("x")
    assert files.build() and files.shown == 1 and not files.build()
    files.set_files(["/b/x.txt", "/b/z"], True)
    files.build()
    assert files.filter_text == "x" and [r.name for r in files.rows] == ["/", "b", "x.txt"]


# ---------------------------------------------------------------- the panel in the window

def test_enter_focuses_the_details_and_the_slide_over_keeps_its_size(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        app.list_widget.action_details()  # Enter in the list
        await pilot.pause()
        assert app.has_focus_in("details") and app.focused is details(app).body
        assert app.panel("details").region.height == app.slide_height()
        assert app.main.list.bottom_inset == app.slide_height() - 1
        app.action_toggle_panel("details")  # d again while focused: hidden, the list has the focus
        await pilot.pause()
        assert "details" not in app.shown_panels() and app.focused is app.main.list
        assert app.main.list.bottom_inset == 0
    run(test, NARROW)


def test_the_list_cursor_is_blurred_in_high_colour_when_another_panel_has_the_focus(monkeypatch):
    use_catalog(monkeypatch)

    async def test(app, pilot):
        table = app.main.list
        for scheme in ("textual-dark", "textual-ansi"):
            app.set_scheme(scheme)
            await pilot.pause()
            await pilot.pause()
            app.main.list.focus()
            await pilot.pause()
            focused = list(table.render_line(1))[4].style  # the name's cell
            await focus_details(app, pilot)
            blurred = list(table.render_line(1))[4].style
            assert blurred.bgcolor != focused.bgcolor or blurred.reverse != focused.reverse, scheme
            assert blurred.bgcolor == role("cursor-blurred").bgcolor, scheme
            if scheme == "textual-dark":
                assert blurred.bgcolor != role("cursor").bgcolor
            else:
                assert blurred.underline and not blurred.reverse
    run(test)
