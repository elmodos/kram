import gc
import os

import pytest

# kram.i18n picks the language at import time; tests compare English source strings
os.environ["LANGUAGE"] = "en"


@pytest.fixture(autouse=True)
def _settings_file(tmp_path_factory, monkeypatch):
    """kram.core.settings writes to a kram.conf of the test's own, never the user's."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("config")))


@pytest.fixture(scope="module", autouse=True)
def _collect_garbage():
    """Let the garbage collector free the Qt windows and dialogs a module's tests left behind, at the module's end.

    Collected whenever the collector happens to run, in the middle of a later test, they crash PySide6 6.12
    (seen in the COPR rawhide builds).
    """
    yield
    gc.collect()


def pytest_configure(config):
    config.addinivalue_line("markers", 'feature(feature, front): this test proves the feature for the "qt" or "gtk" '
                                       "front end (kram.app.parity)")


def pytest_sessionfinish(session, exitstatus):
    """Delete the Qt windows and dialogs the tests left behind before the interpreter exits.

    Tests create dialogs without a parent; left to PySide6's own cleanup at exit, PySide6 6.12 with Python 3.15
    deletes them in the wrong order and segfaults after a passing run (the COPR rawhide build of 0.12.0).
    """
    import sys
    if "PySide6.QtWidgets" not in sys.modules:
        return
    import shiboken6
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    # only the windows without a parent: a dialog with one is a top-level widget too, and goes with its parent
    for widget in [w for w in app.topLevelWidgets() if w.parentWidget() is None]:
        if shiboken6.isValid(widget):
            shiboken6.delete(widget)
    gc.collect()
