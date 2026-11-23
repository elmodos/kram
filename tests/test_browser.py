"""kram.app.browser without a toolkit: the flows that wait for the user, with a fake window and a recording Ui."""
from types import SimpleNamespace

from kram.app.browser import Browser
from kram.app.mirrors import MirrorChoice
from kram.app.ports import RecordingUi
from kram.app.scheduler import FakeScheduler
from kram.core.history import Change
from kram.core.marks import Action
from kram.core.mirrors import SourceKind
from kram.core.model import CatalogSnapshot, Origin, PkgRow, RepoInfo, Status, TransactionPreview


def row(name, status=Status.NOT_INSTALLED, installed=""):
    return PkgRow(name, "x86_64", "", installed, "1-1", "fedora", 1, Origin.FEDORA, status)


ROWS = [row("fish"), row("vim", Status.INSTALLED, "1-1")]


class Jobs:
    """The dnf thread, run by hand: `run()` does the next job and hands its result over."""

    def __init__(self):
        self.jobs = []
        self.cancelled = None

    def submit(self, fn, done, failed=None):
        self.jobs.append((fn, done, failed))

    def run(self, result=None, error=None):
        fn, done, failed = self.jobs.pop(0)
        if error is not None:
            failed(error)
        else:
            done(fn() if result is None else result)

    def shutdown(self):
        pass


class View:
    """The window, recording what the browser asks of it; its dialogs answer from `review`, `helper`, `repos`."""

    def __init__(self):
        self.calls = []
        self.status = ""
        self.review = None      # what review_changes answers: a request, or None (cancelled)
        self.helper = {"ok": True}
        self.repos = None
        self.mirrors = None     # what show_mirrors answers: a MirrorChoice, or None
        self.selected: list[PkgRow] = []

    def __getattr__(self, name):  # everything else is only recorded
        return lambda *args: self.calls.append((name, *args))

    def current_key(self):
        return None

    def select_key(self, key, scroll=True):
        return False

    def selected_rows(self):
        return self.selected

    def set_status(self, text):
        self.status = text

    def status_text(self):
        return self.status

    def review_changes(self, preview, request, basearch, resolve, done):
        self.calls.append(("review", request))
        done(self.review)

    def run_helper(self, request, title, done):
        self.calls.append(("helper", request))
        done(self.helper)

    def show_repos(self, data, done):
        self.calls.append(("repos", data.counts))
        done(self.repos)

    def show_mirrors(self, repo, source, fastestmirror, apply):
        self.calls.append(("mirrors", repo.id, source.kind, fastestmirror))
        if self.mirrors is not None:  # the user chose something while it is open
            apply(self.mirrors)


class Helper:
    busy = False

    def stop(self):
        pass


def browser(answers=()):
    view, ui, jobs = View(), RecordingUi(list(answers)), Jobs()
    b = Browser(view, ui, FakeScheduler(), SimpleNamespace(show_advisories=lambda r: None,
                                                           show_blocked=lambda r: None, clear=lambda: None,
                                                           show_package=lambda r, d: None),
                post=lambda fn: fn(), catalog=SimpleNamespace(), dnf=jobs, helper=Helper())
    b.snapshot = CatalogSnapshot(ROWS, 1, 0, 0.0)
    b.packages.set_rows(ROWS, "x86_64")
    b.marker.set_snapshot = lambda snap: None
    return b, view, ui, jobs


def views(view, name):
    return [c for c in view.calls if c[0] == name]


def test_apply_resolves_reviews_runs_and_unmarks_what_it_applied():
    b, view, ui, jobs = browser()
    b.packages.marks.set(ROWS[0], Action.INSTALL)
    reloads = []
    b.reload = lambda: reloads.append(1)
    b.apply()
    b.apply()  # a second Apply while it resolves: nothing
    assert len(jobs.jobs) == 1 and b.busy() and view.status == "Resolving dependencies…"
    request = {"op": "transaction", "install": ["fish.x86_64"]}
    view.review = request
    b.packages.marks.set(ROWS[1], Action.REINSTALL)  # marked while the first request resolved
    jobs.run(TransactionPreview([], [], 0, 0))
    assert views(view, "helper") == [("helper", request)]
    assert [k for k, _m in b.packages.marks.items()] == [ROWS[1].key] and reloads == [1]


