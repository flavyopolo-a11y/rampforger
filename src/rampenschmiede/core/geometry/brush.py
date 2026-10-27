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
CLIP_EPSILON = 1e-4
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


def _int_plane(face: "Face") -> tuple[tuple[int, int, int], int] | None:
    """Exakte Ebene (ganzzahlige Normale nach außen, Abstand) aus ganzzahligen Face-Punkten."""
    pts = face.points
    if not all(float(c).is_integer() for p in pts for c in p):
        return None
    p1, p2, p3 = ((int(p[0]), int(p[1]), int(p[2])) for p in pts)
    a = (p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2])
    b = (p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2])
    n = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    return n, n[0] * p1[0] + n[1] * p1[1] + n[2] * p1[2]


def order_on_plane(normal: tuple[int, int, int], pts: Sequence[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    """Ganzzahlige Punkte einer Ebene als konvexes Polygon, gegen den Uhrzeigersinn von
    außen gesehen, ohne Punkte, die nur auf einer Kante liegen. Exakt gerechnet."""
    drop = max(range(3), key=lambda i: abs(normal[i]))
    keep = [i for i in range(3) if i != drop]
    flat = sorted(set((p[keep[0]], p[keep[1]], p) for p in pts))

    def turn(o, a, b) -> int:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list = []
    for q in flat:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper: list = []
    for q in reversed(flat):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    loop = [q[2] for q in lower[:-1] + upper[:-1]]
    if len(loop) >= 3:
        a, b, c = loop[0], loop[1], loop[2]
        u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        if n[0] * normal[0] + n[1] * normal[1] + n[2] * normal[2] < 0:
            loop.reverse()
    return loop


def exact_polygons(faces: Sequence["Face"]) -> list[list[Point] | None] | None:
    """Exakte Face-Polygone für Brushes, deren Ecken genau die ganzzahligen Ebenenpunkte sind
    (so baut die Rampen-Bibliothek ihre Segmente).

    Fast parallele Ebenen machen die Gleitkomma-Rechnung ungenau; hier wird in ganzen Zahlen
    gerechnet. Liefert None, wenn der Brush nicht so beschrieben ist (dann gilt die normale
    Rechnung). Geprüft wird, dass jede Kante genau zwei Faces trennt und die Euler-Formel
    gilt, also ein geschlossener Körper entsteht.
    """
    planes = [_int_plane(f) for f in faces]
    if any(p is None or p[0] == (0, 0, 0) for p in planes):
        return None
    on_planes: dict[tuple[int, int, int], set[int]] = {}
    for c in {(int(p[0]), int(p[1]), int(p[2])) for f in faces for p in f.points}:
        on: set[int] = set()
        for j, (n, d) in enumerate(planes):  # type: ignore[misc]
            s = n[0] * c[0] + n[1] * c[1] + n[2] * c[2] - d
            if s > 0:
                break
            if s == 0:
                on.add(j)
        else:
            if len(on) >= 3:
                on_planes[c] = on
    loops: list[list[tuple[int, int, int]]] = []
    edges: dict[frozenset, int] = {}
    for i, (n, _d) in enumerate(planes):  # type: ignore[misc]
        loop = order_on_plane(n, [c for c, on in on_planes.items() if i in on])
        if len(loop) < 3:
            return None
        for k in range(len(loop)):
            e = frozenset((loop[k], loop[k - 1]))
            edges[e] = edges.get(e, 0) + 1
        loops.append(loop)
    if any(count != 2 for count in edges.values()):
        return None
    verts = {p for loop in loops for p in loop}
    if len(verts) - len(edges) + len(loops) != 2:
        return None
    return [[(float(p[0]), float(p[1]), float(p[2])) for p in loop] for loop in loops]


def solid_polygons(faces: Sequence["Face"]) -> list[list[Point] | None]:
    exact = exact_polygons(faces)
    if exact is not None:
        return exact
    return face_polygons([f.plane for f in faces])


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
