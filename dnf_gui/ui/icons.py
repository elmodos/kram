"""Small painted status/origin icons, cached. Painted rather than themed so they read the same in any theme."""
from functools import cache

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap

from ..core.model import Origin, Status

_BOX = QRect(1, 1, 13, 13)


def _canvas():
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    return pm, p


def _arrow_up(p, color=Qt.white):
    p.setPen(QPen(color, 2))
    p.drawLine(7, 12, 7, 4)
    p.drawLine(4, 7, 7, 4)
    p.drawLine(10, 7, 7, 4)


@cache
def status_icon(status: Status) -> QIcon:
    pm, p = _canvas()
    green, dark = QColor("#4e8f3a"), QColor("#2f5a22")
    if status is Status.NOT_INSTALLED:
        p.setPen(QPen(QColor("#888"), 1))
        p.setBrush(Qt.white)
        p.drawRect(_BOX)
    elif status is Status.UPGRADABLE:
        p.setPen(QPen(QColor("#8a5a00"), 1))
        p.setBrush(QColor("#e0a020"))
        p.drawRect(_BOX)
        _arrow_up(p)
    elif status is Status.UNNEEDED:
        p.setPen(QPen(dark, 1))
        p.setBrush(QColor("#9bb98f"))
        p.drawRect(_BOX)
        p.setPen(QPen(Qt.white, 3))
        p.drawPoint(7, 7)
    else:
        p.setPen(QPen(dark, 1))
        p.setBrush(green)
        p.drawRect(_BOX)
        glyph = {Status.ORPHAN: "?", Status.NEWER: "↓"}.get(status)
        if glyph:
            p.setPen(Qt.white)
            p.setFont(QFont("Noto Sans", 8, QFont.Bold))
            p.drawText(_BOX, Qt.AlignCenter, glyph)
    p.end()
    return QIcon(pm)


ORIGIN_LABEL = {
    Origin.FEDORA: "Fedora", Origin.COPR: "COPR", Origin.THIRD_PARTY: "Стороннє",
    Origin.LOCAL: "Локальне", Origin.UNKNOWN: "Невідоме",
}
_ORIGIN_STYLE = {
    Origin.FEDORA: ("#294172", "F"), Origin.COPR: ("#d4762c", "C"), Origin.THIRD_PARTY: ("#6b6b6b", "3"),
    Origin.LOCAL: ("#7a4fa0", "L"), Origin.UNKNOWN: ("#b03030", "?"),
}


@cache
def origin_icon(origin: Origin) -> QIcon:
    color, ch = _ORIGIN_STYLE[origin]
    pm, p = _canvas()
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, 14, 14)
    p.setPen(Qt.white)
    p.setFont(QFont("Noto Sans", 7, QFont.Bold))
    p.drawText(QRect(1, 1, 14, 14), Qt.AlignCenter, ch)
    p.end()
    return QIcon(pm)
