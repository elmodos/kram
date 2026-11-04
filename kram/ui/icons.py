"""Small painted status/origin icons, cached. Painted rather than themed so they read the same in any theme.

Drawn as vectors in a 16×16 coordinate space at whatever size and screen scale Qt asks for, so they stay sharp at
125 %, 150 %, 200 %… instead of being a 16 px bitmap scaled up.
"""
from collections.abc import Callable
from functools import cache

from PySide6.QtCore import QLineF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QIconEngine, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QStyleOption

from ..core.marks import Action
from ..core.model import Origin, Status
from ..i18n import _

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
    p.drawText(QRectF(0, 0, rect.width() * 10, rect.height() * 10), Qt.AlignCenter, ch)
    p.restore()


class _PaintedIconEngine(QIconEngine):
    def __init__(self, draw: Draw):
        super().__init__()
        self._draw = draw

    def paint(self, painter: QPainter, rect: QRect, _mode, _state) -> None:
        side = min(rect.width(), rect.height())
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(rect.x() + (rect.width() - side) / 2, rect.y() + (rect.height() - side) / 2)
        painter.scale(side / _GRID, side / _GRID)
        self._draw(painter)
        painter.restore()

    def scaledPixmap(self, size: QSize, mode, state, scale: float) -> QPixmap:
        pm = QPixmap(size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        self.paint(p, QRect(0, 0, pm.width(), pm.height()), mode, state)
        p.end()
        pm.setDevicePixelRatio(scale)
        if mode == QIcon.Disabled:
            pm = QApplication.style().generatedIconPixmap(QIcon.Disabled, pm, QStyleOption())
        return pm

    def pixmap(self, size: QSize, mode, state) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def clone(self) -> QIconEngine:
        return _PaintedIconEngine(self._draw)


def _painted(draw: Draw) -> QIcon:
    return QIcon(_PaintedIconEngine(draw))


def _arrow_up(p, color=Qt.white):
    p.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QLineF(8, 12, 8, 4.5))
    p.drawLine(QLineF(5, 7.5, 8, 4.5))
    p.drawLine(QLineF(11, 7.5, 8, 4.5))


@cache
def status_icon(status: Status) -> QIcon:
    green, dark = QColor("#4e8f3a"), QColor("#2f5a22")

    def draw(p: QPainter) -> None:
        if status is Status.NOT_INSTALLED:
            _box(p, "#888", Qt.white)
        elif status is Status.UPGRADABLE:
            _box(p, "#8a5a00", "#e0a020")
            _arrow_up(p)
        elif status is Status.UNNEEDED:
            _box(p, dark, "#9bb98f")
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.white)
            p.drawEllipse(QRectF(6.5, 6.5, 3, 3))
        else:
            _box(p, dark, green)
            glyph = {Status.ORPHAN: "?", Status.NEWER: "↓"}.get(status)
            if glyph:
                p.setPen(Qt.white)
                _text(p, _BOX, 10.5, glyph)

    return _painted(draw)


ORIGIN_LABEL = {
    Origin.FEDORA: "Fedora", Origin.COPR: "COPR", Origin.THIRD_PARTY: _("Third-party origin"),
    Origin.LOCAL: _("Local origin"), Origin.UNKNOWN: _("Unknown origin"),
}
_ORIGIN_STYLE = {
    Origin.FEDORA: ("#294172", "F"), Origin.COPR: ("#d4762c", "C"), Origin.THIRD_PARTY: ("#6b6b6b", "3"),
    Origin.LOCAL: ("#7a4fa0", "L"), Origin.UNKNOWN: ("#b03030", "?"),
}


@cache
def origin_icon(origin: Origin) -> QIcon:
    color, ch = _ORIGIN_STYLE[origin]

    def draw(p: QPainter) -> None:
        p.setBrush(QColor(color))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(1, 1, 14, 14))
        p.setPen(Qt.white)
        _text(p, QRectF(1, 1, 14, 14), 9.5, ch)

    return _painted(draw)


def _glyph_box(fill: str, border: str, glyph: Draw) -> QIcon:
    def draw(p: QPainter) -> None:
        _box(p, border, fill)
        p.setPen(QPen(Qt.white, 2, Qt.SolidLine, Qt.RoundCap))
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
            p.setPen(Qt.white)
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


# translucent so they work on light and dark palettes
MARK_BACKGROUND = {
    Action.INSTALL: (90, 170, 60, 70), Action.REMOVE: (210, 60, 60, 80), Action.UPGRADE: (60, 130, 220, 70),
    Action.REINSTALL: (60, 130, 220, 50), Action.DOWNGRADE: (200, 150, 40, 70),
    Action.MARK_USER: (90, 170, 60, 35), Action.MARK_DEP: (90, 170, 60, 35),
}
