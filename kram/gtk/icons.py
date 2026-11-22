"""Small painted status/origin icons for GTK, the same shapes and colours as kram.qt.icons; the theme icons of comps
groups and the other ("theme", names) references.

The vectors are drawn with cairo in a 16×16 grid, as a cairo node of each snapshot: GTK rasterizes them at the
screen's own resolution, so they stay sharp at fractional scales (125 %). A texture drawn for an integer scale and
resampled was stretched and pixelated there. One paintable per IconRef, shared by every image that shows it.
"""
import colorsys
import math
from collections.abc import Callable
from functools import cache

import cairo
from gi.repository import Gdk, GObject, Graphene, Gtk, Pango, PangoCairo

from ..app.icons import ADVISORY_COLOR, ORIGIN_STYLE, IconRef, group_icon_names
from ..core.marks import Action
from ..core.model import Origin, Status

GRID = 16  # every icon is drawn in a 16×16 coordinate space
_BOX = (1.5, 1.5, 13, 13)    # where glyphs inside the box are centred
_BOX_OUTER = (1, 1, 14, 14)  # the box including its 1 px border
WHITE = "#ffffff"

Draw = Callable[[cairo.Context], None]


def rgb(color: str) -> tuple[float, float, float]:
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    return tuple(int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))


def darker(color: str, factor: int = 150) -> tuple[float, float, float]:
    """QColor.darker: the value (HSV) divided by factor / 100."""
    h, s, v = colorsys.rgb_to_hsv(*rgb(color))
    return colorsys.hsv_to_rgb(h, s, v * 100 / factor)


def _source(cr: cairo.Context, color) -> None:
    cr.set_source_rgb(*(rgb(color) if isinstance(color, str) else color))


def _box(cr: cairo.Context, border: str, fill: str) -> None:
    """The status/mark box, snapped to whole device pixels with a whole-pixel border, as Qt's: at 125 % or 150 % a
    scaled 1 px border lands between pixels and smears over two."""
    # GTK's cairo nodes carry the whole transform (screen scale and position) in the CTM, and a plain image
    # surface may carry the scale as its device scale: snap in device pixels, then map back to user space
    ds = cr.get_target().get_device_scale()[0]
    x0, y0 = cr.user_to_device(_BOX_OUTER[0], _BOX_OUTER[1])
    x1, y1 = cr.user_to_device(_BOX_OUTER[0] + _BOX_OUTER[2], _BOX_OUTER[1] + _BOX_OUTER[3])
    left, top, right, bottom = (round(v * ds) / ds for v in (x0, y0, x1, y1))
    pen = max(1, round(cr.get_matrix().xx * ds)) / ds
    half = pen / 2
    ux0, uy0 = cr.device_to_user(left + half, top + half)
    ux1, uy1 = cr.device_to_user(right - half, bottom - half)
    cr.rectangle(ux0, uy0, ux1 - ux0, uy1 - uy0)
    _source(cr, fill)
    cr.fill_preserve()
    cr.set_line_width(cr.device_to_user_distance(pen, 0)[0])
    _source(cr, border)
    cr.stroke()


def _text(cr: cairo.Context, rect: tuple[float, float, float, float], pixels: float, ch: str, color=WHITE) -> None:
    """A bold Noto Sans glyph centred in `rect`, as Qt's AlignCenter does (on the line box, not the ink)."""
    layout = PangoCairo.create_layout(cr)
    options = cairo.FontOptions()
    options.set_antialias(cairo.ANTIALIAS_GRAY)  # subpixel colour fringes on a glyph that is drawn once and reused
    options.set_hint_metrics(cairo.HINT_METRICS_OFF)
    PangoCairo.context_set_font_options(layout.get_context(), options)
    layout.context_changed()
    font = Pango.FontDescription.from_string("Noto Sans Bold")
    font.set_absolute_size(pixels * Pango.SCALE)
    layout.set_font_description(font)
    layout.set_text(ch, -1)
    _ink, logical = layout.get_extents()
    w, h = logical.width / Pango.SCALE, logical.height / Pango.SCALE
    x, y, rw, rh = rect
    cr.save()
    _source(cr, color)
    cr.move_to(x + (rw - w) / 2 - logical.x / Pango.SCALE, y + (rh - h) / 2 - logical.y / Pango.SCALE)
    PangoCairo.show_layout(cr, layout)
    cr.restore()


def _line(cr, x0, y0, x1, y1) -> None:
    cr.move_to(x0, y0)
    cr.line_to(x1, y1)


def _pen(cr, color, width: float, cap=cairo.LINE_CAP_ROUND) -> None:
    _source(cr, color)
    cr.set_line_width(width)
    cr.set_line_cap(cap)


def _arrow_up(cr, color=WHITE) -> None:
    _pen(cr, color, 2)
    _line(cr, 8, 12, 8, 4.5)
    _line(cr, 5, 7.5, 8, 4.5)
    _line(cr, 11, 7.5, 8, 4.5)
    cr.stroke()


