"""About Kram (docs/TUI_SPEC.md §10.13): the version, the toolkit it runs on (`DIALOG_ABOUT_TOOLKIT`), so that a bug
report says which front end it is about, the homepage as a link, and What's New (§10.14) over it.
"""
import textual
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Static

from ... import HOMEPAGE, __version__
from ...app.whats_new import whats_new_doc
from ...core import releases
from ...core.releases import Release
from ...i18n import _
from ..palette import role
from ..widgets import Button, hint
from .install import DocBlock


def toolkit_version() -> str:
    """The toolkit this front end runs on, as About names it."""
    return _("Terminal front end, Textual {version}").format(version=textual.__version__)


class LinkLine(Widget, can_focus=True):
    """A web address on a line of its own: Enter or a click opens it (copies it without a desktop, as the Ui port
    does). It is also an OSC 8 hyperlink, which terminals that know them make clickable themselves."""

    BINDINGS = [Binding("enter,space", "open", show=False)]
    DEFAULT_CSS = """
    LinkLine { width: auto; height: 1; background: transparent; }
    LinkLine:focus { text-style: reverse; }
    """

    def __init__(self, url: str, ui, **kw):
        super().__init__(**kw)
        self.url, self.ui = url, ui

    def render(self) -> Text:
        return Text(self.url, role("info") + Style(underline=True, link=self.url))

    def action_open(self) -> None:
        self.ui.open_web_link(self.url)

    def on_click(self) -> None:
        self.action_open()


class AboutDialog(ModalScreen):
    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("left", "app.focus_previous", show=False),
        Binding("right", "app.focus_next", show=False),
    ]

    def __init__(self, ui):
        super().__init__()
        self.ui = ui

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog about")
        box.border_title = _("About Kram")
        box.border_subtitle = hint(("tab", _("next")), ("enter", _("choose")), ("esc", _("close")))
        with box:
            yield Static(Text(f"Kram {__version__}", "bold"), id="about-version")
            yield Static(toolkit_version(), id="about-toolkit", markup=False)
            yield Static(_("A Synaptic-style package manager for Fedora."), classes="gap", markup=False)
            yield LinkLine(HOMEPAGE, self.ui, id="about-homepage")
            yield Static("Copyright © 2026 Modo Ltunzher", classes="gap note", markup=False)
            yield Static(_("Released under the MIT License."), classes="note", markup=False)
            with Horizontal(classes="buttons"):
                yield Button(_("What's New"), id="whats-new")
                yield Button(_("Close"), id="close", classes="-primary")

    def on_mount(self) -> None:
        self.query_one("#close", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "whats-new":
            self.app.push_screen(WhatsNewDialog())  # over About, which stays under it (DIALOG_WHATS_NEW_OVER_ABOUT)
        else:
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class WhatsNewDialog(ModalScreen):
    """What's New (§10.14): the release notes of the metainfo (kram.core.releases), newest first, as the document
    of kram.app.whats_new, scrolling."""

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("pageup", "page(-1)", show=False),
        Binding("pagedown", "page(1)", show=False),
    ]
    DEFAULT_CSS = """
    WhatsNewDialog { align: center middle; }
    WhatsNewDialog #whats-new-box { height: 90%; }
    WhatsNewDialog #whats-new-scroll { height: 1fr; margin-top: 1; background: $surface; }
    App:ansi WhatsNewDialog #whats-new-scroll { background: $background; }
    """

    def __init__(self, notes: list[Release] | None = None):
        super().__init__()
        self.notes = releases.load() if notes is None else notes

    def compose(self) -> ComposeResult:
        box = Vertical(classes="window dialog whats-new", id="whats-new-box")
        box.border_title = _("What's New")
        g = self.app.glyphs
        box.border_subtitle = hint((f"{g.up} {g.down}", _("scroll")), ("esc", _("close")))
        with box:
            with VerticalScroll(id="whats-new-scroll"):
                yield DocBlock(id="whats-new")
            with Horizontal(classes="buttons"):
                yield Button(_("Close"), id="close", variant="primary")

    def on_mount(self) -> None:
        self.query_one(DocBlock).show(whats_new_doc(self.notes))
        self.query_one("#whats-new-scroll").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_close()

    def action_page(self, step: int) -> None:
        scroll = self.query_one("#whats-new-scroll", VerticalScroll)
        scroll.scroll_to(y=scroll.scroll_y + step * max(1, scroll.size.height - 1), animate=False)

    def action_close(self) -> None:
        self.dismiss(None)
