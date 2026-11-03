import sys

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtWidgets import QApplication

from . import APP_ID, HOMEPAGE
from .i18n import language
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("kram")
    app.setApplicationDisplayName("Kram")
    app.setOrganizationName("kram")  # QSettings -> ~/.config/kram/kram.conf
    app.setOrganizationDomain(HOMEPAGE.removeprefix("https://"))
    # Wayland app_id: lets Plasma match the window to the .desktop file and its icon
    app.setDesktopFileName(APP_ID)
    # Qt's own strings (standard buttons like Yes/No/Close/Cancel) in the same language as ours
    qt_translator = QTranslator(app)
    if (lang := language()) and qt_translator.load(f"qtbase_{lang}", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(qt_translator)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
