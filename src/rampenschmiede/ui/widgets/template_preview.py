"""Vorschaubilder für Vorlagen und Bausteine: die Form schräg von oben, schattiert.

Gezeichnet wird mit QPainter (ohne OpenGL), damit die Bilder überall gehen, auch in Listen
und Symbolen. Flächen werden von hinten nach vorne gemalt (Maleralgorithmus); für ein
Vorschaubild konvexer Brushes reicht das.
"""
from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QTransform,
)

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


#: Units pro Wiederholung einer Textur in der texturierten Vorschau
TEXTURE_UNITS = 512.0

#: Textur je Fläche (oder None = einfarbig wie sonst)
TextureFor = Callable[[Face], "QImage | None"]


def _face_axes(n: Sequence[float]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Achsen der Textur auf einer Fläche: Bild-x läuft die Neigung hinunter, Bild-y waagrecht
    entlang der Fläche. So liegen die Linien einer Rampentextur quer zur Fahrtrichtung."""
    hx, hy = -n[1], n[0]
    length = math.hypot(hx, hy)
    if length < 1e-6:
        return (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)
    h = (hx / length, hy / length, 0.0)
    down = (n[1] * h[2] - n[2] * h[1], n[2] * h[0] - n[0] * h[2], n[0] * h[1] - n[1] * h[0])
    return down, h


def render(face_sets: Iterable[Sequence[Face]], size: QSize | int = 160,
           background: QColor | None = None, textures: TextureFor | None = None) -> QPixmap:
    """Bild der Brushes aus `face_sets` (Flächen je Brush). Mit `textures` werden Flächen mit
    Textur belegt (Rampentexturen ansehen, bevor man sie anwendet)."""
    if isinstance(size, int):
        size = QSize(size, size)
    polys: list[tuple[float, list[tuple[float, float]], QColor, tuple | None]] = []
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
            texture = textures(face) if textures is not None and color.alpha() == 255 else None
            tex = None
            if texture is not None and not texture.isNull():
                down, along = _face_axes(n)
                # Ursprung auf der Ebene am nächsten zum Nullpunkt: Nachbarflächen setzen das Muster fort
                o = [n[k] * face.plane.dist for k in range(3)]
                step_x = TEXTURE_UNITS / texture.width()
                step_y = TEXTURE_UNITS / texture.height()
                tex = (texture, _rotate(o), _rotate([o[k] + down[k] * step_x for k in range(3)]),
                       _rotate([o[k] + along[k] * step_y for k in range(3)]), shade)
            polys.append((depth, [(p[0], p[1]) for p in pts], shaded, tex))
    image = QImage(size, QImage.Format_ARGB32_Premultiplied)
    image.fill(background or Qt.transparent)
    if polys:
        xs = [x for _d, pts, _c, _t in polys for x, _y in pts]
        ys = [y for _d, pts, _c, _t in polys for _x, y in pts]
        w, h = max(xs) - min(xs) or 1.0, max(ys) - min(ys) or 1.0
        usable_w, usable_h = size.width() * (1 - 2 * MARGIN), size.height() * (1 - 2 * MARGIN)
        scale = min(usable_w / w, usable_h / h)
        ox = (size.width() - w * scale) / 2 - min(xs) * scale
        oy = (size.height() + h * scale) / 2 + min(ys) * scale
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        def to_screen(p) -> tuple[float, float]:
            return ox + p[0] * scale, oy - p[1] * scale

        for _depth, pts, color, tex in sorted(polys, key=lambda t: -t[0]):
            screen = [QPointF(ox + x * scale, oy - y * scale) for x, y in pts]
            if tex is not None:
                # Ortho-Projektion: Bildpunkte -> Bildschirm ist affin, also reicht eine QTransform
                tex_image, o, px, py, shade = tex
                (x0, y0), (x1, y1), (x2, y2) = to_screen(o), to_screen(px), to_screen(py)
                brush = QBrush(QPixmap.fromImage(tex_image))
                brush.setTransform(QTransform(x1 - x0, y1 - y0, x2 - x0, y2 - y0, x0, y0))
                painter.setPen(Qt.NoPen)
                painter.setBrush(brush)
                painter.drawPolygon(QPolygonF(screen))
                painter.setBrush(QColor(0, 0, 0, round(255 * (1 - shade) * 0.9)))
                painter.setPen(QPen(EDGE, 1.0))
                painter.drawPolygon(QPolygonF(screen))
                continue
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


def library_textures(library) -> TextureFor:
    """Texturen aus der Materialbibliothek (eigene Rampentexturen, Spiel-Materialien) für `render`.
    Werkzeug-Texturen und fehlende Materialien bleiben einfarbig."""
    cache: dict[str, QImage | None] = {}

    def texture(face: Face) -> QImage | None:
        name = face.material.upper()
        if name.startswith("TOOLS/") or library is None:
            return None
        if name not in cache:
            tex = library.texture(name)
            cache[name] = (QImage(tex.rgba, tex.width, tex.height, tex.width * 4, QImage.Format_RGBA8888).copy()
                           if tex is not None and tex.width and tex.height else None)
        return cache[name]
    return texture


def template_faces(template: Template | str, values: dict | None = None) -> list[Sequence[Face]]:
    try:
        return list(generate(template, values).face_sets)
    except Exception:  # noqa: BLE001 - ungültige Zwischenwerte: leeres Bild statt Absturz
        return []


def template_pixmap(template: Template | str, values: dict | None = None, size: int | QSize = 160,
                    textures: TextureFor | None = None, background: QColor | None = None) -> QPixmap:
    return render(template_faces(template, values), size, background, textures)


def template_icon(key: str, size: int = 48) -> QIcon:
    """Symbol einer Vorlage mit ihren Standardwerten (zwischengespeichert)."""
    cache_key = (key, size)
    found = _icons.get(cache_key)
    if found is None:
        found = _icons[cache_key] = QIcon(template_pixmap(CATALOG[key], None, size))
    return found


__all__ = ["library_textures", "render", "template_faces", "template_icon", "template_pixmap"]
