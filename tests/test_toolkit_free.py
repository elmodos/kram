"""`kram.core` and `kram.app` import no GUI toolkit, so that a second front end can use them without the first.

Every module is imported in a fresh interpreter in which PySide6 and gi cannot be imported: a toolkit import
anywhere in them, even an indirect one, fails the test.
"""
import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest

import kram.app
import kram.core

ROOT = Path(__file__).resolve().parent.parent
BLOCKED = ("PySide6", "gi", "shiboken6")

PROBE = """
import importlib, sys
for name in {blocked!r}:
    sys.modules[name] = None  # `import name` (and anything under it) raises ImportError now
failed = []
for module in sys.argv[1:]:
    try:
        importlib.import_module(module)
    except ImportError as e:
        failed.append(f"{{module}}: {{e}}")
print("\\n".join(failed))
sys.exit(1 if failed else 0)
"""


def modules(package) -> list[str]:
    return [package.__name__] + [f"{package.__name__}.{m.name}" for m in pkgutil.iter_modules(package.__path__)]


def import_without_toolkits(names: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", PROBE.format(blocked=BLOCKED), *names], cwd=ROOT,
                          capture_output=True, text=True)


@pytest.mark.parametrize("package", [kram.core, kram.app], ids=lambda p: p.__name__)
def test_imports_no_toolkit(package):
    result = import_without_toolkits(modules(package))
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_probe_catches_a_toolkit_import():
    """The probe itself works: a module that imports PySide6 is reported."""
    result = import_without_toolkits(["kram.qt.qt_loop"])
    assert result.returncode == 1 and "kram.qt.qt_loop" in result.stdout
