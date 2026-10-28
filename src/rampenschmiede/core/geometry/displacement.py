"""Displacements: Gelände-Flächen aus einem Raster verschobener Punkte auf einer Brush-Seite.

Gespeichert wird wie in VMF im `dispinfo`-Block der Seite (`face.extra["raw"]`), damit Import
und Export verlustfrei bleiben. Dieses Modul liest und schreibt den Block und rechnet wie vbsp
(CCoreDispInfo::GenerateDispSurf) die Punkte aus:

- Die vier Ecken der Seite werden im Uhrzeigersinn (von außen gesehen) geordnet, beginnend
  bei der Ecke, die `startposition` am nächsten liegt: p0 … p3.
- Punkt (i, j) mit i, j = 0 … n-1 liegt auf der Linie zwischen p0→p1 und p3→p2 bei i/(n-1),
  dort bei j/(n-1) Richtung p3→p2. VMF-Zeile `row<i>`, Spalte j, Index i·n + j.
- Endgültige Lage = Grundpunkt + offset + normal · distance + Seiten-Normale · elevation.

Texturkoordinaten kommen vom flachen Grundpunkt, wie im Spiel.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field

import numpy as np

from ..mathutil import Point
from ..model.objects import Face, Solid

DISP_KEY = "dispinfo"
POWERS = (2, 3, 4)
#: Höchstens so viele Vertices hat ein Displacement (Power 4: 17 × 17)
MAX_POWER = 4


def _vecs(text: str, n: int) -> np.ndarray:
    vals = [float(v) for v in text.split()]
    vals += [0.0] * (n * 3 - len(vals))
    return np.asarray(vals[:n * 3], dtype=np.float64).reshape(n, 3)


def _nums(text: str, n: int) -> np.ndarray:
    vals = [float(v) for v in text.split()]
    vals += [0.0] * (n - len(vals))
    return np.asarray(vals[:n], dtype=np.float64)


def _fmt(v: float) -> str:
    if abs(v) < 5e-7:
        return "0"
    return format(float(v), ".6g")


@dataclass
class Displacement:
    power: int
    start: Point
    elevation: float = 0.0
    #: Je Vertex (n·n): Richtung, Weg entlang der Richtung, zusätzlicher Versatz, Überblendung 0–255
    normals: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    distances: np.ndarray = field(default_factory=lambda: np.zeros(0))
    offsets: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    alphas: np.ndarray = field(default_factory=lambda: np.zeros(0))
    #: Was wir nicht auswerten (flags, subdiv, offset_normals, triangle_tags, allowed_verts …)
    other: list = field(default_factory=list)

    @property
    def size(self) -> int:
        """Punkte je Kante: 2^power + 1."""
        return (1 << self.power) + 1

    @property
    def vectors(self) -> np.ndarray:
        """Verschiebung je Vertex ohne Elevation: normal · distance + offset."""
        return self.normals * self.distances[:, None] + self.offsets

    def with_vectors(self, vectors: np.ndarray) -> "Displacement":
        """Neue Verschiebungen setzen (als Richtung und Länge, der Versatz wird eingerechnet)."""
        v = np.asarray(vectors, dtype=np.float64)
        dist = np.linalg.norm(v, axis=1)
        normals = np.where(dist[:, None] > 1e-9, v / np.maximum(dist, 1e-9)[:, None], self.normals)
        return dataclasses.replace(self, normals=normals, distances=dist, offsets=np.zeros_like(v))

    # ---- VMF -----------------------------------------------------------------------
    @classmethod
    def from_raw(cls, node: list) -> "Displacement":
        _name, children = node
        flat = {k.lower(): v for k, v in children if isinstance(v, str)}
        power = int(float(flat.get("power", "3")))
        if power not in POWERS:
            raise ValueError(f"Displacement-Power {power} wird nicht unterstützt")
        n = (1 << power) + 1
        start = tuple(float(c) for c in flat.get("startposition", "[0 0 0]").strip("[] ").split()[:3])
        blocks = {k.lower(): v for k, v in children if isinstance(v, list)}

        def rows(name: str, per_row: int, parse) -> np.ndarray:
            block = dict((k.lower(), v) for k, v in blocks.get(name, []))
            return np.concatenate([parse(block.get(f"row{i}", ""), per_row) for i in range(n)])

        known_flat = {"power", "startposition", "elevation"}
        known_blocks = {"normals", "distances", "offsets", "alphas"}
        other = [c for c in children if (c[0].lower() not in known_flat if isinstance(c[1], str)
                                         else c[0].lower() not in known_blocks)]
        return cls(
            power=power, start=start,  # type: ignore[arg-type]
            elevation=float(flat.get("elevation", "0")),
            normals=rows("normals", n, _vecs), distances=rows("distances", n, _nums),
            offsets=rows("offsets", n, _vecs), alphas=rows("alphas", n, _nums),
            other=other,
        )

    def to_raw(self) -> list:
        n = self.size

        def block(name: str, data: np.ndarray, vec: bool) -> list:
            out = []
            for i in range(n):
                part = data[i * n:(i + 1) * n]
                vals = part.reshape(-1) if vec else part
                out.append([f"row{i}", " ".join(_fmt(v) for v in vals)])
            return [name, out]

        flat_other = [c for c in self.other if isinstance(c[1], str)]
        block_other = [c for c in self.other if not isinstance(c[1], str)]
        return [DISP_KEY, [
            ["power", str(self.power)],
            ["startposition", "[" + " ".join(_fmt(c) for c in self.start) + "]"],
            *flat_other,
            ["elevation", _fmt(self.elevation)],
            block("normals", self.normals, True),
            block("distances", self.distances, False),
            block("offsets", self.offsets, True),
            block("alphas", self.alphas, False),
            *block_other,
        ]]


def new_displacement(power: int, start: Point) -> Displacement:
    """Flaches Displacement wie „Create“ in Hammer (Richtungen zeigen nach der Seiten-Normale)."""
    n = (1 << power) + 1
    tags = [[f"row{i}", " ".join(["0"] * (2 * (n - 1)))] for i in range(n - 1)]
    return Displacement(
        power=power, start=start, normals=np.zeros((n * n, 3)), distances=np.zeros(n * n),
        offsets=np.zeros((n * n, 3)), alphas=np.zeros(n * n),
        other=[["flags", "0"], ["subdiv", "0"],
               ["offset_normals", [[f"row{i}", " ".join(["0 0 0"] * n)] for i in range(n)]],
               ["triangle_tags", tags], ["allowed_verts", [["10", " ".join(["-1"] * 10)]]]],
    )


# ---- Seiten --------------------------------------------------------------------------

def _raw_index(face: Face) -> int | None:
    for k, node in enumerate(face.extra.get("raw", ())):
        if isinstance(node, list) and len(node) == 2 and str(node[0]).lower() == DISP_KEY:
            return k
    return None


def has_displacement(face: Face) -> bool:
    return _raw_index(face) is not None


def face_displacement(face: Face) -> Displacement | None:
    k = _raw_index(face)
    if k is None:
        return None
    try:
        return Displacement.from_raw(face.extra["raw"][k])
    except (ValueError, TypeError, IndexError):
        return None


def with_displacement(face: Face, disp: Displacement | None) -> Face:
    """Seite mit neuem (oder ohne, bei None) Displacement."""
    raw = list(face.extra.get("raw", ()))
    k = _raw_index(face)
    if k is not None:
        raw.pop(k)
    if disp is not None:
        raw.insert(k if k is not None else len(raw), disp.to_raw())
    extra = {key: v for key, v in face.extra.items() if key != "raw"}
    if raw:
        extra["raw"] = raw
    return dataclasses.replace(face, extra=extra)


def is_displacement_solid(solid: Solid) -> bool:
    return any(has_displacement(f) for f in solid.faces)


# ---- Geometrie --------------------------------------------------------------------------

def surface_corners(poly: list[Point], normal: Point, start: Point) -> np.ndarray | None:
    """Die vier Ecken in vbsp-Reihenfolge (im Uhrzeigersinn von außen, ab `start`), None wenn
    die Seite kein Viereck ist."""
    if poly is None or len(poly) != 4:
        return None
    pts = np.asarray(poly, dtype=np.float64)
    n = np.asarray(normal, dtype=np.float64)
    turn = np.cross(pts[1] - pts[0], pts[2] - pts[1]) @ n
    if turn > 0:  # gegen den Uhrzeigersinn: umdrehen
        pts = pts[::-1]
    first = int(np.argmin(np.linalg.norm(pts - np.asarray(start, dtype=np.float64), axis=1)))
    return np.roll(pts, -first, axis=0)


def base_grid(corners: np.ndarray, power: int) -> np.ndarray:
    """Flache Grundpunkte (n·n, 3), Index i·n + j wie in vbsp."""
    n = (1 << power) + 1
    t = np.linspace(0.0, 1.0, n)
    p0, p1, p2, p3 = corners
    edge0 = p0[None, :] + (p1 - p0)[None, :] * t[:, None]   # i entlang p0→p1
    edge1 = p3[None, :] + (p2 - p3)[None, :] * t[:, None]   # und p3→p2
    grid = edge0[:, None, :] + (edge1 - edge0)[:, None, :] * t[None, :, None]
    return grid.reshape(n * n, 3)


@dataclass
class DispSurface:
    """Ausgerechnetes Displacement einer Seite."""

    face_index: int
    disp: Displacement
    base: np.ndarray       # (n·n, 3) flache Grundpunkte
    positions: np.ndarray  # (n·n, 3) endgültige Punkte
    normal: np.ndarray     # Normale der Seite

    @property
    def size(self) -> int:
        return self.disp.size

    def triangles(self) -> np.ndarray:
        """(m, 3) Indizes; je Rasterfeld zwei Dreiecke, die Diagonale wechselt wie in vbsp."""
        n = self.size
        out = []
        for i in range(n - 1):
            for j in range(n - 1):
                a, b, c, d = i * n + j, i * n + j + 1, (i + 1) * n + j + 1, (i + 1) * n + j
                if (i + j) % 2 == 0:
                    out += [(a, d, c), (a, c, b)]
                else:
                    out += [(a, d, b), (b, d, c)]
        tris = np.asarray(out, dtype=np.int64)
        # Nach außen (Seiten-Normale) zeigende Reihenfolge
        p = self.base
        if len(tris) and np.cross(p[tris[0, 1]] - p[tris[0, 0]], p[tris[0, 2]] - p[tris[0, 0]]) @ self.normal < 0:
            tris = tris[:, ::-1]
        return tris

    def vertex_normals(self) -> np.ndarray:
        tris = self.triangles()
        p = self.positions
        fn = np.cross(p[tris[:, 1]] - p[tris[:, 0]], p[tris[:, 2]] - p[tris[:, 0]])
        acc = np.zeros_like(p)
        for k in range(3):
            np.add.at(acc, tris[:, k], fn)
        length = np.linalg.norm(acc, axis=1, keepdims=True)
        return np.where(length > 1e-9, acc / np.maximum(length, 1e-9), self.normal[None, :])


def surfaces(solid: Solid) -> list[DispSurface]:
    """Alle Displacements eines Brushes, ausgerechnet. Seiten, die kein Viereck sind, fehlen
    (vbsp lehnt sie auch ab)."""
    out = []
    polys = solid.polygons()
    for k, (face, poly) in enumerate(zip(solid.faces, polys)):
        disp = face_displacement(face)
        if disp is None:
            continue
        normal = np.asarray(face.plane.normal, dtype=np.float64)
        corners = surface_corners(poly, face.plane.normal, disp.start)
        if corners is None:
            continue
        base = base_grid(corners, disp.power)
        pos = base + disp.vectors + normal[None, :] * disp.elevation
        out.append(DispSurface(k, disp, base, pos, normal))
    return out


def make_displacement(solid: Solid, face_index: int, power: int = 3) -> Solid:
    """Seite in ein flaches Displacement umwandeln (Startecke: die erste Ecke in vbsp-Reihenfolge)."""
    face = solid.faces[face_index]
    poly = solid.polygons()[face_index]
    corners = surface_corners(poly, face.plane.normal, poly[0] if poly else (0, 0, 0))
    if corners is None:
        raise ValueError("Nur viereckige Seiten können Gelände werden")
    start = tuple(float(c) for c in corners[0])
    faces = list(solid.faces)
    faces[face_index] = with_displacement(face, new_displacement(power, start))  # type: ignore[arg-type]
    return solid.replace(faces=tuple(faces))


def set_surface(solid: Solid, surf: DispSurface, disp: Displacement) -> Solid:
    faces = list(solid.faces)
    faces[surf.face_index] = with_displacement(faces[surf.face_index], disp)
    return solid.replace(faces=tuple(faces))


def heights_to_disp(surf: DispSurface, targets: np.ndarray, alphas: np.ndarray | None = None) -> Displacement:
    """Displacement so setzen, dass die Punkte bei `targets` liegen (Elevation bleibt)."""
    vec = targets - surf.base - surf.normal[None, :] * surf.disp.elevation
    disp = surf.disp.with_vectors(vec)
    if alphas is not None:
        disp = dataclasses.replace(disp, alphas=np.clip(alphas, 0, 255))
    return disp


# ---- Formen -----------------------------------------------------------------------------

#: Pinsel-Arten des Gelände-Werkzeugs
BRUSH_MODES = ("heben", "senken", "glaetten", "rauschen", "ebnen", "alpha", "alpha_weg")


def falloff(dist: np.ndarray, radius: float) -> np.ndarray:
    """Weicher Pinsel: 1 in der Mitte, 0 am Rand (Kosinus)."""
    x = np.clip(dist / max(radius, 1e-6), 0.0, 1.0)
    return 0.5 * (1.0 + np.cos(np.pi * x))


def _grid_smooth(values: np.ndarray, n: int) -> np.ndarray:
    """Mittelwert jedes Punkts mit seinen Rasternachbarn (Ränder mit weniger Nachbarn)."""
    g = values.reshape(n, n, -1)
    acc = g.copy()
    cnt = np.ones((n, n, 1))
    acc[1:] += g[:-1]
    cnt[1:] += 1
    acc[:-1] += g[1:]
    cnt[:-1] += 1
    acc[:, 1:] += g[:, :-1]
    cnt[:, 1:] += 1
    acc[:, :-1] += g[:, 1:]
    cnt[:, :-1] += 1
    return (acc / cnt).reshape(values.shape)


def brush_stroke(surf: DispSurface, center: Point, radius: float, strength: float, mode: str,
                 up: Point = (0.0, 0.0, 1.0), seed: int = 0, ignore_axis: int | None = None) -> Displacement | None:
    """Einen Pinselschritt anwenden. `strength` in Units je Schritt (Alpha: Stufen von 255).
    `up`: Richtung, in die gehoben wird. `ignore_axis`: diese Achse zählt beim Abstand nicht
    (Pinsel von oben in einer 2D-Ansicht). None, wenn kein Punkt im Pinsel liegt."""
    c = np.asarray(center, dtype=np.float64)
    pos = surf.positions
    delta = pos - c[None, :]
    if ignore_axis is not None:
        delta[:, ignore_axis] = 0.0
    w = falloff(np.linalg.norm(delta, axis=1), radius)
    if not (w > 1e-6).any():
        return None
    direction = np.asarray(up, dtype=np.float64)
    direction /= max(np.linalg.norm(direction), 1e-9)
    if mode in ("alpha", "alpha_weg"):
        sign = 1.0 if mode == "alpha" else -1.0
        alphas = np.clip(surf.disp.alphas + sign * strength * w, 0, 255)
        return dataclasses.replace(surf.disp, alphas=alphas)
    new = pos.copy()
    if mode in ("heben", "senken"):
        new += direction[None, :] * (strength if mode == "heben" else -strength) * w[:, None]
    elif mode == "glaetten":
        smooth = _grid_smooth(pos, surf.size)
        k = np.clip(w * min(1.0, strength / 16.0), 0, 1)[:, None]
        new = pos + (smooth - pos) * k
    elif mode == "rauschen":
        rng = np.random.default_rng(seed)
        new += direction[None, :] * (rng.uniform(-1, 1, len(pos)) * strength * w)[:, None]
    elif mode == "ebnen":
        # Auf die mittlere Höhe unter dem Pinsel ziehen
        h = pos @ direction
        level = float((h * w).sum() / max(w.sum(), 1e-9))
        k = np.clip(w * min(1.0, strength / 16.0), 0, 1)
        new = pos + direction[None, :] * ((level - h) * k)[:, None]
    else:
        raise ValueError(f"Unbekannte Pinsel-Art {mode}")
    return heights_to_disp(surf, new)


def sew(solids: list[Solid], tolerance: float = 0.5) -> list[Solid]:
    """Nähte schließen: Punkte verschiedener Displacements, deren Grundpunkte zusammenfallen,
    bekommen dieselbe Lage (den Mittelwert). Gibt die geänderten Brushes zurück."""
    entries: dict[tuple, list[tuple[int, int, int]]] = {}
    surfs: list[list[DispSurface]] = []
    for si, solid in enumerate(solids):
        ss = surfaces(solid)
        surfs.append(ss)
        for k, surf in enumerate(ss):
            n = surf.size
            border = [i * n + j for i in range(n) for j in range(n) if i in (0, n - 1) or j in (0, n - 1)]
            for v in border:
                key = tuple(np.round(surf.base[v] / tolerance).astype(np.int64))
                entries.setdefault(key, []).append((si, k, v))
    targets = {(si, k): ss.positions.copy() for si, s in enumerate(surfs) for k, ss in enumerate(s)}
    changed: set[int] = set()
    for group in entries.values():
        if len({(si, k) for si, k, _ in group}) < 2:
            continue
        mean = np.mean([surfs[si][k].positions[v] for si, k, v in group], axis=0)
        for si, k, v in group:
            if not np.allclose(targets[(si, k)][v], mean, atol=1e-3):
                targets[(si, k)][v] = mean
                changed.add(si)
    out = []
    for si in sorted(changed):
        solid = solids[si]
        for k, surf in enumerate(surfs[si]):
            solid = set_surface(solid, surf, heights_to_disp(surf, targets[(si, k)]))
        out.append(solid)
    return out


def transform_displacement(disp: Displacement, point_fn, linear_fn) -> Displacement:
    """Displacement mit dem Brush verschieben, drehen oder skalieren: Startecke wie ein Punkt,
    Verschiebungen wie Richtungen."""
    vec = np.asarray([linear_fn(tuple(v)) for v in disp.vectors], dtype=np.float64) if len(disp.vectors) else disp.vectors
    moved = disp.with_vectors(vec) if len(vec) else disp
    return dataclasses.replace(moved, start=tuple(float(c) for c in point_fn(disp.start)))


def ray_hit(surf: DispSurface, origin, direction) -> tuple[float, np.ndarray] | None:
    """Erster Schnitt eines Strahls mit dem Displacement: (Abstand, Punkt) oder None."""
    tris = surf.triangles()
    p = surf.positions
    o = np.asarray(origin, dtype=np.float64)
    d = np.asarray(direction, dtype=np.float64)
    v0, v1, v2 = p[tris[:, 0]], p[tris[:, 1]], p[tris[:, 2]]
    e1, e2 = v1 - v0, v2 - v0
    h = np.cross(d[None, :], e2)
    a = np.einsum("ij,ij->i", e1, h)
    ok = np.abs(a) > 1e-12
    f = np.where(ok, 1.0 / np.where(ok, a, 1.0), 0.0)
    s = o[None, :] - v0
    u = f * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, e1)
    v = f * (q @ d)
    t = f * np.einsum("ij,ij->i", e2, q)
    hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-6)
    if not hit.any():
        return None
    t_min = float(t[hit].min())
    return t_min, o + d * t_min


def solid_ray_face(solid: Solid, origin, direction) -> tuple[float, int] | None:
    """Erster Treffer eines Strahls auf den Displacements eines Brushes: (Abstand, Seiten-Index)."""
    best = None
    for surf in surfaces(solid):
        hit = ray_hit(surf, origin, direction)
        if hit is not None and (best is None or hit[0] < best[0]):
            best = (hit[0], surf.face_index)
    return best


def solid_ray_hit(solid: Solid, origin, direction) -> float | None:
    best = solid_ray_face(solid, origin, direction)
    return best[0] if best is not None else None


def angle_of(normal) -> float:
    """Steigung in Grad (0 = flach) einer Normale."""
    nz = abs(float(normal[2])) / max(float(np.linalg.norm(normal)), 1e-9)
    return math.degrees(math.acos(min(1.0, nz)))


__all__ = ["BRUSH_MODES", "DISP_KEY", "DispSurface", "Displacement", "MAX_POWER", "POWERS", "base_grid",
           "brush_stroke", "face_displacement", "falloff", "has_displacement", "heights_to_disp",
           "is_displacement_solid", "make_displacement", "new_displacement", "ray_hit", "set_surface", "sew",
           "solid_ray_face", "solid_ray_hit", "surface_corners", "surfaces", "transform_displacement", "with_displacement"]
