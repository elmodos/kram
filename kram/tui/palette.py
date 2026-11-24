"""Every colour of the terminal front end, by role (docs/TUI_SPEC.md §9), and the colour schemes.

No colour is written anywhere else. Widgets' CSS uses theme variables; text drawn in Python asks `role(name)`, which
reads the style of that role from the hidden `Palette` widget, so a scheme change reaches it as soon as Textual has
applied the new CSS. Two rule sets: high-colour themes take Textual's theme variables as they are; 16-colour schemes
(Textual's `App:ansi`) use only what such a terminal has, its 16 colours, its own foreground and background, bold,
dim, reverse and underline: nothing blended with transparency, which shows there as a solid fill or not at all.

The rules live in `PALETTE_CSS`, which the app puts in its own CSS: a widget's DEFAULT_CSS is scoped to that widget,
and Textual prefixes a rule starting with `App:ansi` there with the widget's name, so it never matches.
"""
from rich.style import Style
from textual.strip import Strip
from textual.theme import Theme
from textual.widget import Widget

from ..app import preferences

ROLES = ("muted", "rule", "key", "current", "header", "cursor", "cursor-blurred", "upgradable", "installed", "ok",
         "marked", "info", "danger", "badge", "frame", "frame-focus", "tint-marked", "tint-danger")

PALETTE_CSS = """
Palette > .role--muted { color: $text-muted; }
Palette > .role--rule { color: $border-blurred; }
Palette > .role--key { color: $accent; text-style: bold; }
Palette > .role--current { text-style: reverse bold; }
Palette > .role--header { color: $text-muted; text-style: bold; }
Palette > .role--cursor { background: $block-cursor-background; color: $block-cursor-foreground;
                          text-style: $block-cursor-text-style; }
Palette > .role--cursor-blurred { background: $block-cursor-blurred-background;
                                  color: $block-cursor-blurred-foreground; }
Palette > .role--upgradable { color: $warning; }
Palette > .role--installed { color: $success; }
Palette > .role--ok { color: $success; }
Palette > .role--marked { color: $accent; text-style: bold; }
Palette > .role--info { color: $primary; text-style: bold; }
Palette > .role--danger { color: $error; text-style: bold; }
Palette > .role--badge { color: $error; text-style: reverse bold; }
/* the theme's own border colour vanishes on dark themes: the text's colour, faint */
Palette > .role--frame { color: $foreground 30%; }
Palette > .role--frame-focus { color: $accent; }
/* a marked row's background in high colour (§7.3.5): the mark's colour, blended with the background by the theme
   itself (a colour with transparency would come out solid here). 16 colours have no tint: the glyph and the name
   take the mark's colour instead, which the list does without these roles */
Palette > .role--tint-marked { background: $accent-muted; }
Palette > .role--tint-danger { background: $error-muted; }

App:ansi Palette > .role--muted { color: $foreground; text-style: dim; }
App:ansi Palette > .role--key { color: $warning; text-style: bold; }
App:ansi Palette > .role--header { color: $foreground; text-style: bold dim; }
App:ansi Palette > .role--cursor { background: $background; color: $foreground; text-style: reverse bold; }
App:ansi Palette > .role--cursor-blurred { background: $background; color: $foreground; text-style: underline; }
App:ansi Palette > .role--frame { color: $border-blurred; }
"""


class Palette(Widget):
    """Holds the roles as component classes; never shown. The app has exactly one."""

    COMPONENT_CLASSES = {f"role--{r}" for r in ROLES}
    DEFAULT_CSS = "Palette { display: none; }"

    def on_mount(self) -> None:
        global _palette
        _palette = self

    def on_unmount(self) -> None:
        global _palette
        if _palette is self:
            _palette = None


_palette: Palette | None = None


def role(name: str) -> Style:
    """The text style of a colour role in the current scheme; plain until the palette is mounted and styled. With
    NO_COLOR only the role's bold, dim, reverse and underline are left (§9.6)."""
    if name not in ROLES:
        raise KeyError(name)
    palette = _palette
    if palette is None:
        return Style()
    try:
        style = palette.get_component_rich_style(f"role--{name}", partial=True)
    except KeyError:  # not styled yet
        return Style()
    if not palette.app.ansi_color:
        style = _blended(palette, name, style)
    else:
        style = _without_default(style)
    return style.without_color if palette.app.no_color else style


