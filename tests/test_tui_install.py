"""The terminal front end's Install package file dialog (docs/TUI_SPEC.md §10.8, kram.tui.dialogs.install) over the
fakes of tests/test_install_flow.py, as tests/test_gtk.py tests the GTK one: what the file does, its
recommendations, the command line, the check before a reinstall, installing through the fake helper; opening it from
File → Open Package File…, from a pasted path, and alone (`kram-tui FILE.rpm`, kram.tui.installer).
"""
import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from test_install_flow import Catalog, Sync, make_rpm  # noqa: E402
from test_tui_progress import finish, helper, until  # noqa: E402, F401 - helper is a fixture
from test_tui_window import WIDE, loaded, use_catalog  # noqa: E402
from textual import events  # noqa: E402

from kram.app import install  # noqa: E402
from kram.app.parity import Feature  # noqa: E402
from kram.core import local_rpm  # noqa: E402
from kram.core.local_rpm import VerifyResult  # noqa: E402
from kram.core.model import LocalTarget, PreviewItem, Recommendation, Requirement, TransactionPreview  # noqa: E402
from kram.core.settings import store as settings  # noqa: E402
from kram.tui import __main__ as tui_main  # noqa: E402
from kram.tui import installer  # noqa: E402
from kram.tui.app import KramApp  # noqa: E402
from kram.tui.dialogs.apply import ChangeList, Lines, RecBox  # noqa: E402
from kram.tui.dialogs.install import InstallDialog, note_text, split_files  # noqa: E402
from kram.tui.dialogs.path import PathDialog  # noqa: E402
from kram.tui.dialogs.progress import AUTO_CLOSE_KEY, ProgressDialog  # noqa: E402
from kram.tui.dialogs.question import QuestionDialog  # noqa: E402
from kram.tui.glyphs import UNICODE  # noqa: E402
from kram.tui.widgets import Button  # noqa: E402
from kram.tui.window import INSTALL_DIR_KEY, pasted_rpm  # noqa: E402


class RecCatalog(Catalog):
    """A file that recommends a package; unticking it resolves again without it."""

    def __init__(self, action="install"):
        super().__init__(action)
        self.excluded = []

    def resolve_local(self, path, action, exclude, sizes=True):
        self.excluded.append(list(exclude))
        items = [PreviewItem(action, "tool", "x86_64", "2.0-1", "", "@commandline", 1000, 5000, "user")]
        recs = [Recommendation("tool-extras", ["tool"], "tool-extras" not in exclude,
                               [] if exclude else ["tool-extras"], ["tool-extras"], size=300, count=1, exact=True)]
        if not exclude:
            items.append(PreviewItem("install", "tool-extras", "noarch", "1-1", "", "fedora", 100, 300, "weak"))
        return TransactionPreview(items, [], 100, 5300, recs)

    def open_local(self, path):
        return LocalTarget(self.action, "", "", "", {"requires": [Requirement("bash", ["bash"], ["bash"])],
                                                     "recommends": [], "suggests": []})


@pytest.fixture
def rpm(tmp_path, monkeypatch):
    """A package file on disk (a paste must name one), read as the fake of test_install_flow."""
    path = tmp_path / "tool-2.0-1.x86_64.rpm"
    path.write_bytes(b"rpm")
    found = make_rpm(path=str(path))
    monkeypatch.setattr(local_rpm, "read", lambda _path: found)
    monkeypatch.setattr(install, "DnfWorker", lambda post, name: Sync())  # the file reader, at once
    settings.set(AUTO_CLOSE_KEY, False)
    return found


def run_alone(monkeypatch, test, size=WIDE):
    """`test(app, pilot)` over the window with a made-up catalog, loaded: the dialog is pushed by the test."""
    use_catalog(monkeypatch)
    app = KramApp()

    async def go():
        async with app.run_test(size=size) as pilot:
            await loaded(app, pilot)
            await test(app, pilot)
    asyncio.run(go())


async def show(app, pilot, path: str, catalog, run=None, marks: int = 0) -> tuple[InstallDialog, list]:
    results = []
    dialog = InstallDialog(path, catalog, Sync(), busy=lambda: False, run=run or (lambda *a: None), marks=marks)
    app.push_screen(dialog, results.append)
    await until(pilot, lambda: dialog.is_mounted and bool(dialog.query("#install")))
    await pilot.pause()
    return dialog, results


def text(dialog, name: str) -> str:
    widget = dialog.query_one(f"#{name}", Lines)
    return widget.render().plain if widget.display else ""


def run_window(monkeypatch, test, **catalog):
    use_catalog(monkeypatch, **catalog)
    app = KramApp()

    async def go():
        async with app.run_test(size=WIDE) as pilot:
            await loaded(app, pilot)
            await test(app, pilot)
    asyncio.run(go())
    return app


