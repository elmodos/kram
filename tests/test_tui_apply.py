"""The terminal front end's changes (docs/TUI_SPEC.md §7.5, §10.1, §10.16): marking from the list, the Apply changes
dialog (kram.tui.dialogs.apply) over a made-up preview, as tests/test_gtk.py tests the GTK one, and the flow from
the window: resolve, review, the transaction in the progress dialog, the reload; the conflicts offer and the form
when nothing can be done, which are Browser's questions.
"""
import asyncio
import dataclasses

import pytest

pytest.importorskip("textual")

from test_tui_progress import finish, helper, until  # noqa: E402, F401 - helper is a fixture
from test_tui_window import WIDE, loaded, rows, snapshot, use_catalog  # noqa: E402

from kram.app import preferences  # noqa: E402
from kram.app.actions import mark_upgrades_id  # noqa: E402
from kram.app.apply_review import ChangeSection  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.core.filters import UPGRADES_FIXES, UPGRADES_SECURITY, UPGRADES_SECURITY_HIGH  # noqa: E402
from kram.core.marks import Action  # noqa: E402
from kram.core.model import (  # noqa: E402
    Advisory,
    CatalogSnapshot,
    Origin,
    PkgRow,
    PreviewItem,
    Recommendation,
    Status,
    TransactionPreview,
)
from kram.core.settings import store as settings  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.dialogs.apply import ApplyDialog, ChangeList, Lines, RecBox, section_role  # noqa: E402
from kram.tui.dialogs.progress import AUTO_CLOSE_KEY, ProgressDialog  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402
from kram.tui.package_list import PackageTable  # noqa: E402
from kram.tui.widgets import Button, CheckBox, ChoiceList, PopupMenu  # noqa: E402

REQUEST = {"op": "transaction", "install": ["virt-manager"]}


def preview(with_kvm: bool = True, **kw) -> TransactionPreview:
    items = [PreviewItem("install", "virt-manager", "noarch", "5.1-1", "", "fedora", 700, 2000, "user"),
             PreviewItem("upgrade", "glib2", "x86_64", "2.84-2", "2.84-1", "updates", 3000, 8000, ""),
             PreviewItem("remove", "sudo", "x86_64", "1.9-1", "", "fedora", 0, 3000, "dependency")]
    if with_kvm:
        items.append(PreviewItem("install", "kvm", "x86_64", "1-1", "", "fedora", 50, 9000, "weak"))
    recs = [Recommendation("kvm", ["virt-manager"], True, ["kvm"] if with_kvm else [], ["kvm"], size=9000, count=1,
                           exact=True)]
    return TransactionPreview(items, [], 3750, 16000, recs, **kw)


def text(dialog: ApplyDialog, name: str) -> str:
    widget = dialog.query_one(f"#{name}", Lines)
    return widget.render().plain if widget.display else ""


def changes(dialog: ApplyDialog) -> str:
    return dialog.query_one(ChangeList).render().plain


def apply_button(dialog: ApplyDialog) -> Button:
    return dialog.query_one("#apply", Button)


def run_dialog(test, size=WIDE):
    """`test(app, pilot)` over an app without a catalog to load: the dialog alone."""
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await test(app, pilot)
    asyncio.run(go())


async def show(app, pilot, p: TransactionPreview, request: dict = REQUEST, resolve=None):
    results = []
    dialog = ApplyDialog(p, request, "x86_64", resolve)
    app.push_screen(dialog, results.append)
    await pilot.pause()
    await pilot.pause()
    return dialog, results


def run(monkeypatch, test, snap: CatalogSnapshot | None = None, loads: list | None = None, **catalog):
    """`test(app, pilot)` in the window over a made-up catalog; `catalog`: what else it answers (resolve, …)."""
    snap = snap or snapshot()

    def load(*_a, **_k):
        if loads is not None:
            loads.append(1)
        return snap
    catalog.setdefault("removal_dependents", lambda names: [])
    settings.set(AUTO_CLOSE_KEY, False)  # the progress dialog stays until Close
    use_catalog(monkeypatch, snap, load=load, **catalog)
    app = KramApp()

    async def go():
        async with app.run_test(size=WIDE) as pilot:
            await loaded(app, pilot)
            await test(app, pilot)
    asyncio.run(go())
    return app


async def wait_for(app, pilot, kind):
    await until(pilot, lambda: isinstance(app.screen, kind))
    return app.screen


# ---------------------------------------------------------------- the dialog (§10.1)