def test_a_cancelled_review_and_a_download_only_run_change_nothing():
    b, view, _ui, jobs = browser()
    b.packages.marks.set(ROWS[0], Action.INSTALL)
    b.reload = lambda: view.calls.append(("reload",))
    b.apply()
    jobs.run(TransactionPreview([], [], 0, 0))  # view.review is None: cancelled
    assert views(view, "helper") == [] and len(b.packages.marks) == 1
    view.review = {"op": "transaction", "download_only": True}
    b.apply()
    jobs.run(TransactionPreview([], [], 0, 0))
    assert views(view, "helper") and views(view, "reload") == [] and len(b.packages.marks) == 1


def test_changes_the_version_lock_excludes_offer_the_locked_packages():
    b, view, ui, jobs = browser(answers=["locked"])
    b.packages.marks.set(ROWS[0], Action.INSTALL)
    selected = []
    b.sidebar.select = lambda v, e: selected.append(e)
    b.apply()
    jobs.run(TransactionPreview([], ["nothing provides x"], 0, 0, versionlock=True))
    jobs.run([])  # no conflicting installed packages to offer
    question = ui.calls[0][1]
    assert question.icon == "warning" and [btn.id for btn in question.buttons] == ["locked", "ok"]
    assert "version lock excludes" in question.informative and question.details == "nothing provides x"
    assert selected == ["status:locked"]


def test_an_undo_that_cannot_be_done_whole_offers_what_is_possible():
    b, view, ui, jobs = browser(answers=["skip"])
    request = {"op": "transaction", "revert": [7]}
    b._review(request, marked=False)
    failed = TransactionPreview([], ["gone"], 0, 0)
    jobs.run(failed)
    jobs.run(True)  # leaving out what is unavailable resolves
    assert [btn.id for btn in ui.calls[0][1].buttons] == ["skip", "ok"]
    assert len(jobs.jobs) == 1  # resolving it again, without the unavailable versions
    fn, _done, _failed = jobs.jobs[0]
    b.catalog.resolve = lambda req, sizes=True: SimpleNamespace(req=req)
    assert fn().req == {**request, "skip_unavailable": True}


def conflicting(answers=(), front_package=""):
    """fish is marked for installation and does not resolve; vim, installed, is what conflicts with it."""
    b, view, ui, jobs = browser(answers)
    b.front_package = front_package
    b.packages.marks.set(ROWS[0], Action.INSTALL)
    b.apply()
    jobs.run(TransactionPreview([], ["fish conflicts with vim"], 0, 0))
    fn, _done, _failed = jobs.jobs[0]
    asked = []
    b.catalog.conflict_removals = lambda req: asked.append(req) or [ROWS[1].key]
    jobs.run()
    assert asked == [{"op": "transaction", "install": ["fish.x86_64"]}]
    return b, view, ui, jobs


def test_conflicting_installed_packages_are_offered_for_removal_and_reviewed():
    b, view, ui, jobs = conflicting(answers=["mark"])
    question = ui.calls[0][1]
    assert question.title == "Conflicting packages" and "1 installed package conflicts" in question.text
    assert question.informative == "vim" and question.details == "fish conflicts with vim"
    assert [btn.id for btn in question.buttons] == ["cancel", "mark"] and question.default == "mark"
    assert b.packages.marks.get(ROWS[1].key).action is Action.REMOVE
    assert len(jobs.jobs) == 1 and b.busy()  # the review of both changes is resolving
    b.catalog.resolve = lambda req, sizes=True: SimpleNamespace(req=req)
    assert jobs.jobs[0][0]().req == {"op": "transaction", "install": ["fish.x86_64"], "remove": ["vim.x86_64"]}


