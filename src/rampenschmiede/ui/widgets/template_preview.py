"""Vorschaubilder für Vorlagen und Bausteine: die Form schräg von oben, schattiert.

Gezeichnet wird mit QPainter (ohne OpenGL), damit die Bilder überall gehen, auch in Listen
und Symbolen. Flächen werden von hinten nach vorne gemalt (Maleralgorithmus); für ein
Vorschaubild konvexer Brushes reicht das.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap, QPolygonF

from ...core.model import Face, Solid
from ...core.surf.catalog import CATALOG, Template, generate

#: Blickrichtung: von schräg vorne links, leicht von oben
YAW = math.radians(-35.0)
PITCH = math.radians(32.0)
LIGHT = (-0.35, -0.55, 0.76)
SURF = QColor(120, 150, 185)
TOP = QColor(200, 200, 205)
WATER = QColor(60, 130, 210)
LAVA = QColor(235, 95, 30)
TRIGGER = QColor(255, 150, 40, 110)
HIDDEN = QColor(90, 90, 96)
EDGE = QColor(20, 22, 26, 170)
#: Ab dieser Fläche in Pixeln bekommt eine Fläche dunkle Kanten
EDGE_AREA = 400
#: Rand um die Form, Anteil der Bildgröße
MARGIN = 0.08

_icons: dict[tuple, QIcon] = {}


def _color(face: Face) -> QColor | None:
    m = face.material.upper()
    if "TRIGGER" in m:
        return TRIGGER
    if "SKIP" in m or "HINT" in m or "CLIP" in m:
        return None
    if "WATER" in m:
        return WATER
    if "LAVA" in m:
        return LAVA
    if m.startswith("TOOLS/"):
        return HIDDEN
    nz = face.plane.normal[2]
    return TOP if nz > 0.72 or nz < -0.72 else SURF


def _rotate(p: Sequence[float]) -> tuple[float, float, float]:
    """Welt -> (rechts, oben, Tiefe) der Vorschaukamera."""
    c, s = math.cos(YAW), math.sin(YAW)
    x, y, z = c * p[0] - s * p[1], s * p[0] + c * p[1], p[2]
    cp, sp = math.cos(PITCH), math.sin(PITCH)
    return x, y * sp + z * cp, y * cp - z * sp


def render(face_sets: Iterable[Sequence[Face]], size: QSize | int = 160,
           background: QColor | None = None) -> QPixmap:
    """Bild der Brushes aus `face_sets` (Flächen je Brush)."""
    if isinstance(size, int):
        size = QSize(size, size)
    polys: list[tuple[float, list[tuple[float, float]], QColor]] = []
    for faces in face_sets:
        if not faces:
            continue
        for face, poly in zip(faces, Solid(id=0, faces=tuple(faces)).polygons()):
            if not poly or len(poly) < 3:
                continue
            color = _color(face)
            if color is None:
                continue
            n = face.plane.normal
            view = _rotate(n)
            # Rückseiten weglassen; durchsichtige Trigger zeigen auch die Rückseite
            if view[2] > 0 and color.alpha() == 255:
                continue
            pts = [_rotate(p) for p in poly]
            depth = sum(p[2] for p in pts) / len(pts)
            shade = 0.5 + 0.5 * max(0.0, sum(n[k] * LIGHT[k] for k in range(3)))
            shaded = QColor.fromRgbF(min(1.0, color.redF() * shade), min(1.0, color.greenF() * shade),
                                     min(1.0, color.blueF() * shade), color.alphaF())
            polys.append((depth, [(p[0], p[1]) for p in pts], shaded))
    image = QImage(size, QImage.Format_ARGB32_Premultiplied)
    image.fill(background or Qt.transparent)
    if polys:
        xs = [x for _d, pts, _c in polys for x, _y in pts]
        ys = [y for _d, pts, _c in polys for _x, y in pts]
        w, h = max(xs) - min(xs) or 1.0, max(ys) - min(ys) or 1.0
        usable_w, usable_h = size.width() * (1 - 2 * MARGIN), size.height() * (1 - 2 * MARGIN)
        scale = min(usable_w / w, usable_h / h)
        ox = (size.width() - w * scale) / 2 - min(xs) * scale
        oy = (size.height() + h * scale) / 2 + min(ys) * scale
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        for _depth, pts, color in sorted(polys, key=lambda t: -t[0]):
            screen = [QPointF(ox + x * scale, oy - y * scale) for x, y in pts]
            # Kanten nur an größeren Flächen; feine Kurvenstücke würden sonst schwarz
            area = abs(sum(screen[i].x() * screen[i - 1].y() - screen[i - 1].x() * screen[i].y()
                           for i in range(len(screen)))) / 2
            pen = QPen(EDGE if area > EDGE_AREA else color.darker(115))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.setBrush(color)
            painter.drawPolygon(QPolygonF(screen))
        painter.end()
    return QPixmap.fromImage(image)


def template_faces(template: Template | str, values: dict | None = None) -> list[Sequence[Face]]:
    try:
        return list(generate(template, values).face_sets)
    except Exception:  # noqa: BLE001 - ungültige Zwischenwerte: leeres Bild statt Absturz
        return []


def template_pixmap(template: Template | str, values: dict | None = None, size: int = 160) -> QPixmap:
    return render(template_faces(template, values), size)


def template_icon(key: str, size: int = 48) -> QIcon:
    """Symbol einer Vorlage mit ihren Standardwerten (zwischengespeichert)."""
    cache_key = (key, size)
    found = _icons.get(cache_key)
    if found is None:
        found = _icons[cache_key] = QIcon(template_pixmap(CATALOG[key], None, size))
    return found


__all__ = ["render", "template_faces", "template_icon", "template_pixmap"]
