"""Render the README / metainfo screenshots from the real UI with this machine's catalog.

    QT_QPA_PLATFORM=offscreen LANGUAGE=en python3 scripts/screenshots.py docs/screenshots

Nothing is changed on the system: no helper is started. The COPR shot searches the Copr API (slow).
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from kram.core.marks import Action
from kram.ui.copr_dialog import CoprDialog
from kram.ui.main_window import MainWindow

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
SIZE = (1400, 850)


def pump(ms: int = 300) -> None:
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        QCoreApplication.processEvents()


def shoot(app: QApplication, w: MainWindow) -> None:
    if not w.snapshot:
        QTimer.singleShot(100, lambda: shoot(app, w))
        return
    pump()
    # a few marks so the status column and the status bar show something
    rows = {r.key: r for r in w.snapshot.rows}
    for key, action in ((("fish", "x86_64"), Action.INSTALL), (("fio", "x86_64"), Action.INSTALL)):
        if key in rows:
            w.model.marks.set(rows[key], action)
    if w.snapshot.n_upgradable:
        w.mark_all_upgrades()
    w._marks_changed(None)
    w.sidebar.select("status", "status:all")
    pump(500)
    w._select_key(("fio", "x86_64"))
    pump(1500)  # Breeze animates enabled/disabled transitions
    w.grab().save(str(OUT / "main.png"))

    w.sidebar.select("status", "status:all")
    w.search.setText("terminal emulator")
    w.search_mode.setCurrentIndex(1)  # name and summary
    w._on_search_enter()
    pump(800)
    w.table.setCurrentIndex(w.model.index(0, 0))
    pump()
    w.grab().save(str(OUT / "search.png"))

    c = CoprDialog(lambda _req, _title: False, w)
    c.set_catalog(w.snapshot, w.catalog.repo_package_counts())
    c.resize(1100, 700)
    c.show()
    c.query.setText("hyprland")
    c._search()
    for _ in range(900):
        if c._reply is None:
            break
        pump(100)
    pump()
    c.grab().save(str(OUT / "copr.png"))
    c.close()
    w.model.marks.clear()
    app.quit()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, tempfile.mkdtemp())  # not the user's settings
    app = QApplication(sys.argv)
    app.setStyle("Breeze")
    app.setOrganizationName("kram")
    app.setApplicationName("kram")
    w = MainWindow()
    w.resize(*SIZE)
    w.show()
    QTimer.singleShot(0, lambda: shoot(app, w))
    app.exec()


if __name__ == "__main__":
    main()
