"""kram.app.custom_filters without a toolkit: editing, deleting and making filters, and what is saved."""
import json
from types import SimpleNamespace

import pytest

from kram.app.custom_filters import PREFIX, SETTINGS_KEY, CustomFilters
from kram.app.parity import Feature
from kram.app.ports import RecordingUi
from kram.core.custom_filters import Condition, CustomFilter, Field, Op
from kram.core.filters import FilterEntry
from kram.core.search import Mode
from kram.core.settings import store as settings

VIM = CustomFilter("Vim", [Condition(Field.NAME, Op.CONTAINS, "vim")])


class Sidebar:
    def __init__(self, entry_id=None):
        self.custom, self.current_view, self.current_entry_id = [], "status", entry_id
        self.calls = []

    def select(self, view, entry):
        self.calls.append(("select", view, entry))

    def set_view(self, view):
        self.calls.append(("view", view))


def filters(answers=(), dialog_result=None, entry_id=None):
    sidebar, ui, opened = Sidebar(entry_id), RecordingUi(list(answers)), []
    snap = SimpleNamespace(provides={})

    def dialog(current, snap, select, new, resolve, done):
        opened.append((list(current), select, new))
        done(dialog_result)
    cf = CustomFilters(sidebar, SimpleNamespace(), SimpleNamespace(), lambda: snap, ui, dialog)
    return cf, sidebar, ui, opened


def saved():
    return [f["name"] for f in json.loads(settings.get(SETTINGS_KEY, "[]"))]


def test_an_accepted_edit_is_saved_and_shown_a_cancelled_one_changes_nothing():
    cf, sidebar, _ui, opened = filters(dialog_result=None)
    cf.edit(select="Vim")
    assert opened == [([], "Vim", None)] and saved() == [] and sidebar.calls == []
    cf, sidebar, _ui, _opened = filters(dialog_result=([VIM], "Vim"))
    cf.edit()
    assert saved() == ["Vim"] and sidebar.custom == [VIM] and sidebar.calls == [("select", "custom", "custom:Vim")]
    cf.restore()
    assert sidebar.custom == [VIM]


@pytest.mark.feature(Feature.SIDEBAR_CUSTOM_FILTER_EDIT, front="qt")
def test_double_clicking_a_custom_filter_edits_it():
    cf, _sidebar, _ui, opened = filters()
    cf.activated(FilterEntry("status:all", "All", None))
    cf.activated(FilterEntry(PREFIX + "Vim", "Vim", None))
    assert [o[1] for o in opened] == ["Vim"]


def test_deleting_asks_first():
    cf, sidebar, ui, _opened = filters(answers=["no", "yes"])
    sidebar.custom = [VIM]
    cf.delete("Vim")
    assert sidebar.custom == [VIM] and "“Vim”" in ui.calls[0][1].text
    cf.delete("Vim")
    assert sidebar.custom == [] and sidebar.calls == [("view", "status")]


@pytest.mark.feature(Feature.DIALOG_CUSTOM_FILTERS_NEW_FROM_VIEW, front="qt")
def test_a_new_filter_from_a_search_is_named_after_it():
    cf, _sidebar, _ui, opened = filters(entry_id="status:all")
    cf.new_from_view(FilterEntry("status:all", "All", None), "vim", Mode.NAME)
    new = opened[0][2]
    assert new.name == "“vim”" and new.conditions == [Condition(Field.NAME, Op.CONTAINS, "vim")]


@pytest.mark.feature(Feature.SIDEBAR_CUSTOM_FILTER_MENU, front="qt")
def test_menu_items_only_for_custom_filters():
    cf, *_ = filters()
    assert cf.menu_items(FilterEntry("status:all", "All", None)) == []
    assert [i.label for i in cf.menu_items(FilterEntry(PREFIX + "Vim", "Vim", None))] == ["Edit Filter…",
                                                                                         "Delete Filter"]
