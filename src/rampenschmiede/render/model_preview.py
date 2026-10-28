"""Vorschaubilder von Modellen ohne OpenGL (läuft daher auch in Hintergrund-Threads).

Die Dreiecke werden von hinten nach vorne als gefüllte Polygone gemalt (Maleralgorithmus),
jedes in der mittleren Farbe seiner Textur und einfach schattiert. Für Kacheln und die
drehbare Vorschau im Modell-Browser reicht das völlig; die Ansichten zeigen Props texturiert.
"""
from __future__ import annotations

import math
import threading

import numpy as np

from ..core.materials import MaterialLibrary
from ..core.models.library import LoadedModel

BACKGROUND = (30, 31, 34, 255)
NO_TEXTURE = (175, 175, 170)
_LIGHT = np.array([0.45, 0.35, 0.82])
_colors: dict[tuple[int, str], tuple[int, int, int]] = {}
_lock = threading.Lock()


def material_average(library: MaterialLibrary | None, name: str) -> tuple[int, int, int]:
    """Mittlere Farbe der Textur eines Materials (zwischengespeichert)."""
    if library is None or not name:
        return NO_TEXTURE
    key = (id(library), name)
    with _lock:
        hit = _colors.get(key)
    if hit is not None:
        return hit
    tex = library.texture(name)
    if tex is None:
        color = NO_TEXTURE
    else:
        px = np.frombuffer(tex.rgba, dtype=np.uint8).reshape(-1, 4)
        opaque = px[px[:, 3] > 64]
        src = opaque if len(opaque) else px
        mean = src[:, :3].mean(axis=0)
        color = (int(mean[0]), int(mean[1]), int(mean[2]))
    with _lock:
        _colors[key] = color
    return color


def view_basis(yaw: float, pitch: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rechts, oben und Blickrichtung einer Kamera, die aus (yaw, pitch) auf das Modell schaut."""
    y, p = math.radians(yaw), math.radians(pitch)
    eye = np.array([math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p)])
    forward = -eye
    right = np.cross(forward, [0.0, 0.0, 1.0])
    right /= max(np.linalg.norm(right), 1e-9)
    up = np.cross(right, forward)
    return right, up, forward


def render_preview(model: LoadedModel, library: MaterialLibrary | None, size: int = 128,
                   yaw: float = 30.0, pitch: float = 20.0, skin: int = 0, max_triangles: int = 30_000) -> bytes:
    """RGBA-Bild (size × size) des Modells, eingepasst mit etwas Rand."""
    from PIL import Image, ImageDraw

    scale = 2  # doppelt so groß malen und verkleinern = glatte Kanten
    big = size * scale
    img = Image.new("RGBA", (big, big), BACKGROUND)
    geom = model.geometry
    if geom is None or not geom.triangle_count:
        return _box_preview(model, size, yaw, pitch)
    right, up, forward = view_basis(yaw, pitch)
    tris, mats_idx = geom.triangles, geom.tri_material
    if len(tris) > max_triangles:  # sehr dichte Modelle: jedes n-te Dreieck reicht für ein Bildchen
        pick = np.linspace(0, len(tris) - 1, max_triangles).astype(np.int64)
        tris, mats_idx = tris[pick], mats_idx[pick]
    pos = geom.positions
    lo, hi = pos[tris.reshape(-1)].min(axis=0), pos[tris.reshape(-1)].max(axis=0)
    center = (lo + hi) / 2
    p = pos - center
    sx, sy, depth = p @ right, -(p @ up), p @ forward
    used = tris.reshape(-1)
    extent = max(float(np.abs(sx[used]).max()), float(np.abs(sy[used]).max()), 1e-3)
    k = big * 0.44 / extent
    px = sx * k + big / 2
    py = sy * k + big / 2

    a, b, c = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    n = np.cross(b - a, c - a)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    # Zur Kamera gedrehte Seite beleuchten (Modelle haben oft zweiseitige Flächen)
    facing = np.where((n @ forward)[:, None] > 0, -n, n)
    light = 0.38 + 0.62 * np.clip(facing @ _LIGHT, 0.0, 1.0)

    materials = model.materials(skin)
    palette = np.array([material_average(library, materials[i]) if i < len(materials) else NO_TEXTURE
                        for i in range(int(mats_idx.max()) + 1)], dtype=np.float32)
    colors = np.clip(palette[mats_idx] * light[:, None], 0, 255).astype(np.uint8)

    # Erst alle abgewandten Dreiecke (laut Vertex-Normalen), dann die zugewandten, jeweils von
    # hinten nach vorne: so überdeckt keine Rückseite eine Vorderseite, und zweiseitige
    # Flächen wie Blätter bleiben trotzdem sichtbar
    away = (geom.normals[tris].mean(axis=1) @ forward) > 0
    order = np.lexsort((-depth[tris].mean(axis=1), ~away))
    draw = ImageDraw.Draw(img)
    for t in order:
        i0, i1, i2 = tris[t]
        col = tuple(int(v) for v in colors[t]) + (255,)
        draw.polygon([(px[i0], py[i0]), (px[i1], py[i1]), (px[i2], py[i2])], fill=col)
    return img.resize((size, size), Image.Resampling.LANCZOS).tobytes()


def _box_preview(model: LoadedModel, size: int, yaw: float, pitch: float) -> bytes:
    """Ohne Dreiecke (VVD/VTX fehlt): der Umriss des Modell-Kastens."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), BACKGROUND)
    lo, hi = (np.array(v, dtype=float) for v in model.bounds())
    corners = np.array([[lo[0] if i & 1 == 0 else hi[0], lo[1] if i & 2 == 0 else hi[1],
                         lo[2] if i & 4 == 0 else hi[2]] for i in range(8)]) - (lo + hi) / 2
    right, up, _ = view_basis(yaw, pitch)
    sx, sy = corners @ right, -(corners @ up)
    k = size * 0.42 / max(float(np.abs(sx).max()), float(np.abs(sy).max()), 1e-3)
    pts = [(x * k + size / 2, y * k + size / 2) for x, y in zip(sx, sy)]
    draw = ImageDraw.Draw(img)
    for i in range(8):
        for bit in (1, 2, 4):
            j = i | bit
            if j != i:
                draw.line([pts[i], pts[j]], fill=(200, 120, 230, 255), width=1)
    return img.tobytes()


__all__ = ["material_average", "render_preview", "view_basis"]