def local_catalog(catalog) -> dict:
    """The methods of the Install presenter's catalog, for the window's (tests/test_tui_window.use_catalog)."""
    return {"open_local": catalog.open_local, "resolve_local": catalog.resolve_local,
            "forget_local": catalog.forget_local, "removal_dependents": lambda names: []}


def install_ready(app) -> bool:
    """The installer is on top, composed, and its button can be pressed."""
    screen = app.screen
    return isinstance(screen, InstallDialog) and any(b.enabled for b in screen.query("#install").results(Button))


# ---------------------------------------------------------------- the dialog

@pytest.mark.feature(Feature.DIALOG_INSTALL_FILE, front="tui")
@pytest.mark.feature(Feature.DIALOG_INSTALL_FILE_COMMAND, front="tui")
def test_the_dialog_shows_what_the_file_does_and_the_command(rpm, monkeypatch):
    copied = []

    async def test(app, pilot):
        app.copy_to_clipboard = copied.append
        dialog, _results = await show(app, pilot, rpm.path, Catalog(), marks=2)
        box = dialog.query_one("#install-box")
        assert box.border_title == "Install package file"
        title = text(dialog, "title")
        assert title.startswith("tool 2.0-1.x86_64") and "A tool" in title
        notes = text(dialog, "notes").splitlines()
        assert notes[0] == f"{app.glyphs.yes} Upgrades the installed version 1.0-1 to 2.0-1."
        assert f"{app.glyphs.yes} Signed by Fedora." in notes
        assert any(n.startswith(f"{app.glyphs.warning} Runs scripts as root") for n in notes)
        assert any("2 changes marked in the main window" in n for n in notes)
        assert "Disk space change" in text(dialog, "sizes")
        assert "tool" in dialog.query_one(ChangeList).render().plain
        assert text(dialog, "command") == f"sudo dnf5 install {rpm.path}"
        assert "Does things." in dialog.query_one("#description").render().plain
        assert "bash" in dialog.query_one("#deps").render().plain
        assert text(dialog, "scripts") == "echo hi" and text(dialog, "files") == "/usr/bin/tool"
        button = dialog.query_one("#install", Button)
        assert button.label == "Upgrade" and button.enabled and button.has_focus  # the default button
        assert "ctrl+a upgrade" in box._border_subtitle.plain
        await pilot.press("y")
        assert copied == [f"sudo dnf5 install {rpm.path}"]
    run_alone(monkeypatch, test)


def test_a_file_that_cannot_be_installed_says_why_and_has_no_button(rpm, monkeypatch):
    async def test(app, pilot):
        dialog, _results = await show(app, pilot, rpm.path, Catalog(problems=["nothing provides libfoo"]))
        notes = text(dialog, "notes")
        assert notes.startswith(f"{app.glyphs.no} Cannot be installed.") and "nothing provides libfoo" in notes
        assert not dialog.query_one("#install", Button).display and not text(dialog, "command")
        assert "ctrl+a" not in dialog.query_one("#install-box")._border_subtitle.plain
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
    run_alone(monkeypatch, test)


def test_note_lines_and_the_files_split():
    from kram.app.icons import ERROR, INFO
    assert note_text(install.note(ERROR, "No."), UNICODE).plain == "✗ No."
    assert note_text(install.note(INFO, "So."), UNICODE).plain == "i So."
    assert note_text(install.note(install.INDENT, "a\nb"), UNICODE).plain == "  a\nb"
    assert split_files("# Missing: /a\n# Changed: /b\n\n/a\n/b") == (["Missing: /a", "Changed: /b"], "/a\n/b")
    assert split_files("/a") == ([], "/a")


@pytest.mark.feature(Feature.DIALOG_INSTALL_FILE_CHECK, front="tui")
def test_a_reinstall_checks_the_installed_files_and_shows_what_it_repairs(rpm, monkeypatch):
    started = []
    monkeypatch.setattr(install.proc, "run",
                        lambda cmd, post, env, done: started.append(done) or SimpleNamespace(kill=lambda: None))
    monkeypatch.setattr(local_rpm, "parse_verify",
                        lambda out: VerifyResult(changed=[("/etc/tool.conf", "5T", True)], missing=["/usr/bin/tool"]))

    async def test(app, pilot):
        dialog, _results = await show(app, pilot, rpm.path, Catalog(action="reinstall"))
        button = dialog.query_one("#install", Button)
        assert "Checking the installed files of tool" in text(dialog, "status") and not button.enabled
        assert not dialog.query_one("#check-title").display
        started[0](1, "whatever", "")
        await pilot.pause()
        assert button.enabled and button.label == "Reinstall" and not text(dialog, "status")
        assert text(dialog, "check").splitlines() == [
            "Missing: /usr/bin/tool", "Changed (contents, modification time): /etc/tool.conf — a configuration file"]
        assert dialog.query_one("#check-title").display
        assert "2 installed files are missing or changed" in text(dialog, "notes")
    run_alone(monkeypatch, test)


