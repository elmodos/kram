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