def filled(widget: Widget, strip: Strip) -> Strip:
    """A line drawn in Python (`render_line`) on the widget's own background. Textual does not lay it under such
    lines: a segment without a background shows the terminal's default one, black on most terminals, whatever the
    scheme (only a translucent modal screen on top covered it up). The terminal's own background ("default", the
    Terminal scheme) is left unset: it is what shows anyway."""
    bgcolor = widget.rich_style.bgcolor
    if bgcolor is None or bgcolor.is_default:
        return strip
    return strip.apply_style(Style(bgcolor=bgcolor))


def _without_default(style: Style) -> Style:
    """The terminal's own colour ("default") left unset: Textual turns an explicit default colour that is dim into
    #000000, black on a dark terminal (found on a real terminal: the top line's counts vanished); unset, the
    terminal draws dim text in its own colour."""
    color = None if style.color is not None and style.color.is_default else style.color
    bgcolor = None if style.bgcolor is not None and style.bgcolor.is_default else style.bgcolor
    if color is style.color and bgcolor is style.bgcolor:
        return style
    return Style(color=color, bgcolor=bgcolor, bold=style.bold, dim=style.dim, italic=style.italic,
                 underline=style.underline, reverse=style.reverse, strike=style.strike, link=style.link,
                 meta=style._meta and style.meta or None)


_blends: dict[tuple[str, str, Style], Style] = {}  # by the scheme, the role and its rich style


def _blended(palette: Palette, name: str, style: Style) -> Style:
    """A role's colour with transparency ("$primary 30%", the blurred cursor of most themes) laid over the window's
    background, as Textual does for its own widgets: the rich style alone drops the transparency, and the blurred
    cursor came out as bright as the focused one."""
    key = (palette.app.theme, name, style)
    found = _blends.get(key)
    if found is not None:
        return found
    if len(_blends) > 512:  # old schemes' entries
        _blends.clear()
    styles = palette.get_component_styles(f"role--{name}")
    back = palette.screen.styles.background
    color, bgcolor = styles.color, styles.background
    blended = style
    if style.bgcolor is not None and 0 < bgcolor.a < 1:
        blended += Style(bgcolor=(back + bgcolor).rich_color)
    if style.color is not None and 0 < color.a < 1:
        blended += Style(color=(back + color).rich_color)
    _blends[key] = blended
    return blended


# 16-colour schemes of our own: only the terminal's 16 colours, by their ANSI names
ANSI_THEMES = (
    Theme(name="kram-midnight", primary="ansi_bright_cyan", secondary="ansi_bright_cyan", accent="ansi_bright_yellow",
          warning="ansi_bright_yellow", error="ansi_bright_red", success="ansi_bright_green",
          foreground="ansi_bright_white", background="ansi_blue", surface="ansi_blue", panel="ansi_blue",
          boost="ansi_blue", dark=True,
          variables={"border": "ansi_bright_cyan", "border-blurred": "ansi_white", "scrollbar": "ansi_cyan",
                     "footer-background": "ansi_cyan", "footer-foreground": "ansi_black",
                     "footer-key-foreground": "ansi_bright_white", "input-cursor-text-style": "reverse"}),
    Theme(name="kram-console", primary="ansi_green", secondary="ansi_cyan", accent="ansi_bright_green",
          warning="ansi_yellow", error="ansi_red", success="ansi_green", foreground="ansi_white",
          background="ansi_black", surface="ansi_black", panel="ansi_black", boost="ansi_black", dark=True,
          variables={"border": "ansi_bright_green", "border-blurred": "ansi_bright_black", "scrollbar": "ansi_green",
                     "input-cursor-text-style": "reverse"}),
)
ANSI_SCHEMES = preferences.TUI_ANSI_SCHEMES
DEFAULT_SCHEME = preferences.TUI_SCHEME_DEFAULT


def schemes() -> tuple[tuple[str, str], ...]:
    """(theme name, label) of every scheme Settings → Colours offers, in its order."""
    return preferences.pref(preferences.TUI_SCHEME).choices


def is_ansi(scheme: str) -> bool:
    return scheme in ANSI_SCHEMES
