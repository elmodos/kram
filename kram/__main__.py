import sys

from PySide6.QtWidgets import QApplication

from . import APP_ID, HOMEPAGE
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("kram")
    app.setApplicationDisplayName("Kram")
    app.setOrganizationDomain(HOMEPAGE.removeprefix("https://"))
    # Wayland app_id: lets Plasma match the window to the .desktop file and its icon
    app.setDesktopFileName(APP_ID)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
