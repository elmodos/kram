"""kram.app.apply_review without a toolkit: the review's texts, the recommendations and the request it gives back."""
import pytest

from kram.app.apply_review import ApplyReview, change_sections, size_line
from kram.app.doc import Bold
from kram.app.parity import Feature
from kram.core.model import PreviewItem, Recommendation, TransactionPreview


class View:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, *args))

    def last(self, name):
        return next(c for c in reversed(self.calls) if c[0] == name)


def preview(with_kvm=True):
    items = [PreviewItem("install", "virt-manager", "noarch", "5.1-1", "", "fedora", 700, 2000, "user")]
    if with_kvm:
        items.append(PreviewItem("install", "kvm", "x86_64", "1-1", "", "fedora", 50, 9000, "weak"))
    recs = [Recommendation("kvm", ["virt-manager"], True, ["kvm"] if with_kvm else [], ["kvm"], size=9000, count=1,
                           exact=True)]
    return TransactionPreview(items, [], 100, 11000, recs)


def test_sections_and_the_size_line():
    sections = change_sections(preview(), "x86_64")
    assert [s.title for s in sections] == ["To be installed (1)", "To be installed as dependencies (1)"]
    assert sections[0].rows[0].name == "virt-manager" and sections[0].rows[0].version == "5.1-1"
    line = size_line(preview())
    assert line[0] == "To download: " and isinstance(line[1], Bold)


@pytest.mark.feature(Feature.DIALOG_APPLY_RECOMMENDATIONS, front="qt")
def test_unchecking_a_recommendation_resolves_again_and_a_late_answer_is_dropped():
    view, waiting = View(), []
    review = ApplyReview(preview(), {"op": "transaction"}, "x86_64", view,
                         resolve=lambda req, done, failed: waiting.append((req, done, failed)))
    review.start()
    assert view.last("set_can_apply") == ("set_can_apply", True)
    rec = preview().recommendations[0]
    review.recs.set_checked(rec, False)
    review.recs_changed()
    assert waiting[0][0] == {"op": "transaction", "exclude_weak": ["kvm"]}
    assert view.last("set_can_apply") == ("set_can_apply", False) and view.last("set_resolving")[1] is True
    review.recs.set_checked(rec, True)
    review.recs_changed()  # a newer one: the first answer is stale
    waiting[0][1](preview(False))
    assert view.last("set_resolving")[1] is True
    waiting[1][1](preview())
    assert view.last("set_resolving") == ("set_resolving", False) and view.last("set_can_apply")[1] is True
    review.close()
    waiting[1][2](RuntimeError("late"))
    assert view.last("set_resolving") == ("set_resolving", False)


@pytest.mark.feature(Feature.DIALOG_APPLY_COMMAND, front="qt")
@pytest.mark.feature(Feature.DIALOG_APPLY_DOWNLOAD_ONLY, front="qt")
def test_download_only_is_in_the_command_and_the_result():
    view = View()
    review = ApplyReview(preview(), {"op": "transaction", "install": ["virt-manager.noarch"]}, "x86_64", view)
    review.start()
    assert "--downloadonly" not in view.last("show_command")[1]
    review.set_download_only(True)
    assert "--downloadonly" in view.last("show_command")[1] and review.result()["download_only"] is True
