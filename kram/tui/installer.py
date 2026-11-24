"""`kram-tui FILE.rpm` (docs/TUI_SPEC.md §15.2): the Install package file dialog alone, as the GUIs' `kram file.rpm`
runs their installer without the main window (kram.gtk.app.InstallApplication).

The app is the terminal front end's frame (the top line, the colours, the small-terminal screen, the footer) with no
main window under the dialog: no package list, no sidebar, no catalog of its own. The dialog loads the catalog it
needs itself (`load_catalog`), and has a helper client of its own that gets root as the window's does
(kram.tui.root). Kram ends when the dialog closes, installed or not; quitting while the installation runs is refused,
as in the window.
"""
from collections.abc import Callable

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding

from ..app.progress import BUSY
from ..core.catalog import Catalog
from ..core.worker import DnfWorker
from ..i18n import _
from . import loop
from .app import Body, KramApp, TooSmall, TopLine
from .dialogs.install import InstallDialog
from .dialogs.progress import ProgressDialog
from .palette import Palette
from .root import RootAccess, TuiHelperClient, is_root
from .widgets import KeyFooter


class InstallerApp(KramApp, inherit_bindings=False):
    """`path`: the package file. `changed_system` afterwards: an installation ran."""

    # Textual's own ctrl+c says how to quit; the window's keys have no window here
    BINDINGS = [Binding("ctrl+c", "help_quit", show=False, system=True)]

    def __init__(self, path: str):
        super().__init__(file=path)
        self.changed_system = False
        self.dialog: InstallDialog | None = None
        self.dnf: DnfWorker | None = None
        self.helper: TuiHelperClient | None = None
        self.root: RootAccess | None = None

    def make_main(self):
        return None

    def compose(self) -> ComposeResult:
        yield Palette()
        yield TopLine(id="top")
        yield Body(id="body")  # its resize tells of a terminal too small (§5.3)
        yield KeyFooter()

    def on_mount(self, event: events.Mount) -> None:
        event.prevent_default()  # KramApp's on_mount starts the main window, which is not here
        loop.attach(self)
        self.theme_changed_signal.subscribe(self, self._theme_changed)
        self.set_scheme(self._scheme, save=False)
        self.top_line.set_root(is_root())
        self.dnf = DnfWorker(loop.post)
        self.root = RootAccess(self, self.ui)
        self.helper = TuiHelperClient(loop.post, self.root)
        self.dialog = InstallDialog(self.file, self.make_catalog(), self.dnf, busy=lambda: self.helper.busy,
                                    run=self.run_request, load_catalog=True)
        self.push_screen(self.dialog, self._dialog_closed)
        self.apply_layout()

    @staticmethod
    def make_catalog():
        return Catalog()

    def run_request(self, request: dict, title: str, done: Callable[[bool], None]) -> None:
        """The installation with its progress dialog, shown by the root flow (MainWindow.run_helper)."""
        dialog = ProgressDialog(self.helper, request, title, lambda ok, _result: done(ok), self.ui, self.root)
        if not dialog.start():
            self.ui.warn(title, _(BUSY))
            done(False)
            return
        self.root.present(dialog)

    def _dialog_closed(self, changed: bool | None) -> None:
        self.changed_system = bool(changed)
        self.shutdown()
        self.exit()

    def shutdown(self) -> None:
        if self.helper is not None:
            self.helper.stop()
        if self.dnf is not None:
            self.dnf.shutdown()

    def apply_layout(self) -> None:
        """Only the small-terminal screen (§5.3): there are no panels to lay out."""
        too_small = self.is_too_small()
        if isinstance(self.screen, TooSmall):
            if not too_small:
                self.pop_screen()
        elif too_small:
            self.push_screen(TooSmall())

    def request_quit(self) -> None:
        """`q` on the small-terminal screen: not while the installation runs."""
        if self.helper is not None and self.helper.busy:
            self.show_status(_(BUSY), 4000)
            return
        if self.dialog is not None:
            self.dialog.logic.close()
        self.shutdown()
        self.exit()