def _dot(cr, color, x=6.5, y=6.5, d=3) -> None:
    cr.arc(x + d / 2, y + d / 2, d / 2, 0, 2 * math.pi)
    _source(cr, color)
    cr.fill()


def _status(status: Status) -> Draw:
    green, dark = "#4e8f3a", "#2f5a22"

    def draw(cr):
        if status is Status.NOT_INSTALLED:
            _box(cr, "#888", WHITE)
        elif status is Status.UPGRADABLE:
            _box(cr, "#8a5a00", "#e0a020")
            _arrow_up(cr)
        elif status is Status.UNNEEDED:
            _box(cr, dark, "#9bb98f")
            _dot(cr, WHITE)
        else:
            _box(cr, dark, green)
            glyph = {Status.ORPHAN: "?", Status.NEWER: "↓"}.get(status)
            if glyph:
                _text(cr, _BOX, 10.5, glyph)
    return draw


def _padlock(cr, color) -> None:
    """A padlock filling the inside of the status box: the shackle above, the body below."""
    _pen(cr, color, 1.3, cairo.LINE_CAP_BUTT)
    cr.move_to(6.3, 7.6)
    cr.line_to(6.3, 6.1)
    cr.arc(8, 6.1, 1.7, math.pi, 2 * math.pi)  # over the top, from left to right
    cr.line_to(9.7, 7.6)
    cr.stroke()
    _rounded(cr, 5, 7.4, 6, 4.8, 0.6)
    _source(cr, color)
    cr.fill()


def _rounded(cr, x, y, w, h, r) -> None:
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def _locked(installed: bool) -> Draw:
    """A package dnf's version lock holds: the installed box (or the empty one: a lock left without the package)
    with a padlock in place of the status glyph."""
    def draw(cr):
        if installed:
            _box(cr, "#2f5a22", "#4e8f3a")
            _padlock(cr, WHITE)
        else:
            _box(cr, "#888", WHITE)
            _padlock(cr, "#777")
    return draw


def _origin(origin: Origin) -> Draw:
    color, ch = ORIGIN_STYLE[origin]

    def draw(cr):
        cr.arc(8, 8, 7, 0, 2 * math.pi)
        _source(cr, color)
        cr.fill()
        _text(cr, (1, 1, 14, 14), 9.5, ch)
    return draw


def _glyph_box(fill: str, border: str, glyph: Draw) -> Draw:
    def draw(cr):
        _box(cr, border, fill)
        _pen(cr, WHITE, 2)
        glyph(cr)
    return draw


def _mark(action: Action) -> Draw:
    def plus(cr):
        _line(cr, 4.5, 8, 11.5, 8)
        _line(cr, 8, 4.5, 8, 11.5)
        cr.stroke()

    def cross(cr):
        _line(cr, 5, 5, 11, 11)
        _line(cr, 11, 5, 5, 11)
        cr.stroke()

    def down(cr):
        _line(cr, 8, 4, 8, 11.5)
        _line(cr, 5, 8.5, 8, 11.5)
        _line(cr, 11, 8.5, 8, 11.5)
        cr.stroke()

    def letter(ch):
        return lambda cr: _text(cr, _BOX, 10.5, ch)

    style = {
        Action.INSTALL: ("#4e8f3a", "#2f5a22", plus),
        Action.REMOVE: ("#d64545", "#8a1f1f", cross),
        Action.UPGRADE: ("#3d7fd6", "#1f4f8a", _arrow_up),
        Action.REINSTALL: ("#3d7fd6", "#1f4f8a", letter("R")),
        Action.DOWNGRADE: ("#b07a1f", "#6e4c10", down),
        Action.MARK_USER: ("#4e8f3a", "#2f5a22", letter("U")),
        Action.MARK_DEP: ("#9bb98f", "#2f5a22", letter("D")),
    }
    fill, border, glyph = style[action]
    return _glyph_box(fill, border, glyph)


def _hammer(cr) -> None:
    _pen(cr, WHITE, 1.8)
    _line(cr, 4.5, 11.5, 9.5, 6.5)
    cr.stroke()
    _pen(cr, WHITE, 3, cairo.LINE_CAP_BUTT)
    _line(cr, 7.6, 4, 12, 8.4)
    cr.stroke()


def _check(cr) -> None:
    _pen(cr, WHITE, 2)
    cr.set_line_join(cairo.LINE_JOIN_ROUND)
    cr.move_to(4.5, 8.5)
    cr.line_to(7, 11)
    cr.line_to(11.5, 5)
    cr.stroke()


def _all(cr) -> None:
    """The not-installed box with a grey dot the size of the unneeded one."""
    _box(cr, "#888", WHITE)
    _dot(cr, "#888")