@pytest.mark.feature(Feature.DIALOG_INSTALL_FILE_RECOMMENDATIONS, front="tui")
def test_unticking_a_recommendation_resolves_again_without_it(rpm, monkeypatch):
    catalog = RecCatalog()

    async def test(app, pilot):
        dialog, _results = await show(app, pilot, rpm.path, catalog)
        [box] = dialog.query(RecBox)
        assert box.value and "tool-extras" in box.label
        assert "Recommended packages." in text(dialog, "recs-note")
        assert "tool-extras" in dialog.query_one(ChangeList).render().plain
        box.focus()
        await pilot.press("space")
        await pilot.pause()
        assert catalog.excluded[-1] == ["tool-extras"]
        assert "tool-extras" not in dialog.query_one(ChangeList).render().plain
        assert text(dialog, "command") == f"sudo dnf5 install --setopt=exclude_from_weak=tool-extras {rpm.path}"
        assert not dialog.query_one(RecBox).value
    run_alone(monkeypatch, test)


def test_install_runs_the_request_and_closes_when_it_succeeded(rpm, monkeypatch):
    ran = []

    async def test(app, pilot):
        dialog, results = await show(app, pilot, rpm.path, Catalog(),
                                     run=lambda request, title, done: ran.append((request, title, done)))
        await pilot.press("ctrl+a")
        await pilot.press("escape")  # not while it runs (root is asked for before its progress shows)
        await pilot.pause()
        assert app.screen is dialog
        request, title, done = ran[0]
        assert request["op"] == "local_install" and request["path"] == rpm.path and title == "Installing tool"
        assert not dialog.query_one("#install", Button).enabled  # while it runs
        done(False)
        await pilot.pause()
        assert dialog.query_one("#install", Button).enabled and app.screen is dialog
        await pilot.press("ctrl+a")
        ran[1][2](True)
        await pilot.pause()
        await pilot.pause()
        assert results == [True] and len(app.screen_stack) == 1
    run_alone(monkeypatch, test)


# ---------------------------------------------------------------- from the window

def test_install_through_the_helper_reloads_the_window(rpm, monkeypatch, helper):  # noqa: F811
    loads = []
    catalog = Catalog()

    def load(*_a, **_k):
        from test_tui_window import snapshot
        loads.append(1)
        return snapshot()

    async def test(app, pilot):
        app.main.install_file(rpm.path)
        await until(pilot, lambda: install_ready(app))
        before = len(loads)
        await pilot.press("ctrl+a")
        dialog = await finish(app, pilot)  # the progress dialog; the installer closes after it
        assert dialog.title_text == "Installing tool" and dialog.request["op"] == "local_install"
        assert helper() == ["local_install"]
        await until(pilot, lambda: len(app.screen_stack) == 1 and len(loads) > before)
        assert catalog.forgot
        app.main.browser.helper.stop()
    run_window(monkeypatch, test, load=load, **local_catalog(catalog))


@pytest.mark.feature(Feature.INSTALL_FILE_OPEN_MENU, front="tui")
def test_open_package_file_asks_for_a_path_in_the_last_folder(rpm, monkeypatch, tmp_path):
    settings.set(INSTALL_DIR_KEY, "/nonexistent")

    async def test(app, pilot):
        app.main.run_action("open_file")
        await pilot.pause()
        path_dialog = app.screen
        assert isinstance(path_dialog, PathDialog) and path_dialog.title_text == "Open package file"
        assert path_dialog.patterns == ["*.rpm"]
        field = path_dialog.query_one("#path")
        field.value = str(tmp_path) + "/tool"
        await pilot.press("tab")  # completes the only .rpm
        assert field.value == rpm.path
        await pilot.press("enter")
        await until(pilot, lambda: isinstance(app.screen, InstallDialog))
        assert settings.get(INSTALL_DIR_KEY) == str(tmp_path)
        await pilot.press("escape")
        await until(pilot, lambda: len(app.screen_stack) == 1)
        app.main.run_action("open_file")  # the folder is remembered
        await pilot.pause()
        assert app.screen.query_one("#path").value == str(tmp_path) + "/"
    run_window(monkeypatch, test, **local_catalog(Catalog()))


