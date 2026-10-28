"""Gelände-Vorlagen: Hügel, Berg, Felsen, Insel und Klippe aus Displacements.

Die Fläche wird in Kacheln von höchstens 1024 Units zerlegt; jede Kachel ist ein flacher
Welt-Brush, dessen Oberseite ein Displacement trägt. Die Höhe kommt aus einer Funktion der
Position, deshalb passen die Kanten benachbarter Kacheln genau aufeinander. Die übrigen
Seiten sind Nodraw (vbsp zeichnet sie bei Displacements ohnehin nicht).

Gelände sind Welt-Brushes, keine Bausteine: Nach dem Einfügen formt man sie mit dem
Gelände-Werkzeug weiter. Displacements dichten die Map nicht ab, darunter muss die
Hülle geschlossen bleiben.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

import numpy as np

from ..geometry import primitives
from ..geometry.displacement import heights_to_disp, make_displacement, set_surface, surfaces
from ..model.objects import Face, Solid
from .catalog import Materials, Param, Placement, Template, _add
from .sweep import SweepPiece

NODRAW = "TOOLS/TOOLSNODRAW"
#: Größte Kachel: größere Displacements werden im Spiel grob und schlecht beleuchtet
MAX_TILE = 1024
#: Gras auf Kies aus HL2, in CS:S vorhanden; die zweite Textur (Kies) malt man mit „Textur malen“
DEFAULT_TERRAIN_MATERIAL = "NATURE/BLENDGRASSGRAVEL001A"


def _smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def _hash(ix, iy, seed: int):
    h = (ix * 374761393 + iy * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 65535.0


def value_noise(x, y, seed: int = 0, octaves: int = 4) -> np.ndarray:
    """Weiches Rauschen −1 … 1 (mehrere Oktaven), gleiche Werte an gleichen Stellen."""
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    total = np.zeros_like(x)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        f = 2.0 ** o
        fx, fy = x * f, y * f
        ix, iy = np.floor(fx).astype(np.int64), np.floor(fy).astype(np.int64)
        tx, ty = _smooth(fx - ix), _smooth(fy - iy)
        s = seed + o * 101
        a, b = _hash(ix, iy, s), _hash(ix + 1, iy, s)
        c, d = _hash(ix, iy + 1, s), _hash(ix + 1, iy + 1, s)
        total += amp * ((a + (b - a) * tx) * (1 - ty) + (c + (d - c) * tx) * ty)
        norm += amp
        amp *= 0.5
    return total / norm * 2 - 1


# ---- Höhenformen: lokale Koordinaten u (entlang), w (quer) in 0 … 1 -----------------------

def _radial(u, w):
    return np.hypot((u - 0.5) * 2, (w - 0.5) * 2)


def shape_hill(u, w, seed):
    r = _radial(u, w)
    return 0.5 + 0.5 * np.cos(np.pi * np.clip(r, 0, 1))


def shape_mountain(u, w, seed):
    r = _radial(u, w)
    ridge = 1 - np.abs(value_noise(u * 3, w * 3, seed, 3))
    base = np.clip(1 - r, 0, 1) ** 1.6
    return np.clip(base * (0.75 + 0.25 * ridge), 0, None) * _edge(u, w)


def shape_rocks(u, w, seed):
    r = _radial(u, w)
    bump = 0.5 + 0.5 * np.cos(np.pi * np.clip(r, 0, 1))
    rough = value_noise(u * 6, w * 6, seed, 4)
    return np.clip(bump * (0.6 + 0.6 * rough), 0, None) * _edge(u, w)


def shape_island(u, w, seed):
    r = _radial(u, w) * (1 + 0.15 * value_noise(u * 2.5, w * 2.5, seed, 2))
    return _smooth((1.0 - r) / 0.35) * (0.85 + 0.15 * value_noise(u * 5, w * 5, seed + 7, 2))


def shape_cliff(u, w, seed):
    wobble = 0.06 * value_noise(w * 4, np.zeros_like(w), seed, 3)
    step = _smooth((u - 0.45 - wobble) / 0.1)
    return np.clip(step * (0.96 + 0.04 * value_noise(u * 8, w * 8, seed + 3, 3)), 0, None)


def _edge(u, w):
    """Am Rand auf 0 auslaufen lassen (Nachbarn ohne Gelände passen ohne Stufe an)."""
    m = np.minimum.reduce([u, 1 - u, w, 1 - w])
    return _smooth(m / 0.08)


SHAPES = {"huegel": shape_hill, "berg": shape_mountain, "felsen": shape_rocks, "insel": shape_island,
          "klippe": shape_cliff}


@dataclass
class TerrainShape:
    faces: tuple[Face, ...]

    def build(self) -> list[SweepPiece]:
        return [SweepPiece(self.faces, 0, 0)]


def _quarter(yaw: float) -> int:
    return int(round(yaw / 90.0)) % 4


def _footprint(v: dict, at: Placement) -> tuple[float, float, float, float]:
    """Achsparallele Grundfläche (x0, y0, x1, y1). Der Anfang liegt bei `at`, Mitte der Breite."""
    length, width = v["laenge"], v["breite"]
    q = _quarter(at.yaw)
    fx, fy = [(1, 0), (0, 1), (-1, 0), (0, -1)][q]
    lx, ly = -fy, fx
    xs = [at.x, at.x + fx * length]
    ys = [at.y, at.y + fy * length]
    xs += [at.x + lx * width / 2, at.x - lx * width / 2]
    ys += [at.y + ly * width / 2, at.y - ly * width / 2]
    if fx:
        xs, ys = xs[:2], ys[2:]
    else:
        xs, ys = xs[2:], ys[:2]
    return min(xs), min(ys), max(xs), max(ys)


def _local(x, y, v: dict, at: Placement):
    """Welt (x, y) → (u entlang, w quer), beide 0 … 1."""
    q = _quarter(at.yaw)
    fx, fy = [(1, 0), (0, 1), (-1, 0), (0, -1)][q]
    lx, ly = -fy, fx
    dx, dy = x - at.x, y - at.y
    u = (dx * fx + dy * fy) / v["laenge"]
    w = (dx * lx + dy * ly) / v["breite"] + 0.5
    return u, w


def _tiles(lo: float, hi: float) -> list[tuple[int, int]]:
    span = hi - lo
    n = max(1, math.ceil(span / MAX_TILE - 1e-9))
    edges = [int(round(lo + span * k / n)) for k in range(n + 1)]
    return list(zip(edges[:-1], edges[1:]))


def terrain_faces(kind: str, v: dict, at: Placement, material: str) -> list[tuple[Face, ...]]:
    x0, y0, x1, y1 = _footprint(v, at)
    z0 = int(round(at.z))
    top = z0 + int(v["dicke"])
    fn = SHAPES[kind]
    power = int(v["feinheit"])
    out = []
    for ax, bx in _tiles(x0, x1):
        for ay, by in _tiles(y0, y1):
            faces = primitives.block((ax, ay, z0), (bx, by, top), material)[0]
            solid = Solid(id=0, faces=faces)
            k = max(range(len(faces)), key=lambda i: faces[i].plane.normal[2])
            faces = tuple(f if i == k else dataclasses.replace(f, material=NODRAW) for i, f in enumerate(faces))
            solid = make_displacement(Solid(id=0, faces=faces), k, power)
            (surf,) = surfaces(solid)
            u, w = _local(surf.base[:, 0], surf.base[:, 1], v, at)
            h = fn(u, w, int(v["zufall"])) * float(v["hoehe"])
            targets = surf.base.copy()
            targets[:, 2] += h
            alphas = None
            if v["hang_textur"]:
                alphas = _slope_alpha(surf, targets)
            solid = set_surface(solid, surf, heights_to_disp(surf, targets, alphas))
            out.append(solid.faces)
    return out


def _slope_alpha(surf, targets: np.ndarray) -> np.ndarray:
    """Steile Stellen bekommen die zweite Textur (Fels oder Kies statt Gras)."""
    n = surf.size
    g = targets.reshape(n, n, 3)
    di = np.gradient(g[:, :, 2], axis=0) / np.maximum(np.linalg.norm(np.gradient(g[:, :, :2], axis=0), axis=2), 1e-6)
    dj = np.gradient(g[:, :, 2], axis=1) / np.maximum(np.linalg.norm(np.gradient(g[:, :, :2], axis=1), axis=2), 1e-6)
    slope = np.degrees(np.arctan(np.hypot(di, dj))).reshape(-1)
    return _smooth((slope - 22.0) / 18.0) * 255.0


def _builder(kind: str):
    def build(v: dict, at: Placement, m: Materials) -> list[TerrainShape]:
        return [TerrainShape(f) for f in terrain_faces(kind, v, at, str(v["mat_gelaende"]).upper())]
    return build


def _params(length: int, width: int, height: int, hint: str = "") -> tuple[Param, ...]:
    return (
        Param("laenge", "Länge", length, 256, 16384, 16, "u"),
        Param("breite", "Breite", width, 256, 16384, 16, "u"),
        Param("hoehe", "Höhe", height, -4096, 8192, 16, "u", hint=hint),
        Param("dicke", "Sockel", 16, 8, 512, 8, "u", hint="Dicke der flachen Brushes unter dem Gelände"),
        Param("feinheit", "Feinheit", "3", choices=(("2", "Grob (4 × 4 je Kachel)"), ("3", "Normal (8 × 8)"),
                                                     ("4", "Fein (16 × 16)"))),
        Param("zufall", "Variante", 1, 0, 9999, hint="Andere Zahl, andere Form"),
        Param("hang_textur", "Zweite Textur an steilen Hängen", True),
        Param("mat_gelaende", "Material", DEFAULT_TERRAIN_MATERIAL,
              hint="Überblend-Material mit zwei Texturen, z. B. nature/blendgrassgravel001a"),
    )


_GROUP = "Gelände"
for key, name, desc, dims in (
    ("huegel", "Hügel", "Runde, sanfte Erhebung.", (1024, 1024, 192)),
    ("berg", "Berg", "Hoher Gipfel mit Graten, läuft am Rand flach aus.", (2048, 2048, 1024)),
    ("felsen", "Felsen", "Unruhige, steinige Erhebung.", (768, 768, 256)),
    ("insel", "Insel", "Flaches Plateau mit weichem Ufer, gut über Wasser.", (2048, 2048, 128)),
    ("klippe", "Klippe", "Steile Kante quer über die Fläche, unten und oben flach.", (1024, 1024, 512)),
):
    _add(Template(f"gelaende_{key}", name, _GROUP, desc + " Formbar mit dem Gelände-Werkzeug (Shift+G).",
                  _params(*dims), _builder(key), check_angles=False, world=True))


__all__ = ["DEFAULT_TERRAIN_MATERIAL", "MAX_TILE", "SHAPES", "terrain_faces", "value_noise"]