def _advisory(level: str | None) -> Draw:
    """A dot in the colour of an advisory level; None: an empty icon of the same size, so that the text next to it
    lines up with the rows that have a dot."""
    def draw(cr):
        if level is None:
            return
        cr.arc(8, 8, 4, 0, 2 * math.pi)
        _source(cr, ADVISORY_COLOR[level])
        cr.fill_preserve()
        _pen(cr, darker(ADVISORY_COLOR[level]), 1)
        cr.stroke()
    return draw


def _held(level: str) -> Draw:
    """A ring in the colour of an advisory level, in place of its dot: an update the version lock holds back."""
    def draw(cr):
        cr.arc(8, 8, 3.7, 0, 2 * math.pi)
        _pen(cr, ADVISORY_COLOR[level], 1.6)
        cr.stroke()
    return draw


def _blocked(cr) -> None:
    """A red cross the size of the advisory dot, in its place, with a white halo that keeps it visible on dark rows,
    the selection and a row marked for removal."""
    for color, width in ((WHITE, 4), (ADVISORY_COLOR["important"], 2)):
        _pen(cr, color, width)
        _line(cr, 5, 5, 11, 11)
        _line(cr, 11, 5, 5, 11)
        cr.stroke()


_DRAWERS: dict[str, Callable[..., Draw]] = {
    "status": _status,
    "mark": _mark,
    "locked": _locked,
    "origin": _origin,
    "advisory": _advisory,
    "held": _held,
    "blocked": lambda: _blocked,
    "all": lambda: _all,
    "user": lambda: _glyph_box("#4e8f3a", "#2f5a22", _hammer),
    "marked": lambda: _glyph_box("#8e5cc2", "#563080", _check),
}


def drawer(ref: IconRef) -> Draw | None:
    """The cairo drawing of a painted IconRef (in the 16×16 grid); None for a theme icon."""
    make = _DRAWERS.get(ref[0])
    return make(*ref[1:]) if make else None


def paint(cr: cairo.Context, draw: Draw, x: float, y: float, side: float) -> None:
    cr.save()
    cr.translate(x, y)
    cr.scale(side / GRID, side / GRID)
    cr.set_antialias(cairo.ANTIALIAS_GRAY)
    draw(cr)
    cr.restore()


class PaintedIcon(GObject.Object, Gdk.Paintable):
    """A painted icon: 16×16 by nature, shown from a texture drawn at the screen's scale and placed without
    smoothing, so a 1 px border stays one crisp pixel at 125 % and 150 %."""
    __gtype_name__ = "KramPaintedIcon"

    def __init__(self, draw: Draw, size: int = GRID):
        super().__init__()
        self._draw = draw
        self._size = size

    def do_get_intrinsic_width(self) -> int:
        return self._size

    def do_get_intrinsic_height(self) -> int:
        return self._size

    def do_get_flags(self) -> Gdk.PaintableFlags:
        return Gdk.PaintableFlags.SIZE  # the drawing does not depend on the screen scale, only the size

    def do_snapshot(self, snapshot: Gtk.Snapshot, width: float, height: float) -> None:
        """Drawn as vectors each time, by GTK, at the screen's own resolution: a texture resampled at a fractional
        scale (125 %) came out stretched and pixelated. The position is rounded to whole logical pixels only."""
        side = round(min(width, height))
        x, y = math.floor((width - side) / 2), math.floor((height - side) / 2)  # whole logical pixels
        cr = snapshot.append_cairo(Graphene.Rect().init(x, y, side, side))
        paint(cr, self._draw, x, y, side)


@cache
def paintable(ref: IconRef) -> PaintedIcon | None:
    """The shared paintable of a painted IconRef; None for a theme icon (see `icon_name`)."""
    draw = drawer(ref)
    return PaintedIcon(draw) if draw else None


def _theme_has(name: str) -> bool:
    display = Gdk.Display.get_default()
    return display is not None and Gtk.IconTheme.get_for_display(display).has_icon(name)


def first_themed(names: tuple[str, ...]) -> str | None:
    """The first of `names` the icon theme has, trying each name's -symbolic variant after the names themselves
    (Adwaita keeps few full-colour icons)."""
    for name in (*names, *(f"{n}-symbolic" for n in names if not n.endswith("-symbolic"))):
        if _theme_has(name):
            return name
    return None


@cache
def icon_name(ref: IconRef) -> str | None:
    """The theme icon name for a ("group", id) or ("theme", names) reference; None if the theme has none."""
    if ref[0] == "group":
        names, fallback = group_icon_names(ref[1])
        return first_themed(names) or (first_themed(fallback) if fallback else None)
    if ref[0] == "theme":
        return first_themed(ref[1])
    return None


def set_image(image: Gtk.Image, ref: IconRef | None) -> None:
    """Show the icon `ref` names in `image` (nothing for None)."""
    if ref is None:
        image.clear()
    elif (p := paintable(ref)) is not None:
        image.set_from_paintable(p)
    else:
        image.set_from_icon_name(icon_name(ref))