def test_declining_the_conflicting_removals_changes_nothing():
    b, _view, ui, jobs = conflicting(answers=["cancel"])
    assert ui.kinds() == ["ask"] and [k for k, _m in b.packages.marks.items()] == [ROWS[0].key]
    assert not jobs.jobs and not b.busy()


def test_without_conflicting_packages_it_says_why_it_cannot_apply():
    b, _view, ui, jobs = browser(answers=["ok"])
    b.packages.marks.set(ROWS[0], Action.INSTALL)
    b.apply()
    jobs.run(TransactionPreview([], ["nothing provides libfoo"], 0, 0))
    jobs.run([])
    question = ui.calls[0][1]
    assert question.title == "Cannot apply changes" and question.details == "nothing provides libfoo"


def test_marks_changed_while_looking_for_conflicts_drop_the_offer():
    b, view, ui, jobs = browser()
    b.packages.marks.set(ROWS[0], Action.INSTALL)
    b.apply()
    jobs.run(TransactionPreview([], ["fish conflicts with vim"], 0, 0))
    b.packages.marks.unmark(ROWS[0].key)
    jobs.run([ROWS[1].key])
    assert ui.calls == [] and not b.busy()


def test_removing_the_running_front_end_closes_kram_instead_of_reloading():
    b, view, ui, jobs = conflicting(answers=["mark", "ok"], front_package="vim")
    assert "front end of Kram you are using (vim)" in ui.calls[0][1].informative
    b.reload = lambda: view.calls.append(("reload",))
    view.review = {"op": "transaction", "install": ["fish.x86_64"], "remove": ["vim.x86_64"]}
    jobs.run(TransactionPreview([], [], 0, 0))
    assert "Kram closes now" in ui.calls[1][1].text
    assert views(view, "quit") == [("quit",)] and views(view, "reload") == [] and not len(b.packages.marks)


def test_quitting_with_marks_asks():
    b, _view, ui, _jobs = browser(answers=["no", "yes"])
    answers = []
    b.can_close(answers.append)
    b.packages.marks.set(ROWS[0], Action.INSTALL)
    b.can_close(answers.append)
    b.can_close(answers.append)
    assert answers == [True, False, True] and "1 marked change" in ui.calls[0][1].text
    b._reviewing = True
    b.can_close(answers.append)
    assert answers[-1] is False


def test_a_failed_resolve_says_so_and_allows_a_retry():
    b, view, ui, jobs = browser()
    b.packages.marks.set(ROWS[0], Action.INSTALL)
    b.apply()
    jobs.run(error=RuntimeError("boom"))
    assert not b.busy() and ui.kinds() == ["error"] and "boom" in ui.calls[0][2]
    b.apply()
    assert len(jobs.jobs) == 1


def test_removing_repositories_runs_the_helper_and_reopens_nothing():
    b, view, _ui, jobs = browser()
    b.snapshot = CatalogSnapshot(ROWS, 1, 0, 0.0, repos=[RepoInfo("copr:a", "a", True, Origin.COPR, 60)],
                                 releasever="45", basearch="x86_64")
    b.reload = lambda: view.calls.append(("reload",))
    b.catalog.repo_package_counts = lambda: {"copr:a": 3}
    b.open_repos()
    jobs.run(({"copr:a": 3}, {}))
    assert views(view, "repos") == [("repos", {"copr:a": 3})]
    b.remove_repos(["copr:a"])  # from the dialog, which stays open
    assert views(view, "helper") == [("helper", {"op": "repo_remove", "repos": ["copr:a"]})]
    b.catalog_loaded.emit(b.snapshot)
    assert len(views(view, "repos")) == 1  # the open dialog updates itself: no second one