@pytest.mark.feature(Feature.DIALOG_APPLY, front="tui")
@pytest.mark.feature(Feature.DIALOG_APPLY_COMMAND, front="tui")
@pytest.mark.feature(Feature.DIALOG_APPLY_SKIPPED, front="tui")
def test_the_dialog_shows_every_part_of_the_review(tmp_path):
    copied = []

    async def test(app, pilot):
        app.copy_to_clipboard = copied.append
        p = preview(skipped=["nothing provides libfoo.so.3 needed by bar-1.0-1.x86_64"], to_download=3750,
                    cache_dir=str(tmp_path))
        dialog, results = await show(app, pilot, p)
        assert dialog.query_one("#apply-box").border_title == "Apply changes"
        summary = text(dialog, "summary")
        assert summary.startswith("3 to install/upgrade, 1 to remove.") and "To download: 3.7 kB" in summary
        assert "Disk space change: +15.6 kB" in summary and " free on /" in summary  # the free space
        assert "Essential system packages will be removed: sudo" in text(dialog, "warning")
        assert text(dialog, "skipped-title").startswith("⚠ Some marked changes cannot be carried out")
        assert "nothing provides libfoo.so.3" in text(dialog, "skipped")
        shown = changes(dialog)
        for line in ("To be installed (1)", "To be upgraded (1)", "To be removed as dependent or no longer needed (1)",
                     "To be installed as dependencies (1)"):
            assert line in shown
        row = next(line for line in shown.splitlines() if "glib2" in line)
        assert row.split() == ["glib2", "2.84-1", "→", "2.84-2", "updates", "2.9", "kB"]  # versions, repo, size
        sections = dialog.query_one(ChangeList).sections
        assert [section_role(s) for s in sections] == ["ok", "ok", "info", "danger"]
        assert section_role(ChangeSection("x", "#a86f1f", ())) == "muted"  # a downgrade: the others are muted
        boxes = list(dialog.query(RecBox))
        assert [b.row.label for b in boxes] == ["kvm"] and boxes[0].value
        assert "virt-manager" in boxes[0].label and "+8.8 kB, 1 package" in boxes[0].label
        assert "Recommended packages." in text(dialog, "recs-note")
        assert text(dialog, "command") == "sudo dnf5 install virt-manager"
        assert not dialog.query_one("#download-only", CheckBox).value
        assert apply_button(dialog).enabled and apply_button(dialog).has_focus
        await pilot.press("y")
        assert copied == ["sudo dnf5 install virt-manager"]
        await pilot.press("escape")
        await pilot.pause()
        assert results == [None] and len(app.screen_stack) == 1
    run_dialog(test)


def test_a_narrow_dialog_drops_columns_not_words():
    async def test(app, pilot):
        dialog, _results = await show(app, pilot, preview())
        rows_ = changes(dialog).splitlines()
        assert all(len(line) <= dialog.query_one(ChangeList).size.width for line in rows_)
        row = next(line for line in rows_ if "glib2" in line)
        assert row.split() == ["glib2", "2.84-2", "2.9", "kB"]  # the version it ends up at, no repository
        box = dialog.query_one("#apply-box")
        buttons = dialog.query_one(".buttons")
        assert buttons.region.bottom <= box.region.bottom - 1  # the buttons stay in the frame
    run_dialog(test, size=(64, 22))


@pytest.mark.feature(Feature.DIALOG_APPLY_RECOMMENDATIONS, front="tui")
@pytest.mark.feature(Feature.DIALOG_APPLY_DOWNLOAD_ONLY, front="tui")
def test_unticking_a_recommendation_resolves_again_and_download_only_reaches_the_request():
    async def test(app, pilot):
        waiting = []
        dialog, results = await show(app, pilot, preview(), resolve=lambda req, done, failed: waiting.append(
            (req, done)))
        box = dialog.query_one(RecBox)
        box.focus()
        await pilot.press("space")
        assert waiting and waiting[-1][0]["exclude_weak"] == ["kvm"]
        assert text(dialog, "summary") == "Resolving dependencies…" and not apply_button(dialog).enabled
        await pilot.press("space")  # off while it resolves
        assert not box.value and len(waiting) == 1
        await pilot.press("ctrl+a")  # Apply is off meanwhile
        assert app.screen is dialog
        waiting[-1][1](preview(with_kvm=False))
        await pilot.pause()
        assert apply_button(dialog).enabled and "kvm" not in changes(dialog)
        assert text(dialog, "summary").startswith("2 to install/upgrade")
        assert dialog.query_one(RecBox) is box and box.has_focus and not box.value  # in place, the focus kept
        assert text(dialog, "command") == "sudo dnf5 install --setopt=exclude_from_weak=kvm virt-manager"
        dialog.query_one("#download-only", CheckBox).focus()
        await pilot.press("space")
        assert "--downloadonly" in text(dialog, "command")
        await pilot.press("ctrl+a")
        await until(pilot, lambda: results)
        assert results == [{"op": "transaction", "install": ["virt-manager"], "exclude_weak": ["kvm"],
                            "download_only": True}]
    run_dialog(test)


