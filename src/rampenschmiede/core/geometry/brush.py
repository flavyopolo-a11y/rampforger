"""Brush-Geometrie: aus Ebenen werden Face-Polygone, aus Polygonen werden Faces.

Ein Brush ist der Schnitt der Halbräume seiner Ebenen und damit immer konvex. Für jede
Ebene wird ein großes Polygon auf der Ebene angelegt und an allen anderen Ebenen
abgeschnitten (Sutherland-Hodgman). Was übrig bleibt, ist die sichtbare Seite.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

from ..mathutil import EPSILON, Plane, Point, add, cross, dot, length, normalize, scale, sub
from ..model.objects import DEFAULT_MATERIAL, Face, default_tex_axes

if TYPE_CHECKING:
    from ..model.objects import Solid

WORLD_EXTENT = 131072.0  # größer als jede Source-Map (±16384 bzw. ±32768 in Strata)
CLIP_EPSILON = 0.01
SNAP_EPSILON = 1e-3


def _base_winding(plane: Plane) -> list[Point]:
    n = plane.normal
    ax = max(range(3), key=lambda i: abs(n[i]))
    up: Point = (0.0, 0.0, 1.0) if ax != 2 else (1.0, 0.0, 0.0)
    # up auf die Ebene projizieren
    up = normalize(sub(up, scale(n, dot(up, n))))
    right = cross(up, n)
    origin = scale(n, plane.dist)
    up = scale(up, WORLD_EXTENT)
    right = scale(right, WORLD_EXTENT)
    # Reihenfolge so, dass das Polygon von außen (entlang der Normale) gegen den Uhrzeigersinn läuft.
    return [
        add(sub(origin, right), up),
        sub(sub(origin, right), up),
        sub(add(origin, right), up),
        add(add(origin, right), up),
    ]


def _clip(poly: list[Point], plane: Plane) -> list[Point]:
    """Behält den Teil des Polygons, der hinter der Ebene liegt (distance <= 0)."""
    dists = [plane.distance(p) for p in poly]
    if all(d <= CLIP_EPSILON for d in dists):
        return poly
    if all(d >= -CLIP_EPSILON for d in dists):
        return []
    out: list[Point] = []
    count = len(poly)
    for i in range(count):
        p, d = poly[i], dists[i]
        q, e = poly[(i + 1) % count], dists[(i + 1) % count]
        if d <= CLIP_EPSILON:
            out.append(p)
        if (d < -CLIP_EPSILON and e > CLIP_EPSILON) or (d > CLIP_EPSILON and e < -CLIP_EPSILON):
            t = d / (d - e)
            out.append(add(p, scale(sub(q, p), t)))
    return out


def _snap(p: Point) -> Point:
    """Entfernt Rechenrauschen: fast ganze Zahlen werden ganz."""
    return tuple(float(round(c)) if abs(c - round(c)) < SNAP_EPSILON else c for c in p)  # type: ignore[return-value]


def _dedupe(poly: list[Point]) -> list[Point]:
    out: list[Point] = []
    for p in poly:
        if not out or length(sub(p, out[-1])) > SNAP_EPSILON:
            out.append(p)
    if len(out) > 1 and length(sub(out[0], out[-1])) <= SNAP_EPSILON:
        out.pop()
    return out


def face_polygons(planes: Sequence[Plane]) -> list[list[Point] | None]:
    result: list[list[Point] | None] = []
    for i, plane in enumerate(planes):
        if not plane.is_valid():
            result.append(None)
            continue
        poly = _base_winding(plane)
        for j, other in enumerate(planes):
            if i == j or not other.is_valid():
                continue
            if other.same_as(plane):
                # Doppelte Ebene: nur die erste trägt eine Fläche.
                if j < i:
                    poly = []
                    break
                continue
            poly = _clip(poly, other)
            if not poly:
                break
        poly = _dedupe([_snap(p) for p in poly])
        result.append(poly if len(poly) >= 3 else None)
    return result


def polygon_area(poly: Sequence[Point]) -> float:
    total: Point = (0.0, 0.0, 0.0)
    for i in range(1, len(poly) - 1):
        total = add(total, cross(sub(poly[i], poly[0]), sub(poly[i + 1], poly[0])))
    return length(total) / 2


def is_valid_solid(solid: "Solid") -> bool:
    """Gültig heißt: mindestens 4 Faces, jede Face hat ein Polygon mit Fläche,
    und der Körper hat Volumen."""
    polys = solid.polygons()
    if len(polys) < 4 or any(p is None or polygon_area(p) < 1e-3 for p in polys):
        return False
    bbox = solid.bbox()
    return bbox is not None and all(s > EPSILON for s in bbox.size)


def best_triangle(poly: Sequence[Point]) -> tuple[Point, Point, Point]:
    """Drei Punkte des Polygons mit möglichst großem Dreieck (stabile Ebene).
    Rückgabe in Polygon-Reihenfolge (gegen den Uhrzeigersinn von außen)."""
    best = (0, 1, 2)
    best_area = -1.0
    n = len(poly)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                a = length(cross(sub(poly[j], poly[i]), sub(poly[k], poly[i])))
                if a > best_area:
                    best_area, best = a, (i, j, k)
    return poly[best[0]], poly[best[1]], poly[best[2]]


def vmf_points_from_loop(poly: Sequence[Point]) -> tuple[Point, Point, Point]:
    """Polygon (gegen den Uhrzeigersinn von außen) zu VMF-Ebenenpunkten (im Uhrzeigersinn)."""
    a, b, c = best_triangle(poly)
    return (a, c, b)


def faces_from_loops(loops: Sequence[Sequence[Point]], material: str = DEFAULT_MATERIAL) -> tuple[Face, ...]:
    faces = []
    for loop in loops:
        pts = vmf_points_from_loop(loop)
        u, v = default_tex_axes(Plane.from_vmf_points(*pts).normal)
        faces.append(Face(points=pts, material=material, uaxis=u, vaxis=v))
    return tuple(faces)


def ray_intersect_solid(solid: "Solid", origin: Point, direction: Point) -> float | None:
    """Abstand entlang des Strahls bis zum Eintritt in den Brush, oder None."""
    t_enter, t_exit = -1e30, 1e30
    for face in solid.faces:
        plane = face.plane
        denom = dot(plane.normal, direction)
        dist = plane.distance(origin)
        if abs(denom) < 1e-12:
            if dist > 0:
                return None
            continue
        t = -dist / denom
        if denom < 0:
            t_enter = max(t_enter, t)
        else:
            t_exit = min(t_exit, t)
        if t_enter > t_exit:
            return None
    if t_exit < 0:
        return None
    return max(t_enter, 0.0)
