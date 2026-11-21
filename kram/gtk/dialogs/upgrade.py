"""The header bar's "Fedora N" button for GTK (kram.app.upgrade): what moving to that release would do."""
import os

from gi.repository import Adw, Gtk

from ...app.icons import INFO, STATE_ICONS
from ...app.progress import Bar
from ...app.upgrade import Finding, UpgradeCheck, have_text, intro
from ...core import distro, proc
from ...core.model import CatalogSnapshot
from ...i18n import _
from .. import icons
from ..loop import post
from ..ui_port import GtkUi
from .common import Node, frame, standard_button, text_view, tree_model, wrapped

LOG_HEIGHT = 150


class UpgradeDialog(Adw.Dialog):
    """Kept by the main window for the session, so a finished check is not repeated when it is opened again."""

    def __init__(self, target: int, running: int, running_eol: str, snapshot: CatalogSnapshot, dnf):
        super().__init__(title=f"Fedora {target}", content_width=760, content_height=600)
        self.target = target
        self.ui = GtkUi(self)
        self.upgrade = UpgradeCheck(target, dnf, post, self)
        self._copr = Finding(INFO, _("COPR projects: checking…"))
        self._failed: Finding | None = None
        self._results: list[Finding] = []
        header, body = frame(self)
        self.close_button = standard_button("_Close")
        self.close_button.connect("clicked", lambda _b: self.close())
        header.pack_end(self.close_button)

        heading = Gtk.Label(label=_("Fedora {version} is available").format(version=target), xalign=0)
        heading.add_css_class("title-4")
        body.append(heading)
        info = wrapped()
        info.set_text(have_text(running, running_eol))
        body.append(info)

        panel = Gtk.Box(spacing=12)
        self.check = Gtk.Button(child=Adw.ButtonContent(label=_("Check"), icon_name="edit-find-symbolic"),
                                valign=Gtk.Align.START)
        self.check.add_css_class("suggested-action")  # the main action here
        self.check.connect("clicked", lambda _b: self.upgrade.start())
        self.cancel_button = standard_button("_Cancel")
        self.cancel_button.set_valign(Gtk.Align.START)
        self.cancel_button.connect("clicked", lambda _b: self.upgrade.cancel())
        self.cancel_button.set_visible(False)  # takes the place of Check while one runs
        group = Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)  # the text beside them does not jump
        for b in (self.check, self.cancel_button):
            group.add_widget(b)
            panel.append(b)
        self.status = wrapped()
        self.status.set_text(intro(target))
        self.status.set_hexpand(True)
        panel.append(self.status)
        body.append(panel)

        self.tree = Gtk.ListView(factory=self._factory(), vexpand=True)
        body.append(Gtk.ScrolledWindow(child=self.tree, vexpand=True))
        self.log_box, self.log = text_view(LOG_HEIGHT)
        self.log_box.set_visible(False)  # nothing to show before the first check
        body.append(self.log_box)
        self.busy = Gtk.ProgressBar(visible=False)
        body.append(self.busy)

        bottom = Gtk.Box(spacing=6)
        self.notes_button = self._link_button("help-about-symbolic", _("Release notes"),
                                              distro.RELEASE_NOTES_URL.format(version=target))
        self.guide_button = self._link_button("help-browser-symbolic", _("Upgrade guide"), distro.UPGRADE_GUIDE_URL)
        bottom.append(self.notes_button)
        bottom.append(self.guide_button)
        self.program = distro.upgrade_program(os.environ.get("XDG_CURRENT_DESKTOP", ""))
        self.open_program = None
        if self.program is not None:
            self.open_program = Gtk.Button(child=Adw.ButtonContent(
                label=_("Open {program}").format(program=self.program.name),
                icon_name=icons.first_themed((self.program.icon, "system-software-install")) or ""))
            self.open_program.connect("clicked", lambda _b: proc.spawn_detached(self.program.argv))
            bottom.append(self.open_program)
        body.append(bottom)
        self._show()
        self.upgrade.ask_copr(snapshot)

    def _link_button(self, icon: str, text: str, url: str) -> Gtk.Button:
        button = Gtk.Button(child=Adw.ButtonContent(label=text, icon_name=icon))
        button.connect("clicked", lambda _b: self.ui.open_web_link(url))
        return button

    @staticmethod
    def _factory() -> Gtk.SignalListItemFactory:
        factory = Gtk.SignalListItemFactory()

        def setup(_f, item: Gtk.ListItem) -> None:
            box = Gtk.Box(spacing=6)
            box.append(Gtk.Image())
            box.append(Gtk.Label(xalign=0, wrap=True, hexpand=True))
            item.set_child(Gtk.TreeExpander(child=box))
            item.set_activatable(False)

        def bind(_f, item: Gtk.ListItem) -> None:
            row: Gtk.TreeListRow = item.get_item()
            expander: Gtk.TreeExpander = item.get_child()
            expander.set_list_row(row)
            box = expander.get_child()
            image, label = box.get_first_child(), box.get_last_child()
            data = row.get_item().data
            if isinstance(data, Finding):
                icons.set_image(image, STATE_ICONS[data.kind])
                image.set_visible(True)
                label.set_text(data.title)
            else:
                image.set_visible(False)
                label.set_text(data)
        factory.connect("setup", setup)
        factory.connect("bind", bind)
        return factory

    def _show(self) -> None:
        findings = [self._copr, *([self._failed] if self._failed else []), *self._results]
        nodes = [Node(f, [Node(line) for line in f.lines]) for f in findings]
        self.tree.set_model(Gtk.NoSelection(model=tree_model(nodes, lambda n: n.data.expanded)))

    # ---------------------------------------------------------------- UpgradeView

    def show_copr(self, finding: Finding, failed: Finding | None) -> None:
        self._copr, self._failed = finding, failed
        self._show()

    def show_findings(self, findings: list[Finding]) -> None:
        self._results = list(findings)
        self._show()

    def show_status(self, text: str) -> None:
        self.status.set_text(text)

    def set_running(self, running: bool) -> None:
        self.check.set_visible(not running)
        self.close_button.set_sensitive(not running)
        self.set_can_close(not running)  # Escape too: a check is left with Cancel
        self.cancel_button.set_sensitive(running)
        self.cancel_button.set_visible(running)
        self.busy.set_visible(running)
        if running:
            self.log.get_buffer().set_text("")
            self.log_box.set_visible(True)

    def set_cancelling(self) -> None:
        self.cancel_button.set_sensitive(False)

    def show_progress(self, bar: Bar) -> None:
        if bar.maximum:
            self.busy.set_fraction(min(bar.value / bar.maximum, 1.0))
        else:
            self.busy.pulse()

    def append_log(self, line: str) -> None:
        buffer = self.log.get_buffer()
        buffer.insert(buffer.get_end_iter(), ("\n" if buffer.get_char_count() else "") + line)
        self.log.scroll_to_iter(buffer.get_end_iter(), 0, False, 0, 0)