def test_a_failed_resolve_says_why_on_the_summary_line():
    async def test(app, pilot):
        waiting = []
        dialog, _results = await show(app, pilot, preview(), resolve=lambda req, done, failed: waiting.append(
            failed))
        dialog.query_one(RecBox).focus()
        await pilot.press("space")
        waiting[-1](RuntimeError("no network"))
        await pilot.pause()
        assert text(dialog, "summary") == "Could not resolve the changes:\n\nno network"
        assert not apply_button(dialog).enabled and dialog.query_one(RecBox).enabled
    run_dialog(test)


@pytest.mark.feature(Feature.DIALOG_APPLY_FREE_SPACE, front="tui")
def test_apply_is_off_when_the_disk_cannot_hold_it_and_on_for_a_download_that_fits(tmp_path):
    async def test(app, pilot):
        dialog, results = await show(app, pilot, preview(to_download=1 << 60, cache_dir=str(tmp_path)))
        assert not apply_button(dialog).enabled and dialog.query_one("#cancel", Button).has_focus
        assert text(dialog, "space").startswith("⚠ Not enough disk space on /")
        await pilot.press("ctrl+a")
        await pilot.pause()
        assert app.screen is dialog and not results
        await pilot.press("escape")
        await pilot.pause()
        # the installation does not fit, the download does: Download only turns Apply on
        p = dataclasses.replace(preview(to_download=100, cache_dir=str(tmp_path)), size_change=1 << 60)
        dialog, results = await show(app, pilot, p)
        assert not apply_button(dialog).enabled
        assert "The download alone fits" in text(dialog, "space")
        dialog.query_one("#download-only", CheckBox).focus()
        await pilot.press("space")
        assert apply_button(dialog).enabled and not text(dialog, "space")
        await pilot.press("ctrl+a")
        await until(pilot, lambda: results)
        assert results[0]["download_only"] is True
    run_dialog(test)


# ---------------------------------------------------------------- from the window

@pytest.mark.feature(Feature.MARK_APPLY_BUTTON, front="tui")
@pytest.mark.feature(Feature.MARK_INSTALL_REMOVE, front="tui")
def test_apply_runs_the_transaction_with_its_progress_then_reloads(monkeypatch, helper):  # noqa: F811
    loads, resolved = [], []

    def resolve(request, sizes=True):
        resolved.append(request)
        return preview()

    async def test(app, pilot):
        b = app.main.browser
        app.main.list.select(1)  # pkg0001 is not installed
        await pilot.pause()
        await pilot.press("plus")
        assert b.packages.marks.get(("pkg0001", "x86_64")).action is Action.INSTALL
        before = len(loads)
        await pilot.press("a")
        dialog = await wait_for(app, pilot, ApplyDialog)
        assert resolved == [{"op": "transaction", "install": ["pkg0001.x86_64"]}]
        await pilot.press("ctrl+a")
        progress = await finish(app, pilot)
        assert isinstance(progress, ProgressDialog) and progress.title_text == "Applying changes"
        assert progress.request == dialog.review.result()
        assert helper() == ["transaction"]
        await until(pilot, lambda: len(loads) > before and app.main.reload_enabled)
        assert not len(b.packages.marks)
        b.helper.stop()
    run(monkeypatch, test, loads=loads, resolve=resolve)


def test_cancel_runs_nothing(monkeypatch, helper):  # noqa: F811
    async def test(app, pilot):
        b = app.main.browser
        app.main.list.select(1)
        await pilot.press("plus", "a")
        await wait_for(app, pilot, ApplyDialog)
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert len(app.screen_stack) == 1 and helper() == [] and len(b.packages.marks) == 1
        assert not b.busy()
    run(monkeypatch, test, resolve=lambda request, sizes=True: preview())


