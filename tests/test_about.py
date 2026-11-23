"""About names the front end's toolkit and its version, so the two Kram packages can be told apart."""
import pytest

from kram.app.parity import Feature  # noqa: E402  (the feature marks of the parity tests)

pytest.importorskip("PySide6.QtWidgets")


@pytest.mark.feature(Feature.DIALOG_ABOUT_TOOLKIT, front="qt")
def test_the_qt_front_end_names_qt_and_pyside():
    from kram.qt.main_window import toolkit_versions
    text = toolkit_versions()
    assert text.startswith("Qt 6.") and ", PySide6 " in text


@pytest.mark.feature(Feature.DIALOG_WHATS_NEW_OVER_ABOUT, front="qt")
def test_whats_new_opens_over_about_which_stays_open():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication

    from kram.qt.about_dialog import AboutDialog
    from kram.qt.whats_new import WhatsNewDialog
    _app = QApplication.instance() or QApplication([])
    about = AboutDialog("<h3>Kram</h3>", QPixmap(), None)
    about.show()
    about.whats_new_btn.click()
    [notes] = about.findChildren(WhatsNewDialog)
    assert notes.isVisible() and about.isVisible() and notes.parent() is about
    notes.close()
    assert about.isVisible()
    about.close()
