"""About names the front end's toolkit and its version, so the two Kram packages can be told apart."""
import pytest

pytest.importorskip("PySide6.QtWidgets")


def test_the_qt_front_end_names_qt_and_pyside():
    from kram.qt.main_window import toolkit_versions
    text = toolkit_versions()
    assert text.startswith("Qt 6.") and ", PySide6 " in text
