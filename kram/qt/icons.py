"""Small painted status/origin icons, cached. Painted rather than themed so they read the same in any theme.

Drawn as vectors in a 16×16 coordinate space at whatever size and screen scale Qt asks for, so they stay sharp at
125 %, 150 %, 200 %… instead of being a 16 px bitmap scaled up.
"""
from collections.abc import Callable
from functools import cache

from PySide6.QtCore import QLineF, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QStyleOption

from ..app.icons import ADVISORY_COLOR, ORIGIN_STYLE, IconRef
from ..core.marks import Action
from ..core.model import Origin, Status
from .group_icons import group_icon

_BOX = QRectF(1.5, 1.5, 13, 13)   # where glyphs inside the box are centred
_BOX_OUTER = QRectF(1, 1, 14, 14)  # the box including its 1 px border
_GRID = 16  # every icon is drawn in a 16×16 coordinate space

Draw = Callable[[QPainter], None]


def _box(p: QPainter, border, fill) -> None:
    """The status/mark box, snapped to whole device pixels with a whole-pixel border.

    At fractional scales (125 %, 150 %) a scaled 1 px border lands between pixels and smears over two; snapping
    keeps it one crisp line on every screen.
    """
    dpr = p.device().devicePixelRatioF()
    t = p.transform()
    outer = t.mapRect(_BOX_OUTER)
    left, top = round(outer.left() * dpr) / dpr, round(outer.top() * dpr) / dpr
    right, bottom = round(outer.right() * dpr) / dpr, round(outer.bottom() * dpr) / dpr
    pen = max(1, round(t.m11() * dpr)) / dpr
    p.save()
    p.resetTransform()
    p.setPen(QPen(QColor(border), pen))
    p.setBrush(QColor(fill))
    p.drawRect(QRectF(left + pen / 2, top + pen / 2, right - left - pen, bottom - top - pen))
    p.restore()


def _font(pixels: float) -> QFont:
    f = QFont("Noto Sans")
    f.setPixelSize(round(pixels * 10))  # scaled down by the painter below; a large size hints better
    f.setBold(True)
    return f


def _text(p: QPainter, rect: QRectF, pixels: float, ch: str) -> None:
    p.save()
    p.translate(rect.topLeft())
    p.scale(0.1, 0.1)
    p.setFont(_font(pixels))
    p.drawText(QRectF(0, 0, rect.width() * 10, rect.height() * 10), Qt.AlignmentFlag.AlignCenter, ch)
    p.restore()


class _PaintedIconEngine(QIconEngine):
    """Draws the vectors once per pixel size and screen scale, then reuses that pixmap (~1 µs instead of ~30 µs)."""

    def __init__(self, draw: Draw):
        super().__init__()
        self._draw = draw
        self._pixmaps: dict[tuple, QPixmap] = {}

    def _paint_vectors(self, painter: QPainter, rect: QRect) -> None:
        side = min(rect.width(), rect.height())
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(rect.x() + (rect.width() - side) / 2, rect.y() + (rect.height() - side) / 2)
        painter.scale(side / _GRID, side / _GRID)
        self._draw(painter)
        painter.restore()

    def paint(self, painter: QPainter, rect: QRect, mode, state) -> None:
        # scaled or rotated: a cached pixmap would blur
        if painter.transform().type().value > QTransform.TransformationType.TxTranslate.value:
            self._paint_vectors(painter, rect)
            return
        side = min(rect.width(), rect.height())
        dpr = painter.device().devicePixelRatioF()
        pm = self.scaledPixmap(QSize(side, side), mode, state, dpr)
        # at 125 % or 150 % a logical position can fall between device pixels: snap so the pixmap is not resampled
        at = painter.transform().map(QPointF(rect.x() + (rect.width() - side) / 2, rect.y() + (rect.height() - side) / 2))
        painter.save()
        painter.resetTransform()
        painter.drawPixmap(QPointF(round(at.x() * dpr) / dpr, round(at.y() * dpr) / dpr), pm)
        painter.restore()

    def scaledPixmap(self, size: QSize, mode, state, scale: float) -> QPixmap:
        key = (size.width(), size.height(), scale, mode == QIcon.Mode.Disabled)
        if (cached := self._pixmaps.get(key)) is not None:
            return cached
        pm = QPixmap(size * scale)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        self._paint_vectors(p, QRect(0, 0, pm.width(), pm.height()))
        p.end()
        pm.setDevicePixelRatio(scale)
        if mode == QIcon.Mode.Disabled:
            pm = QApplication.style().generatedIconPixmap(QIcon.Mode.Disabled, pm, QStyleOption())
        self._pixmaps[key] = pm
        return pm

    def pixmap(self, size: QSize, mode, state) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def clone(self) -> QIconEngine:
        return _PaintedIconEngine(self._draw)


