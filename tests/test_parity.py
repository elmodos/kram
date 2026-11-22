"""Feature parity between the Qt and GTK front ends (kram.app.parity): every feature is listed for both, a SUPPORTED
feature is proved by tests marked for that front end, nothing is NOT_IMPLEMENTED, and the rest says why.

The marks are read from the source with `ast`, not from a collected run: this works without any toolkit installed, so
the check is the same on a machine without GTK as in the container."""
import ast
from pathlib import Path

from kram.app.parity import FRONTS, FRONTS_RELEASED, Feature, Support

TESTS = Path(__file__).resolve().parent


def _mark(decorator: ast.expr) -> tuple[str, str] | None:
    """(feature name, front) of a `@pytest.mark.feature(Feature.X, front="…")` decorator, else None."""
    if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "feature"):
        return None
    if not decorator.args or not isinstance(decorator.args[0], ast.Attribute):
        raise AssertionError(f"line {decorator.lineno}: the first argument of feature() is Feature.<NAME>")
    front = next((k.value.value for k in decorator.keywords if k.arg == "front"), None)
    if not isinstance(front, str):
        raise AssertionError(f"line {decorator.lineno}: feature() needs front=\"qt\" or \"gtk\"")
    return decorator.args[0].attr, front


def proved_features() -> set[tuple[str, str]]:
    """Every (front, feature name) that a test function marks, read from all test files."""
    found = set()
    for path in sorted(TESTS.glob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text(), str(path))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in node.decorator_list:
                    if (mark := _mark(deco)) is not None:
                        found.add((mark[1], mark[0]))
    return found


def test_every_feature_is_listed_for_every_front_end():
    for front, table in FRONTS.items():
        assert set(table) == set(Feature), f"{front}: missing {sorted(f.value for f in set(Feature) - set(table))}, " \
                                           f"unknown {sorted(f.value for f in set(table) - set(Feature))}"


def test_a_released_front_end_has_no_planned_or_missing_feature():
    """Released front ends are complete: nothing PLANNED and nothing NOT_IMPLEMENTED (kram.app.parity)."""
    broken = [(front, f.value, e.support.name) for front in FRONTS_RELEASED for f, e in FRONTS[front].items()
              if e.support in (Support.PLANNED, Support.NOT_IMPLEMENTED)]
    assert not broken, f"released front ends with features still to do: {broken}"


def test_a_front_end_in_development_is_listed_as_planned_or_not_intended():
    """A front end not released yet may have PLANNED features, but each one is either planned or deliberately absent."""
    for front, table in FRONTS.items():
        if front in FRONTS_RELEASED:
            continue
        odd = [f.value for f, e in table.items() if e.support not in (Support.PLANNED, Support.NOT_INTENDED,
                                                                        Support.PARTIAL, Support.SUPPORTED)]
        assert not odd, f"{front}: {odd}"


def test_what_is_partial_or_not_intended_says_why():
    bare = [(front, f.value) for front, table in FRONTS.items() for f, e in table.items()
            if e.support in (Support.PARTIAL, Support.NOT_INTENDED) and not e.note.strip()]
    assert not bare, f"no note: {bare}"


def test_a_supported_feature_is_proved_by_a_marked_test():
    marked = proved_features()
    problems = []
    for front, table in FRONTS.items():
        for feature, entry in table.items():
            has_mark = (front, feature.name) in marked
            if entry.support is Support.SUPPORTED and not has_mark:
                problems.append(f"{front}: {feature.value} is SUPPORTED but no test is marked for it")
            if entry.support is not Support.SUPPORTED and has_mark:
                problems.append(f"{front}: {feature.value} is {entry.support.name} but a test proves it: "
                                "set SUPPORTED or drop the mark")
    assert not problems, "\n".join(problems)


def test_the_marks_name_known_features_and_fronts():
    unknown = [(front, name) for front, name in proved_features()
               if front not in FRONTS or name not in Feature.__members__]
    assert not unknown, f"marks that name no feature or front: {unknown}"