def test_the_repositories_data_is_read_for_any_snapshot():
    b, _view, _ui, jobs = browser()
    snap = CatalogSnapshot(ROWS, 1, 0, 0.0, repos=[RepoInfo("copr:a", "a", True, Origin.COPR, 60)],
                           releasever="45", basearch="x86_64")
    b.catalog.repo_package_counts = lambda: {"copr:a": 3}
    got = []
    b.repos_data(snap, got.append)
    jobs.run(({"copr:a": 3}, {"/x.repo": "pkg"}))
    [data] = got
    assert (data.repos, data.counts, data.owners, data.variables) == (
        snap.repos, {"copr:a": 3}, {"/x.repo": "pkg"}, {"releasever": "45", "basearch": "x86_64"})


def mirror_browser():
    b, view, _ui, jobs = browser()
    repo = RepoInfo("updates", "Updates", True, Origin.FEDORA, 60, metalink="https://ml/x")
    b.snapshot = CatalogSnapshot(ROWS, 1, 0, 0.0, repos=[repo], releasever="45", basearch="x86_64", fastestmirror=True)
    b.reload = lambda: view.calls.append(("reload",))
    return b, view


def test_the_mirrors_dialog_opens_and_closing_it_changes_nothing():
    b, view = mirror_browser()
    b.open_mirrors("updates")
    assert views(view, "mirrors") == [("mirrors", "updates", SourceKind.METALINK, True)]
    assert not views(view, "helper") and not views(view, "repos")  # Repositories was never closed


def test_pinning_a_mirror_runs_the_helper_and_reloads():
    b, view = mirror_browser()
    view.mirrors = MirrorChoice("updates", "https://a.example/f/")
    b.open_mirrors("updates")
    assert views(view, "helper") == [("helper", {"op": "mirrors",
                                                 "pin": {"repo": "updates", "baseurl": "https://a.example/f/"}})]
    assert views(view, "reload") and not views(view, "repos")
    b.snapshot.repos[0].metalink, b.snapshot.repos[0].baseurls = "", ("https://a.example/f/",)
    b.snapshot.repos[0].file_path = ""
    assert b.mirror_state(b.snapshot, "updates") is None  # pinned, but its file names no list: nothing to show
    b.snapshot.repos[0].metalink = "https://ml/x"
    source, fastest = b.mirror_state(b.snapshot, "updates")
    assert source.url == "https://ml/x" and fastest is True and b.mirror_state(b.snapshot, "gone") is None


def test_going_back_to_automatic_and_the_fastest_option():
    b, view = mirror_browser()
    view.mirrors = MirrorChoice("updates", None)
    b.open_mirrors("updates")
    view.mirrors = MirrorChoice(fastestmirror=False)
    b.open_mirrors("updates")
    assert [r for _n, r in views(view, "helper")] == [{"op": "mirrors", "pin": {"repo": "updates", "baseurl": None}},
                                                      {"op": "mirrors", "fastestmirror": False}]


def test_a_repository_without_mirrors_opens_nothing():
    b, view = mirror_browser()
    b.snapshot.repos[0].metalink = ""
    b.open_mirrors("updates")
    b.open_mirrors("gone")
    assert not views(view, "mirrors")

def test_an_undo_reports_what_cannot_be_undone():
    b, view, ui, jobs = browser()
    rows = [SimpleNamespace(key=("fish", "x86_64"), change=Change.UNREADABLE)]
    b.undo_transaction(3, rows, lambda: None)
    assert ui.kinds() == ["warn"] and "could not be read" in ui.calls[0][2]


def test_status_counts_follow_the_marks():
    b, view, _ui, _jobs = browser()
    b.packages.set_visible([0, 1])
    b.marker.mark([ROWS[0]], Action.INSTALL)
    counts = views(view, "show_counts")[-1]
    assert counts[2:5] == (2, 1, 0)