def _painted(draw: Draw) -> QIcon:
    return QIcon(_PaintedIconEngine(draw))


def _arrow_up(p, color=Qt.GlobalColor.white):
    p.setPen(QPen(color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QLineF(8, 12, 8, 4.5))
    p.drawLine(QLineF(5, 7.5, 8, 4.5))
    p.drawLine(QLineF(11, 7.5, 8, 4.5))


@cache
def status_icon(status: Status) -> QIcon:
    green, dark = QColor("#4e8f3a"), QColor("#2f5a22")

    def draw(p: QPainter) -> None:
        if status is Status.NOT_INSTALLED:
            _box(p, "#888", Qt.GlobalColor.white)
        elif status is Status.UPGRADABLE:
            _box(p, "#8a5a00", "#e0a020")
            _arrow_up(p)
        elif status is Status.UNNEEDED:
            _box(p, dark, "#9bb98f")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(Qt.GlobalColor.white)
            p.drawEllipse(QRectF(6.5, 6.5, 3, 3))
        else:
            _box(p, dark, green)
            glyph = {Status.ORPHAN: "?", Status.NEWER: "↓"}.get(status)
            if glyph:
                p.setPen(Qt.GlobalColor.white)
                _text(p, _BOX, 10.5, glyph)

    return _painted(draw)


def _padlock(p: QPainter, color) -> None:
    """A padlock filling the inside of the status box: the shackle above, the body below."""
    p.setPen(QPen(QColor(color), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    shackle = QPainterPath(QPointF(6.3, 7.6))
    shackle.lineTo(6.3, 6.1)
    shackle.arcTo(QRectF(6.3, 4.4, 3.4, 3.4), 180, -180)
    shackle.lineTo(9.7, 7.6)
    p.drawPath(shackle)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    p.drawRoundedRect(QRectF(5, 7.4, 6, 4.8), 0.6, 0.6)


@cache
def locked_icon(installed: bool) -> QIcon:
    """A package dnf's version lock holds: the installed box (or the empty one: a lock left without the package)
    with a padlock in place of the status glyph."""
    def draw(p: QPainter) -> None:
        if installed:
            _box(p, "#2f5a22", "#4e8f3a")
            _padlock(p, Qt.GlobalColor.white)
        else:
            _box(p, "#888", Qt.GlobalColor.white)
            _padlock(p, "#777")

    return _painted(draw)


@cache
def origin_icon(origin: Origin) -> QIcon:
    color, ch = ORIGIN_STYLE[origin]

    def draw(p: QPainter) -> None:
        p.setBrush(QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(1, 1, 14, 14))
        p.setPen(Qt.GlobalColor.white)
        _text(p, QRectF(1, 1, 14, 14), 9.5, ch)

    return _painted(draw)


def _glyph_box(fill: str, border: str, glyph: Draw) -> QIcon:
    def draw(p: QPainter) -> None:
        _box(p, border, fill)
        p.setPen(QPen(Qt.GlobalColor.white, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        glyph(p)

    return _painted(draw)


@cache
def mark_icon(action: Action) -> QIcon:
    def plus(p):
        p.drawLine(QLineF(4.5, 8, 11.5, 8))
        p.drawLine(QLineF(8, 4.5, 8, 11.5))

    def cross(p):
        p.drawLine(QLineF(5, 5, 11, 11))
        p.drawLine(QLineF(11, 5, 5, 11))

    def down(p):
        p.drawLine(QLineF(8, 4, 8, 11.5))
        p.drawLine(QLineF(5, 8.5, 8, 11.5))
        p.drawLine(QLineF(11, 8.5, 8, 11.5))

    def letter(ch):
        def draw(p):
            p.setPen(Qt.GlobalColor.white)
            _text(p, _BOX, 10.5, ch)
        return draw

    style = {
        Action.INSTALL: ("#4e8f3a", "#2f5a22", plus),
        Action.REMOVE: ("#d64545", "#8a1f1f", cross),
        Action.UPGRADE: ("#3d7fd6", "#1f4f8a", _arrow_up),
        Action.REINSTALL: ("#3d7fd6", "#1f4f8a", letter("R")),
        Action.DOWNGRADE: ("#b07a1f", "#6e4c10", down),
        Action.MARK_USER: ("#4e8f3a", "#2f5a22", letter("U")),
        Action.MARK_DEP: ("#9bb98f", "#2f5a22", letter("D")),
    }
    fill, border, draw = style[action]
    return _glyph_box(fill, border, draw)


def _hammer(p: QPainter) -> None:
    p.setPen(QPen(Qt.GlobalColor.white, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QLineF(4.5, 11.5, 9.5, 6.5))
    p.setPen(QPen(Qt.GlobalColor.white, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    p.drawLine(QLineF(7.6, 4, 12, 8.4))


def _check(p: QPainter) -> None:
    p.setPen(QPen(Qt.GlobalColor.white, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawPolyline([QPointF(4.5, 8.5), QPointF(7, 11), QPointF(11.5, 5)])


@cache
def _all_icon() -> QIcon:
    """The not-installed box with a grey dot the size of the unneeded one."""
    def draw(p: QPainter) -> None:
        _box(p, "#888", Qt.GlobalColor.white)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#888"))
        p.drawEllipse(QRectF(6.5, 6.5, 3, 3))

    return _painted(draw)


@cache
def advisory_icon(level: str | None) -> QIcon:
    """A dot in the colour of an advisory level; None: an empty icon of the same size, so that the text next to it
    lines up with the rows that have a dot."""
    def draw(p: QPainter) -> None:
        if level is None:
            return
        color = QColor(ADVISORY_COLOR[level])
        p.setPen(QPen(color.darker(150), 1))
        p.setBrush(color)
        p.drawEllipse(QRectF(4, 4, 8, 8))

    return _painted(draw)


@cache
def held_advisory_icon(level: str) -> QIcon:
    """A ring in the colour of an advisory level, in place of its dot: an update the version lock holds back."""
    def draw(p: QPainter) -> None:
        p.setPen(QPen(QColor(ADVISORY_COLOR[level]), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(4.3, 4.3, 7.4, 7.4))

    return _painted(draw)


@cache
def blocked_icon() -> QIcon:
    """A red cross the size of the advisory dot, in its place: the upgrade cannot be installed now. The white halo
    keeps it visible on dark rows, the selection and the reddish background of a row marked for removal."""
    def draw(p: QPainter) -> None:
        cross = (QLineF(5, 5, 11, 11), QLineF(11, 5, 5, 11))
        for color, width in ((Qt.GlobalColor.white, 4), (QColor(ADVISORY_COLOR["important"]), 2)):
            p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLines(cross)

    return _painted(draw)


@cache
def _user_icon() -> QIcon:
    return _glyph_box("#4e8f3a", "#2f5a22", _hammer)


@cache
def _marked_icon() -> QIcon:
    return _glyph_box("#8e5cc2", "#563080", _check)


def _theme(names: tuple[str, ...]) -> QIcon:
    for name in names:
        if QIcon.hasThemeIcon(name):
            return QIcon.fromTheme(name)
    return QIcon()


_MAKERS: dict[str, Callable[..., QIcon]] = {
    "status": lambda status: status_icon(status),
    "mark": lambda action: mark_icon(action),
    "locked": lambda installed: locked_icon(installed),
    "origin": lambda origin: origin_icon(origin),
    "advisory": lambda level: advisory_icon(level),
    "held": lambda level: held_advisory_icon(level),
    "blocked": lambda: blocked_icon(),
    "all": lambda: _all_icon(),
    "user": lambda: _user_icon(),
    "marked": lambda: _marked_icon(),
    "group": lambda group_id: group_icon(group_id),
    "theme": lambda names: _theme(names),
}


def icon(ref: IconRef) -> QIcon:
    """The icon a kram.app.icons.IconRef names."""
    return _MAKERS[ref[0]](*ref[1:])

