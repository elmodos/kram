import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTranslator, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_ID, HOMEPAGE, __version__
from .i18n import language


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("kram")
    app.setApplicationDisplayName("Kram")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("kram")  # QSettings -> ~/.config/kram/kram.conf
    app.setOrganizationDomain(HOMEPAGE.removeprefix("https://"))
    # Wayland app_id: lets Plasma match the window to the .desktop file and its icon
    app.setDesktopFileName(APP_ID)
    # installed: the hicolor theme icon; source checkout: the SVG next to the package
    source_icon = Path(__file__).resolve().parent.parent / "data" / f"{APP_ID}.svg"
    app.setWindowIcon(QIcon.fromTheme(APP_ID, QIcon(str(source_icon))))
    # Qt's own strings (standard buttons like Yes/No/Close/Cancel) in the same language as ours
    qt_translator = QTranslator(app)
    if (lang := language()) and qt_translator.load(f"qtbase_{lang}", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(qt_translator)
    # `kram file.rpm` (file managers: "Open with Kram"): only the installer, no main window
    files = [a for a in app.arguments()[1:] if not a.startswith("-")]
    if files:
        return install_file(files[0])
    from .ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    return app.exec()


def install_file(arg: str) -> int:
    from .core.catalog import Catalog
    from .ipc.client import HelperClient
    from .ui.dnf_thread import DnfThread
    from .ui.install_dialog import InstallDialog

    path = QUrl(arg).toLocalFile() if arg.startswith("file:") else arg
    dnf, helper = DnfThread(), HelperClient()
    dialog = InstallDialog(path, Catalog(), dnf, helper, load_catalog=True)
    try:
        dialog.exec()
    finally:
        helper.stop()
        dnf.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
