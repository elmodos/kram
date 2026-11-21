"""kram.app.install without a toolkit: the header's lines, the tabs and the button follow what is known so far."""
from kram.app import install
from kram.app.doc import plain_text
from kram.app.icons import ERROR, OK, WARN
from kram.core import local_rpm
from kram.core.local_rpm import LocalRpm, Signature, VerifyResult
from kram.core.model import LocalTarget, PreviewItem, Requirement, TransactionPreview


def make_rpm(**kw) -> LocalRpm:
    rpm = LocalRpm("/tmp/tool-2.0-1.x86_64.rpm", "ab" * 32, 1000, "tool", None, "2.0", "1", "x86_64", "A tool",
                   "Does things.\n\nWell.", "", "MIT", "", "", 0, 5000, False, ["bash"], [], [], [], ["tool"], [], [],
                   ["/usr/bin/tool"], [], "echo hi", Signature("ok", "dbfcf71c6d9f90a6", "Fedora"))
    for k, v in kw.items():
        setattr(rpm, k, v)
    return rpm


class Sync:
    """The dnf thread and the file reader, run at once."""

    def __init__(self):
        self.calls = []

    def submit(self, fn, done, failed=None):
        try:
            result = fn()
        except Exception as error:  # noqa: BLE001
            failed(error)
            return
        done(result)

    def shutdown(self):
        self.calls.append("shutdown")


class Catalog:
    def __init__(self, action="upgrade", problems=()):
        self.action, self.problems, self.forgot = action, list(problems), False

    def open_local(self, path):
        return LocalTarget(self.action, "1.0-1", "", "", {"requires": [Requirement("bash", ["bash"], ["bash"])],
                                                          "recommends": [], "suggests": []})

    def resolve_local(self, path, action, exclude, sizes=True):
        items = [PreviewItem(action, "tool", "x86_64", "2.0-1", "1.0-1", "@commandline", 1000, 5000, "user")]
        return TransactionPreview(items, self.problems, 0, 4000)

    def forget_local(self):
        self.forgot = True


class View:
    def __getattr__(self, name):
        def record(*args):
            setattr(self, name.removeprefix("show_"), args[0] if len(args) == 1 else args)
        return record


def run(monkeypatch, rpm, catalog, **kw):
    monkeypatch.setattr(local_rpm, "read", lambda path: rpm)
    monkeypatch.setattr(install, "DnfWorker", lambda post, name: Sync())
    view = View()
    logic = install.Install(rpm.path, catalog, Sync(), lambda fn: fn(), view, busy=lambda: False, **kw)
    logic.start()
    return logic, view


def test_an_upgrade_shows_what_it_does_and_can_be_installed(monkeypatch):
    logic, view = run(monkeypatch, make_rpm(), Catalog(), marks=2)
    kinds = [n.kind for n in view.notes]
    assert kinds[:2] == [OK, OK] and WARN in kinds  # upgrade, signed; scripts run as root
    assert view.title == ("tool", "2.0-1.x86_64", "A tool")
    assert view.button == install.InstallButton("Upgrade", "go-up", True, True) and view.status == ""
    assert "bash — installed: bash" in plain_text(view.deps)
    assert view.command == "sudo dnf5 install /tmp/tool-2.0-1.x86_64.rpm"
    ran = []
    view.run_transaction = lambda request, title, done: ran.append((request, title, done))
    logic.install()
    request, title, done = ran[0]
    assert request["op"] == "local_install" and title == "Installing tool" and logic.changed_system
    assert not view.button.enabled  # while it runs
    done(False)
    assert view.button.enabled
    logic.close()
    assert logic.catalog.forgot


def test_a_source_package_cannot_be_installed(monkeypatch):
    _logic, view = run(monkeypatch, make_rpm(source="tool-2.0-1.src.rpm"), Catalog())
    assert view.notes[0].kind == ERROR and "source package" in "".join(view.notes[1].spans)
    assert not view.button.visible and view.command is None


def test_unresolvable_shows_the_solvers_reason_cut_short(monkeypatch):
    problems = ["line %d" % i for i in range(10)]
    _logic, view = run(monkeypatch, make_rpm(), Catalog(problems=["\n".join(problems)]))
    reason = [s for s in view.notes[1].spans if isinstance(s, str)]
    assert reason[:4] == problems[:4] and "Dependencies tab" in reason[-1]
    assert view.changes[1] == problems and not view.button.visible


def test_a_reinstall_checks_the_installed_files_first(monkeypatch):
    started = []
    monkeypatch.setattr(install.proc, "run", lambda cmd, post, env, done: started.append(done) or object())
    monkeypatch.setattr(local_rpm, "parse_verify",
                        lambda out: VerifyResult(changed=[("/etc/tool.conf", "5T", True)], missing=["/usr/bin/tool"]))
    _logic, view = run(monkeypatch, make_rpm(), Catalog(action="reinstall"))
    assert "Checking the installed files" in view.status and not view.button.enabled
    started[0](1, "whatever", "")
    assert view.button.enabled and view.files.startswith(
        "# Missing: /usr/bin/tool\n# Changed (contents, modification time): /etc/tool.conf — a configuration file")
    assert "2 installed files are missing or changed (see the Files tab)." in [n.spans[0] for n in view.notes]
