import gc
import os

import pytest

# kram.i18n picks the language at import time; tests compare English source strings
os.environ["LANGUAGE"] = "en"


@pytest.fixture(scope="module", autouse=True)
def _collect_garbage():
    """Let the garbage collector free the Qt windows and dialogs a module's tests left behind, at the module's end.

    Collected whenever the collector happens to run, in the middle of a later test, they crash PySide6 6.12
    (seen in the COPR rawhide builds).
    """
    yield
    gc.collect()
