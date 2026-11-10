"""What the apply dialog warns about, and how an installonly rotation (old kernels) is told from a real removal."""
import os

import pytest

from kram.core.model import PreviewItem, TransactionPreview, mark_rotated

pytest.importorskip("PySide6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kram.ui.apply_dialog import GROUPS, removal_warning


def item(action, name, arch="x86_64", evr="1-1", reason="user"):
    return PreviewItem(action, name, arch, evr, "", "updates", 1, 1, reason)


def preview(*items):
    items = list(items)
    mark_rotated(items)
    return TransactionPreview(items, [], 0, 0)


def test_the_oldest_kernel_going_next_to_a_new_one_is_housekeeping():
    p = preview(item("install", "kernel-core", evr="7.3.3-200"), item("remove", "kernel-core", evr="7.2.11-200"),
                item("install", "kernel", evr="7.3.3-200"), item("remove", "kernel", evr="7.2.11-200"))
    assert [i.rotated for i in p.items] == [False, True, False, True]
    assert removal_warning(p) == ""


def test_a_real_removal_of_an_essential_package_still_warns():
    assert "kernel-core" in removal_warning(preview(item("remove", "kernel-core")))
    assert "systemd" in removal_warning(preview(item("remove", "systemd"), item("install", "kernel-core")))


def test_another_architecture_of_an_arriving_package_does_not_count_as_a_rotation():
    p = preview(item("install", "glibc", arch="x86_64"), item("remove", "glibc", arch="i686"))
    assert not any(i.rotated for i in p.items)
    assert "glibc" in removal_warning(p)


def test_an_upgrade_alone_does_not_make_a_removal():
    p = preview(item("upgrade", "bash"), item("remove", "bash-completion", arch="noarch"))
    assert not any(i.rotated for i in p.items)


def test_rotation_is_not_counted_among_the_many_removals():
    items = [item("remove", f"p{n}") for n in range(15)]
    items += [x for n in range(10) for x in (item("install", f"k{n}"), item("remove", f"k{n}"))]
    assert removal_warning(preview(*items)) == ""  # 15 real removals, below the threshold of 20
    more = removal_warning(preview(*items, *[item("remove", f"q{n}") for n in range(5)]))
    assert "20 packages will be removed" in more


def test_the_tree_groups_a_rotation_apart():
    p = preview(item("install", "kernel-core"), item("remove", "kernel-core"), item("remove", "tool"))
    groups = {title: [i.name for i in p.items if pred(i)] for title, _color, pred in GROUPS}
    assert groups["Oldest kernels removed to stay within the limit of kept versions"] == ["kernel-core"]
    assert groups["To be removed"] == ["tool"]
    assert sum(len(v) for v in groups.values()) == 3  # every item is in exactly one group


def test_the_name_column_keeps_its_width_when_versions_are_long():
    from PySide6.QtWidgets import QApplication

    from kram.ui.apply_dialog import ChangesTree

    app = QApplication.instance() or QApplication([])
    long_old, long_new = "32:9.18.51^git20261003.d0a87358-2.fc44", "32:9.18.51^git20261102.973d8646-3.fc44"
    items = [PreviewItem("upgrade", "bind-utils", "x86_64", long_new, long_old, "updates", 1, 1, "user"),
             PreviewItem("upgrade", "kernel-modules-core", "x86_64", "7.3.3-200.fc44", "7.2.4-200.fc44", "updates",
                         1, 1, "user"),
             item("install", "tool", evr="1-1")]
    tree = ChangesTree()
    tree.fill(preview(*items))
    tree.resize(560, 300)  # narrower than the long versions need
    tree.show()
    for _ in range(5):
        app.processEvents()
    longest = max(tree.fontMetrics().horizontalAdvance(n) for n in ("bind-utils", "kernel-modules-core"))
    assert tree.columnWidth(0) >= longest  # the whole name, not "ke…"
    assert tree.columnWidth(0) < 300  # and not a group title's width either
    version = tree.columnWidth(1)
    assert version < tree.fontMetrics().horizontalAdvance(f"{long_old} → {long_new}")  # this one gave way
    upgrades = next(tree.topLevelItem(i) for i in range(tree.topLevelItemCount())
                    if tree.topLevelItem(i).child(0).text(0) == "bind-utils")
    assert upgrades.child(0).toolTip(1) == f"{long_old} → {long_new}"  # and is complete in the tooltip
    assert all(tree.isFirstColumnSpanned(i, tree.rootIndex()) for i in range(tree.topLevelItemCount()))
