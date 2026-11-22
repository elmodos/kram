"""kram.app.copr without a toolkit: the projects table, the search and the questions before a change."""
import json
from collections import Counter
from types import SimpleNamespace

import pytest

from kram.app import copr as copr_app
from kram.app.parity import Feature
from kram.app.ports import RecordingUi
from kram.core import net
from kram.core.model import Origin, RepoInfo

REPO = "copr:copr.fedorainfracloud.org:elmodos:Kram"


class View:
    def __init__(self):
        self.projects, self.results, self.status, self.searching, self.selected = [], [], "", False, False

    def show_projects(self, projects):
        self.projects = projects

    def show_results(self, results):
        self.results = results

    def show_search_status(self, text):
        self.status = text

    def set_searching(self, on):
        self.searching = on

    def select_first_result(self):
        self.selected = True


def snapshot(installed=2):
    rows = [SimpleNamespace(installed=True, origin_repo=REPO)] * installed
    return SimpleNamespace(rows=rows, repos=[RepoInfo(REPO, "Kram", True, Origin.COPR, 60)], releasever="45",
                           basearch="x86_64")


def projects(answers=(), body=None):
    view, ui, helper, shown = View(), RecordingUi(list(answers)), [], []
    c = copr_app.CoprProjects(view, ui, lambda fn: fn(), lambda req, title: helper.append((req, title)),
                              shown.append)
    c.set_catalog(snapshot(), Counter({REPO: 7}))
    return c, view, ui, helper, shown


def test_the_table_and_the_buttons():
    c, view, *_ = projects()
    [p] = view.projects
    assert (p.project, p.hub, p.enabled, p.packages, p.installed) == ("elmodos/Kram", "copr.fedorainfracloud.org",
                                                                       True, "7", "2")
    b = c.buttons(p, None, "")
    assert (b.enable, b.disable, b.remove, b.add) == (False, True, True, False)
    assert c.buttons(None, None, "owner/project").add


@pytest.mark.feature(Feature.DIALOG_COPR_REMOVE_QUESTION, front="qt")
def test_removing_asks_and_can_show_the_packages_instead():
    c, view, ui, helper, shown = projects(answers=["show", "remove"])
    c.remove(view.projects[0])
    assert shown == [REPO] and helper == [] and "2 installed packages" in ui.calls[0][1].informative
    c.remove(view.projects[0])
    assert helper == [({"op": "copr", "action": "remove", "project": "elmodos/Kram"}, "Removing elmodos/Kram")]


@pytest.mark.feature(Feature.DIALOG_COPR_NO_BUILD_QUESTION, front="qt")
def test_search_marks_the_enabled_project_and_missing_builds(monkeypatch):
    payload = {"items": [{"full_name": "elmodos/Kram", "description": "d", "chroot_repos": {"fedora-45-x86_64": ""}},
                         {"full_name": "a/old", "description": "", "chroot_repos": {"fedora-43-x86_64": ""}}]}
    monkeypatch.setattr(net, "fetch", lambda url, *, done, **kw: done(json.dumps(payload).encode()))
    c, view, ui, helper, _shown = projects(answers=["no", "yes"])
    c.search("kram")
    assert view.status == "2 projects found." and view.selected and not view.searching
    names = {r.name: r for r in view.results}
    assert names["elmodos/Kram  (enabled)"].builds_ok and not names["a/old"].builds_ok
    old = names["a/old"].project
    c.enable(old, "")
    c.enable(old, "")
    assert len(helper) == 1 and helper[0][0]["project"] == "a/old"


def test_a_failed_search_says_why(monkeypatch):
    monkeypatch.setattr(net, "fetch", lambda url, *, failed, **kw: failed(net.NetError("HTTP 503: Unavailable")))
    c, view, *_ = projects()
    c.search("kram")
    assert view.status == "Search failed: HTTP 503: Unavailable" and not view.searching