def front_end_snapshot() -> CatalogSnapshot:
    found = rows(3) + [PkgRow("kram-tui", "noarch", "Kram in a terminal", "0.13-1", "0.13-1", "kram", 1000,
                              Origin.COPR, Status.INSTALLED)]
    return CatalogSnapshot(found, 2, 0, 0.1)


def test_a_transaction_that_removes_kram_tui_closes_kram(monkeypatch, helper):  # noqa: F811
    exited = []

    async def test(app, pilot):
        app.exit = lambda *a, **k: exited.append(1)
        app.main.select_key(("kram-tui", "noarch"))
        await pilot.press("minus", "a")
        await wait_for(app, pilot, ApplyDialog)
        await pilot.press("ctrl+a")
        await until(pilot, lambda: isinstance(app.screen, ProgressDialog) and app.screen.finished)
        await pilot.press("enter")  # Close: the question comes after it
        question = await wait_for(app, pilot, QuestionDialog)
        assert "They removed the front end of Kram you are using (kram-tui)" in question.question.text
        await pilot.press("enter")
        await until(pilot, lambda: exited)
    run(monkeypatch, test, front_end_snapshot(), resolve=lambda request, sizes=True: preview())


@pytest.mark.feature(Feature.DIALOG_APPLY_CONFLICTS, front="tui")
def test_conflicting_packages_are_offered_for_removal_then_reviewed(monkeypatch):
    def resolve(request, sizes=True):
        ok = "remove" in request
        return preview() if ok else TransactionPreview([], ["conflicts with installed kram-tui"], 0, 0)

    async def test(app, pilot):
        b = app.main.browser
        app.main.select_key(("pkg0001", "x86_64"))
        await pilot.press("plus", "a")
        question = await wait_for(app, pilot, QuestionDialog)
        q = question.question
        assert q.title == "Conflicting packages" and "1 installed package conflicts" in q.text
        assert "This removes the front end of Kram you are using (kram-tui)" in q.informative  # §10.16
        await pilot.press("enter")  # Mark for Removal is the default
        await wait_for(app, pilot, ApplyDialog)
        assert b.packages.marks.get(("kram-tui", "noarch")).action is Action.REMOVE
    run(monkeypatch, test, front_end_snapshot(), resolve=resolve,
        conflict_removals=lambda request: [("kram-tui", "noarch")])


@pytest.mark.feature(Feature.DIALOG_APPLY_CANNOT_APPLY, front="tui")
def test_when_nothing_can_be_done_the_form_offers_what_can(monkeypatch):
    locked = TransactionPreview([], ["package pkg0001 is filtered out by the version lock"], 0, 0, versionlock=True)

    def resolve(request, sizes=True):
        if request.get("revert"):
            return preview() if request.get("skip_unavailable") else TransactionPreview([], ["gone"], 0, 0)
        return locked

    async def test(app, pilot):
        b = app.main.browser
        app.main.list.select(1)
        await pilot.press("plus", "a")
        question = await wait_for(app, pilot, QuestionDialog)
        assert question.question.title == "Cannot apply changes"
        show_locked = next(w for w in question.query(Button) if w.label == "Show Locked Packages")
        show_locked.focus()
        await pilot.press("enter")
        await until(pilot, lambda: b.filter is not None and b.filter.id == "status:locked")
        # an undo that cannot be done whole: Undo What Is Possible reviews the rest
        b._review({"op": "transaction", "revert": [7]}, marked=False)
        question = await wait_for(app, pilot, QuestionDialog)
        undo = next(w for w in question.query(Button) if w.label == "Undo What Is Possible…")
        undo.focus()
        await pilot.press("enter")
        dialog = await wait_for(app, pilot, ApplyDialog)
        assert dialog.review.request == {"op": "transaction", "revert": [7], "skip_unavailable": True}
    run(monkeypatch, test, resolve=resolve, conflict_removals=lambda request: [])


# ---------------------------------------------------------------- marking (§7.5)

def marking_snapshot() -> CatalogSnapshot:
    security = Advisory("FEDORA-2026-1", "security", "important", "Fix", 0)
    enhancement = Advisory("FEDORA-2026-2", "enhancement", "", "New", 0)
    found = rows(6) + [
        PkgRow("sec", "x86_64", "S", "1-1", "2-1", "updates", 10, Origin.FEDORA, Status.UPGRADABLE,
               advisories=(security,)),
        PkgRow("enh", "x86_64", "E", "1-1", "2-1", "updates", 10, Origin.FEDORA, Status.UPGRADABLE,
               advisories=(enhancement,)),
        PkgRow("plain", "x86_64", "P", "1-1", "2-1", "updates", 10, Origin.FEDORA, Status.UPGRADABLE),
        PkgRow("leftover", "x86_64", "L", "1-1", "1-1", "fedora", 10, Origin.FEDORA, Status.UNNEEDED),
    ]
    return CatalogSnapshot(found, 6, 3, 0.1)