def test_a_pasted_path_names_an_existing_rpm(rpm, monkeypatch, tmp_path):
    other = tmp_path / "my tool.rpm"
    other.write_bytes(b"rpm")
    assert pasted_rpm(rpm.path) == rpm.path
    assert pasted_rpm(f"  '{other}'\n") == str(other)       # quoted, as GNOME Terminal pastes a drop
    assert pasted_rpm(str(other).replace(" ", "\\ ")) == str(other)  # escaped
    assert pasted_rpm(str(other)) == str(other)            # spaces nobody quoted
    assert pasted_rpm("file://" + str(other).replace(" ", "%20")) == str(other)
    assert pasted_rpm("file://elsewhere" + rpm.path) is None
    assert pasted_rpm(str(tmp_path / "missing.rpm")) is None
    (tmp_path / "notes.txt").write_text("x")
    assert pasted_rpm(str(tmp_path / "notes.txt")) is None
    assert pasted_rpm(f"{rpm.path}\n{other}") is None       # two files
    assert pasted_rpm("") is None


def test_a_pasted_rpm_opens_the_installer_but_not_over_a_dialog(rpm, monkeypatch, tmp_path):
    """The terminal's paste reaches the app, which hands it to the focused widget (the list), which leaves it to the
    window (Textual's App.on_event)."""
    async def test(app, pilot):
        assert app.focused is app.main.list
        app.post_message(events.Paste(f"'{rpm.path}'"))
        await until(pilot, lambda: isinstance(app.screen, InstallDialog))
        await pilot.press("escape")
        await until(pilot, lambda: len(app.screen_stack) == 1)
        app.post_message(events.Paste(str(tmp_path / "notes.txt")))  # not an rpm
        await pilot.pause()
        assert len(app.screen_stack) == 1
        app.main.run_action("about")
        await pilot.pause()
        about = app.screen
        app.post_message(events.Paste("file://" + rpm.path))  # a dialog is open: nothing
        await pilot.pause()
        await pilot.pause()
        assert app.screen is about
    run_window(monkeypatch, test, **local_catalog(Catalog()))


# ---------------------------------------------------------------- alone (§15.2)

@pytest.mark.feature(Feature.INSTALL_FILE_ARGUMENT, front="tui")
def test_kram_tui_file_rpm_runs_the_installer_alone_and_ends_with_it(rpm, monkeypatch):
    catalog = Catalog()
    loaded_ = []
    catalog.load = lambda *a, **k: loaded_.append(1) or type("Snap", (), {"basearch": "x86_64"})()
    monkeypatch.setattr(installer.InstallerApp, "make_catalog", staticmethod(lambda: catalog))
    monkeypatch.setattr(installer, "DnfWorker", lambda post: Sync())
    app = installer.InstallerApp(rpm.path)
    assert app.main is None

    async def go():
        async with app.run_test(size=WIDE) as pilot:
            await until(pilot, lambda: install_ready(app))
            dialog = app.screen
            assert loaded_ == [1]  # the catalog, loaded by the installer itself
            assert len(app.screen_stack) == 2 and "tool" in text(dialog, "title")
            await pilot.press("escape")
            await until(pilot, lambda: not app.is_running)
    asyncio.run(go())
    assert catalog.forgot and not app.changed_system


def test_the_command_line_runs_the_installer_for_a_file(monkeypatch):
    ran = []
    monkeypatch.setattr(installer.InstallerApp, "__init__", lambda self, path: ran.append(path) or None)
    monkeypatch.setattr(installer.InstallerApp, "run", lambda self: ran.append("run"))
    assert tui_main.main(["/tmp/a.rpm"]) == 0 and ran == ["/tmp/a.rpm", "run"]
    assert tui_main.file_path("file:///tmp/my%20a.rpm") == "/tmp/my a.rpm"


def test_the_installer_alone_shows_questions_over_it(rpm, monkeypatch):
    """A busy helper says so over the dialog, and the dialog stays."""
    catalog = Catalog()
    catalog.load = lambda *a, **k: type("Snap", (), {"basearch": "x86_64"})()
    monkeypatch.setattr(installer.InstallerApp, "make_catalog", staticmethod(lambda: catalog))
    monkeypatch.setattr(installer, "DnfWorker", lambda post: Sync())
    app = installer.InstallerApp(rpm.path)

    async def go():
        async with app.run_test(size=WIDE) as pilot:
            await until(pilot, lambda: install_ready(app))
            dialog = app.screen
            app.helper.busy = True
            done = []
            app.run_request({"op": "local_install"}, "Installing tool", done.append)
            await pilot.pause()
            assert done == [False] and isinstance(app.screen, QuestionDialog)
            app.helper.busy = False
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen is dialog
            assert not isinstance(app.screen, ProgressDialog)
            await pilot.press("escape")
            await until(pilot, lambda: not app.is_running)
    asyncio.run(go())
