#!/usr/bin/python3
"""Spike S7 (docs/GTK_FRONTEND.md §7.1): the painted icons of kram.gtk.icons next to those of kram.qt.icons, at
100/125/150/200 %, on a light and a dark background.

    python3 scripts/spikes/s7_icons.py OUT_DIR

GTK side: kram.gtk.icons.texture at the scale, as a window at that scale shows it (each texture pixel one screen
pixel, placed at the device pixel nearest its logical position, as GTK's NEAREST filter does). Qt side: QIcon.pixmap at the device pixel
ratio, as its views do. Writes OUT_DIR/s7-<scale>.png: per background, a row of Qt icons above the row of GTK ones;
and OUT_DIR/s7-zoom.png, the 150 % rows enlarged 6× without smoothing.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import common  # noqa: E402,F401  (puts the repository on sys.path, pins the gi versions)

import kram.gtk  # noqa: E402,F401
from gi.repository import Gtk  # noqa: E402

from kram.core.marks import Action  # noqa: E402
from kram.core.model import Origin, Status  # noqa: E402

REFS = ([("status", s) for s in Status] + [("mark", a) for a in Action] + [("locked", True), ("locked", False)]
        + [("origin", o) for o in Origin] + [("advisory", lv) for lv in ("critical", "important", "moderate", "low",
                                                                          "bugfix", "enhancement")]
        + [("held", "important"), ("blocked",), ("all",), ("user",), ("marked",)])
STEP, PAD, ROW = 22, 3, 22  # logical pixels: odd offsets, so fractional scales hit half pixels
BACKGROUNDS = (("light", "#fafafa"), ("dark", "#242424"))
SCALES = (1.0, 1.25, 1.5, 2.0)


def gtk_strip(scale: float, background: str, path: Path) -> None:
    import cairo

    from kram.gtk.icons import drawer, texture
    width, height = round((PAD * 2 + STEP * len(REFS)) * scale), round(ROW * scale)
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(out)
    cr.set_source_rgb(*(int(background[i:i + 2], 16) / 255 for i in (1, 3, 5)))
    cr.paint()
    for i, ref in enumerate(REFS):
        tex = texture(drawer(ref), 16, scale)
        png = Path(str(path) + f".{i}.png")
        tex.save_to_png(str(png))
        img = cairo.ImageSurface.create_from_png(str(png))
        png.unlink()
        cr.set_source_surface(img, round((PAD + i * STEP) * scale), round(PAD * scale))
        cr.paint()
    out.write_to_png(str(path))


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    Gtk.init()

    from PySide6.QtCore import QPointF, QRectF, QSize, Qt
    from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter
    from PySide6.QtWidgets import QApplication
    app = QApplication([])  # noqa: F841
    from kram.qt.icons import icon

    zoom_rows = []
    for scale in SCALES:
        width, height = PAD * 2 + STEP * len(REFS), ROW
        dev_w, dev_h = round(width * scale), round(height * scale)
        label_w = 70
        sheet = QImage(label_w + dev_w, dev_h * 4 + 8, QImage.Format.Format_ARGB32)
        sheet.fill(QColor("#808080"))
        p = QPainter(sheet)
        f = QFont("Noto Sans")
        f.setPixelSize(11)
        p.setFont(f)
        for b, (name, bg) in enumerate(BACKGROUNDS):
            y_qt, y_gtk = b * (dev_h * 2 + 4), b * (dev_h * 2 + 4) + dev_h
            qt = QImage(dev_w, dev_h, QImage.Format.Format_ARGB32)
            qt.fill(QColor(bg))
            qp = QPainter(qt)
            for i, ref in enumerate(REFS):
                pm = icon(ref).pixmap(QSize(16, 16), scale)
                pm.setDevicePixelRatio(1)  # drawn 1:1 into the device-pixel image
                at = QPointF((PAD + i * STEP) * scale, PAD * scale)
                qp.drawPixmap(QPointF(round(at.x()), round(at.y())), pm)  # Qt snaps to device pixels
            qp.end()
            path = out / f"gtk-{scale}-{name}.png"
            gtk_strip(scale, bg, path)
            gimg = QImage(str(path))
            p.drawImage(label_w, y_qt, qt)
            p.drawImage(label_w, y_gtk, gimg)
            p.setPen(QColor("white"))
            p.drawText(QRectF(2, y_qt, label_w, dev_h), Qt.AlignmentFlag.AlignVCenter, f"Qt {name}")
            p.drawText(QRectF(2, y_gtk, label_w, dev_h), Qt.AlignmentFlag.AlignVCenter, f"GTK {name}")
            if scale == 1.5 and name == "light":
                zoom_rows = [qt, gimg]
        p.end()
        sheet.save(str(out / f"s7-{int(scale * 100)}.png"))
    # the first twelve icons at 150 %, enlarged so every device pixel shows
    crop = round((PAD + 12 * STEP) * 1.5)
    zoom = QImage(crop * 6, zoom_rows[0].height() * 6 * 2 + 6, QImage.Format.Format_ARGB32)
    zoom.fill(QColor("#808080"))
    p = QPainter(zoom)
    for i, img in enumerate(zoom_rows):
        part = img.copy(0, 0, crop, img.height()).scaled(crop * 6, img.height() * 6)
        p.drawImage(0, i * (img.height() * 6 + 6), part)
    p.end()
    zoom.save(str(out / "s7-zoom.png"))
    print(f"written to {out}")


if __name__ == "__main__":
    main()