def mark_of(app, name: str) -> Action | None:
    mark = app.main.browser.packages.marks.get((name, "x86_64"))
    return mark.action if mark else None


@pytest.mark.feature(Feature.LIST_STATUS_CLICK, front="tui")
@pytest.mark.feature(Feature.SETTINGS_STATUS_CLICK, front="tui")
def test_space_and_a_click_on_the_status_cell_follow_the_setting(monkeypatch):
    async def test(app, pilot):
        main = app.main
        preferences.set_value(preferences.STATUS_CLICK, True)
        main.select_key(("pkg0001", "x86_64"))  # not installed
        await pilot.press("space")
        assert mark_of(app, "pkg0001") is Action.INSTALL
        await pilot.press("space")  # marked: unmarked
        assert mark_of(app, "pkg0001") is None
        main.select_key(("pkg0000", "x86_64"))  # installed, no upgrade: no likely mark, so the menu
        await pilot.press("space")
        menu = await wait_for(app, pilot, PopupMenu)
        assert menu.title_text == "pkg0000" and not any("Copy" in item[0] for item in menu.items if item)
        await pilot.press("escape")
        await pilot.pause()
        # a click on the status cell of a row (x 1: after the margin; y: the header is line 0)
        table = app.query_one(PackageTable)
        y = 1 + table.packages.position_of(("pkg0004", "x86_64")) - table.scroll_offset.y
        await pilot.click(PackageTable, offset=(1, y))
        await pilot.pause()
        assert mark_of(app, "pkg0004") is Action.INSTALL and main.current_key() == ("pkg0004", "x86_64")
        # the setting off: the status menu, as in the GUIs
        preferences.set_value(preferences.STATUS_CLICK, False)
        await pilot.press("space")
        menu = await wait_for(app, pilot, PopupMenu)
        assert "Mark for Installation" in [item[0] for item in menu.items if item]
        await pilot.press("escape")
        await pilot.pause()
        await pilot.click(PackageTable, offset=(1, y))
        await wait_for(app, pilot, PopupMenu)
        await pilot.press("escape")
        await pilot.pause()
        assert mark_of(app, "pkg0004") is Action.INSTALL
        preferences.set_value(preferences.STATUS_CLICK, False)
    run(monkeypatch, test)


@pytest.mark.feature(Feature.LIST_DOUBLE_CLICK_MARK, front="tui")
def test_a_double_click_on_a_row_is_the_likely_mark(monkeypatch):
    async def test(app, pilot):
        table = app.query_one(PackageTable)
        y = 1 + table.packages.position_of(("pkg0002", "x86_64")) - table.scroll_offset.y
        await pilot.click(PackageTable, offset=(10, y), times=2)
        await pilot.pause()
        assert mark_of(app, "pkg0002") is Action.INSTALL and len(app.screen_stack) == 1
        await pilot.click(PackageTable, offset=(10, y), times=2)
        await pilot.pause()
        assert mark_of(app, "pkg0002") is None
    run(monkeypatch, test)


@pytest.mark.feature(Feature.MARK_UNMARK_ONE, front="tui")
@pytest.mark.feature(Feature.MARK_UNMARK_ALL, front="tui")
def test_the_marking_keys_and_the_marks_on_the_top_line(monkeypatch):
    async def test(app, pilot):
        main, b = app.main, app.main.browser
        main.select_key(("pkg0001", "x86_64"))
        await pilot.press("plus")
        main.select_key(("pkg0002", "x86_64"))
        await pilot.press("insert")
        main.select_key(("pkg0003", "x86_64"))  # installed
        await pilot.press("minus")
        assert [mark_of(app, n) for n in ("pkg0001", "pkg0002", "pkg0003")] == [Action.INSTALL, Action.INSTALL,
                                                                               Action.REMOVE]
        assert "3 changes marked" in app.top_line.render().plain
        b.sidebar.select("status", "status:marked")  # the Marked entry lists them
        await pilot.pause()
        assert [b.packages.row(i).name for i in range(len(b.packages))] == ["pkg0001", "pkg0002", "pkg0003"]
        main.select_key(("pkg0002", "x86_64"))
        await pilot.press("z")
        assert mark_of(app, "pkg0002") is None and "2 changes marked" in app.top_line.render().plain
        assert len(b.packages) == 3  # "Marked" keeps the unmarked row
        await pilot.press("Z")
        assert not len(b.packages.marks) and "changes marked" not in app.top_line.render().plain
    run(monkeypatch, test)


