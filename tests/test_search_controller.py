"""kram.app.search without a toolkit: debounce, history, quiet changes; and the Scheduler fake it runs on."""
from kram.app.scheduler import FakeScheduler
from kram.app.search import DEBOUNCE_MS, HISTORY_IDLE_MS, SearchController
from kram.core.search import Mode


def controller():
    scheduler = FakeScheduler()
    c = SearchController(scheduler)
    events = []
    for name in ("changed", "submitted", "settled"):
        getattr(c, name).connect(lambda name=name: events.append(name))
    c.shown.connect(lambda text, mode: events.append(("shown", text, mode)))
    return c, scheduler, events


def test_typing_searches_once_it_pauses():
    c, scheduler, events = controller()
    c.edited("v")
    scheduler.advance(DEBOUNCE_MS - 1)
    c.edited("vi ")  # pushes the search back
    scheduler.advance(DEBOUNCE_MS - 1)
    assert events == []
    scheduler.advance(1)
    assert events == ["changed"] and c.text() == "vi" and c.filtering


def test_a_search_running_now_drops_the_pending_one():
    c, scheduler, events = controller()
    c.edited("vim")
    c.cancel_pending()
    scheduler.advance(1000)
    assert events == []


def test_the_history_waits_for_the_results_to_rest():
    c, scheduler, events = controller()
    c.start_history()
    scheduler.advance(HISTORY_IDLE_MS - 1)
    c.stop_history()
    scheduler.advance(HISTORY_IDLE_MS)
    assert events == []
    c.start_history()
    scheduler.advance(HISTORY_IDLE_MS)
    assert events == ["settled"]


def test_quiet_and_loud_changes():
    c, scheduler, events = controller()
    c.set_query("fish", Mode.PROVIDES)
    assert events == [("shown", "fish", Mode.PROVIDES)] and c.mode() is Mode.PROVIDES
    c.clear(quietly=True)
    scheduler.advance(1000)
    assert events[-1] == ("shown", "", Mode.PROVIDES) and "changed" not in events
    c.clear()
    scheduler.advance(DEBOUNCE_MS)
    assert events[-1] == "changed"
    events.clear()
    c.set_mode(Mode.PROVIDES)  # the same: nothing
    c.mode_chosen(Mode.PROVIDES)
    assert events == []
    c.set_mode(Mode.FILE)
    assert events == [("shown", "", Mode.FILE), "changed"]
    c.mode_chosen(Mode.NAME)
    c.submit()
    assert events[-2:] == ["changed", "submitted"]


def test_fake_scheduler_runs_idle_calls_and_due_timers_in_order():
    scheduler = FakeScheduler()
    order = []
    late, early = scheduler.timer(20, lambda: order.append("late")), scheduler.timer(10, lambda: order.append("early"))
    late.start()
    early.start()
    scheduler.later(lambda: order.append("idle"))
    scheduler.advance(30)
    scheduler.run_idle()
    assert order == ["early", "late", "idle"] and not late.active
