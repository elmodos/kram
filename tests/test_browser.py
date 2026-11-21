"""kram.app.browser without a toolkit: the flows that wait for the user, with a fake window and a recording Ui."""
from types import SimpleNamespace

from kram.app.browser import Browser, ReposChoice
from kram.app.ports import RecordingUi
from kram.app.scheduler import FakeScheduler
from kram.core.history import Change
from kram.core.marks import Action
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

    def show_repos(self, snap, counts, owners, listed, installed, done):
        self.calls.append(("repos", counts))
        done(self.repos)


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


def test_removing_repositories_reopens_the_list_after_the_reload():
    b, view, _ui, jobs = browser()
    b.snapshot = CatalogSnapshot(ROWS, 1, 0, 0.0, repos=[RepoInfo("copr:a", "a", True, Origin.COPR, 60)])
    opened = []
    b.reload = lambda: view.calls.append(("reload",))
    view.repos = ReposChoice(remove_repos=("copr:a",))
    b.catalog.repo_package_counts = lambda: {"copr:a": 3}
    b.open_repos()
    jobs.run(({"copr:a": 3}, {}))
    assert views(view, "helper") == [("helper", {"op": "repo_remove", "repos": ["copr:a"]})]
    b.open_repos = lambda: opened.append(1)
    b.catalog_loaded.emit(b.snapshot)
    b.catalog_loaded.emit(b.snapshot)  # only once
    assert opened == [1] and views(view, "repos")[0][1] == {"copr:a": 3}


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