def test_removing_a_package_asks_about_what_depends_on_it(monkeypatch):
    """Marker's question (§7.5.1) through the Ui port: a §10.21 question dialog."""
    async def test(app, pilot):
        app.main.select_key(("pkg0003", "x86_64"))
        await pilot.press("minus")
        question = await wait_for(app, pilot, QuestionDialog)
        assert "1 installed package depends on the packages marked for removal" in question.question.text
        await pilot.press("enter")  # Mark
        await until(pilot, lambda: mark_of(app, "pkg0006") is Action.REMOVE)
        assert mark_of(app, "pkg0003") is Action.REMOVE
    run(monkeypatch, test, removal_dependents=lambda names: [("pkg0006", "x86_64")] if names else [])


@pytest.mark.feature(Feature.MARK_UPGRADE_ALL, front="tui")
@pytest.mark.feature(Feature.MARK_UPGRADE_BY_ADVISORY, front="tui")
@pytest.mark.feature(Feature.MARK_UNNEEDED, front="tui")
def test_u_lists_the_advisory_kinds_and_marks_the_one_chosen(monkeypatch):
    async def test(app, pilot):
        await pilot.press("U")
        choice = await wait_for(app, pilot, ChoiceList)
        assert choice.title_text == "Mark Upgrades"
        assert choice.values == ["mark_upgrades", mark_upgrades_id(UPGRADES_SECURITY),
                                 mark_upgrades_id(UPGRADES_SECURITY_HIGH), mark_upgrades_id(UPGRADES_FIXES)]
        assert choice.labels[0] == "Mark All Upgrades"
        await pilot.press("down", "enter")  # Mark Security Upgrades
        await until(pilot, lambda: mark_of(app, "sec") is not None)
        assert [mark_of(app, n) for n in ("sec", "enh", "plain")] == [Action.UPGRADE, None, None]
        await pilot.press("ctrl+u")
        await wait_for(app, pilot, ChoiceList)
        await pilot.press("enter")  # Mark All Upgrades
        await until(pilot, lambda: mark_of(app, "plain") is not None)
        assert [mark_of(app, n) for n in ("sec", "enh", "plain")] == [Action.UPGRADE] * 3
        app.main.run_action("mark_unneeded")  # Edit → Mark Unneeded Dependencies for Removal
        assert mark_of(app, "leftover") is Action.REMOVE
    run(monkeypatch, test, marking_snapshot())


def test_u_without_advisories_marks_every_upgrade_at_once(monkeypatch):
    plain = [PkgRow("plain", "x86_64", "P", "1-1", "2-1", "updates", 10, Origin.FEDORA, Status.UPGRADABLE)]

    async def test(app, pilot):
        await pilot.press("U")
        await pilot.pause()
        assert len(app.screen_stack) == 1 and mark_of(app, "plain") is Action.UPGRADE
    run(monkeypatch, test, CatalogSnapshot(rows(3) + plain, 1, 1, 0.1))


def test_the_footer_shows_reload_and_apply_and_mark_upgrades_while_they_are_on(monkeypatch):
    """The footer has f5 Reload always, U Mark All Upgrades while a package has an upgrade, a Apply while something
    is marked; Menu, Keys and Quit stand on its right (§5.5)."""
    from kram.tui.widgets import KeyFooter
    plain = [PkgRow("plain", "x86_64", "P", "1-1", "2-1", "updates", 10, Origin.FEDORA, Status.UPGRADABLE)]

    async def test(app, pilot):
        footer = app.query_one(KeyFooter)
        line = footer.render().plain
        assert "f5 Reload" in line and "U Mark All Upgrades" in line and "a Apply" not in line
        assert line.rstrip().endswith("m Menu  ? Keys  q Quit")
        assert len(line) == footer.content_region.width
        await pilot.press("U")
        await until(pilot, lambda: "a Apply" in footer.render().plain)
        line = footer.render().plain
        assert line.index("U Mark All Upgrades") < line.index("a Apply") < line.index("m Menu")
    run(monkeypatch, test, CatalogSnapshot(rows(3) + plain, 1, 1, 0.1))
