"""Grundformen: Block, Keil, Zylinder, Bogen, Treppe.

Alle Formen sind Prismen aus einem konvexen 2D-Umriss. Jeder Eckpunkt wird vor dem
Bauen auf ganze Units gerundet und der Umriss danach erneut als konvexe Hülle gebildet.
So sind Ergebnis-Vertices garantiert ganzzahlig und der Brush garantiert konvex.

Ergebnis ist jeweils eine Liste von Face-Tupeln (ein Eintrag pro Brush). IDs vergibt
erst das Dokument.
"""
from __future__ import annotations

import math
from typing import Literal, Sequence

from ..mathutil import Point
from ..model.objects import DEFAULT_MATERIAL, Face
from .brush import faces_from_loops

Axis = Literal[0, 1, 2]
Point2 = tuple[int, int]


def convex_hull_2d(points: Sequence[tuple[float, float]]) -> list[Point2]:
    """Konvexe Hülle (Andrew's Monotone Chain), gegen den Uhrzeigersinn, ohne kollineare Punkte."""
    pts = sorted(set((int(x), int(y)) for x, y in points))
    if len(pts) < 3:
        return pts

    def turn(o: Point2, a: Point2, b: Point2) -> int:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point2] = []
    for p in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Point2] = []
    for p in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _to3d(axis: Axis, u: float, v: float, w: float) -> Point:
    # Zyklische Vertauschung erhält die Händigkeit: (u, v, Extrusion) -> (x, y, z)
    if axis == 2:
        return (u, v, w)
    if axis == 0:
        return (w, u, v)
    return (v, w, u)


def prism(outline: Sequence[Point2], axis: Axis, lo: int, hi: int, material: str = DEFAULT_MATERIAL) -> tuple[Face, ...] | None:
    """Prisma aus einem konvexen Umriss (gegen den Uhrzeigersinn) entlang einer Achse."""
    hull = convex_hull_2d(outline)
    if len(hull) < 3 or hi <= lo:
        return None
    top = [_to3d(axis, u, v, hi) for u, v in hull]
    bottom = [_to3d(axis, u, v, lo) for u, v in reversed(hull)]
    loops: list[list[Point]] = [top, bottom]
    n = len(hull)
    for i in range(n):
        a, b = hull[i], hull[(i + 1) % n]
        loops.append([
            _to3d(axis, a[0], a[1], lo),
            _to3d(axis, b[0], b[1], lo),
            _to3d(axis, b[0], b[1], hi),
            _to3d(axis, a[0], a[1], hi),
        ])
    return faces_from_loops(loops, material)


def _uv_ranges(mins: Point, maxs: Point, axis: Axis) -> tuple[float, float, float, float, float, float]:
    """(u0, u1, v0, v1, w0, w1) für die gewählte Extrusionsachse."""
    if axis == 2:
        return mins[0], maxs[0], mins[1], maxs[1], mins[2], maxs[2]
    if axis == 0:
        return mins[1], maxs[1], mins[2], maxs[2], mins[0], maxs[0]
    return mins[2], maxs[2], mins[0], maxs[0], mins[1], maxs[1]


def _int(v: float) -> int:
    return math.floor(v + 0.5)


def block(mins: Point, maxs: Point, material: str = DEFAULT_MATERIAL) -> list[tuple[Face, ...]]:
    outline = [(_int(mins[0]), _int(mins[1])), (_int(maxs[0]), _int(mins[1])),
               (_int(maxs[0]), _int(maxs[1])), (_int(mins[0]), _int(maxs[1]))]
    faces = prism(outline, 2, _int(mins[2]), _int(maxs[2]), material)
    return [faces] if faces else []


def wedge(mins: Point, maxs: Point, material: str = DEFAULT_MATERIAL,
          high_side: Literal["-y", "+y", "-x", "+x"] = "-y") -> list[tuple[Face, ...]]:
    """Keil: volle Grundfläche, die Schräge steigt zur Seite `high_side` hin an."""
    x0, y0, z0 = (_int(c) for c in mins)
    x1, y1, z1 = (_int(c) for c in maxs)
    if high_side in ("-y", "+y"):
        top_y = y0 if high_side == "-y" else y1
        outline = [(y0, z0), (y1, z0), (top_y, z1)]  # in (y, z), extrudiert entlang x
        faces = prism(outline, 0, x0, x1, material)
    else:
        top_x = x0 if high_side == "-x" else x1
        outline = [(z0, x0), (z0, x1), (z1, top_x)]  # in (z, x), extrudiert entlang y
        faces = prism(outline, 1, y0, y1, material)
    return [faces] if faces else []


def _ellipse(mins: Point, maxs: Point, axis: Axis, sides: int, start_deg: float, arc_deg: float,
             shrink: float = 0.0) -> list[tuple[float, float]]:
    u0, u1, v0, v1, _, _ = _uv_ranges(mins, maxs, axis)
    cu, cv = (u0 + u1) / 2, (v0 + v1) / 2
    ru, rv = (u1 - u0) / 2 - shrink, (v1 - v0) / 2 - shrink
    pts = []
    for i in range(sides + 1):
        a = math.radians(start_deg + arc_deg * i / sides)
        pts.append((cu + ru * math.cos(a), cv + rv * math.sin(a)))
    return pts


def cylinder(mins: Point, maxs: Point, sides: int = 8, axis: Axis = 2,
             material: str = DEFAULT_MATERIAL) -> list[tuple[Face, ...]]:
    sides = max(3, sides)
    # Startwinkel so, dass bei gerader Seitenzahl Kanten parallel zu den Achsen liegen.
    pts = _ellipse(mins, maxs, axis, sides, 180.0 / sides if sides % 2 == 0 else 90.0, 360.0)[:-1]
    _, _, _, _, w0, w1 = _uv_ranges(mins, maxs, axis)
    faces = prism([(_int(u), _int(v)) for u, v in pts], axis, _int(w0), _int(w1), material)
    return [faces] if faces else []


def arch(mins: Point, maxs: Point, sides: int = 8, wall: int = 16, arc_deg: float = 180.0,
         start_deg: float = 0.0, axis: Axis = 2, material: str = DEFAULT_MATERIAL) -> list[tuple[Face, ...]]:
    """Bogen aus `sides` Segmenten. Jedes Segment ist ein eigener konvexer Brush."""
    sides = max(1, sides)
    outer = _ellipse(mins, maxs, axis, sides, start_deg, arc_deg)
    inner = _ellipse(mins, maxs, axis, sides, start_deg, arc_deg, shrink=float(wall))
    _, _, _, _, w0, w1 = _uv_ranges(mins, maxs, axis)
    result = []
    for i in range(sides):
        quad = [outer[i], outer[i + 1], inner[i + 1], inner[i]]
        faces = prism([(_int(u), _int(v)) for u, v in quad], axis, _int(w0), _int(w1), material)
        if faces:
            result.append(faces)
    return result


def stairs(mins: Point, maxs: Point, steps: int = 8, direction: Literal["+x", "-x", "+y", "-y"] = "+y",
           material: str = DEFAULT_MATERIAL) -> list[tuple[Face, ...]]:
    """Massive Treppe: jede Stufe reicht bis zum Boden. Steigt in `direction` an."""
    x0, y0, z0 = (_int(c) for c in mins)
    x1, y1, z1 = (_int(c) for c in maxs)
    steps = max(1, min(steps, z1 - z0))
    along_x = direction in ("+x", "-x")
    run0, run1 = (x0, x1) if along_x else (y0, y1)
    steps = max(1, min(steps, run1 - run0))
    result = []
    for i in range(steps):
        a = run0 + (run1 - run0) * i // steps
        b = run0 + (run1 - run0) * (i + 1) // steps
        if direction in ("-x", "-y"):
            a, b = run1 - (b - run0), run1 - (a - run0)
        top = z0 + (z1 - z0) * (i + 1) // steps
        if along_x:
            result += block((a, y0, z0), (b, y1, top), material)
        else:
            result += block((x0, a, z0), (x1, b, top), material)
    return result


def _hull(points, material: str) -> tuple[Face, ...] | None:
    from ..surf.hull import hull_faces

    pts = list(dict.fromkeys((_int(p[0]), _int(p[1]), _int(p[2])) for p in points))
    return hull_faces(pts, lambda _n, _loop: material)


def spike(mins: Point, maxs: Point, sides: int = 4, material: str = DEFAULT_MATERIAL) -> list[tuple[Face, ...]]:
    """Spitze (Kegel bzw. Pyramide): Grundfläche unten, Spitze oben in der Mitte."""
    sides = max(3, sides)
    ring = _ellipse(mins, maxs, 2, sides, 180.0 / sides if sides % 2 == 0 else 90.0, 360.0)[:-1]
    apex = ((mins[0] + maxs[0]) / 2, (mins[1] + maxs[1]) / 2, maxs[2])
    faces = _hull([(u, v, mins[2]) for u, v in ring] + [apex], material)
    return [faces] if faces else []


SPHERE_MAX_SIDES = 12


def sphere(mins: Point, maxs: Point, sides: int = 8, material: str = DEFAULT_MATERIAL) -> list[tuple[Face, ...]]:
    """Kugel (Ellipsoid) als ein konvexer Brush: `sides` Punkte je Breitenkreis, halb so viele Kreise.
    Höchstens 12 Seiten: vbsp erlaubt 128 Seiten je Brush."""
    sides = max(4, min(sides, SPHERE_MAX_SIDES))
    rings = max(2, sides // 2)
    c = [(mins[i] + maxs[i]) / 2 for i in range(3)]
    r = [(maxs[i] - mins[i]) / 2 for i in range(3)]
    pts = [(c[0], c[1], mins[2]), (c[0], c[1], maxs[2])]
    for k in range(1, rings):
        lat = math.pi * k / rings - math.pi / 2
        for i in range(sides):
            lon = 2 * math.pi * i / sides + math.pi / sides
            pts.append((c[0] + r[0] * math.cos(lat) * math.cos(lon), c[1] + r[1] * math.cos(lat) * math.sin(lon),
                        c[2] + r[2] * math.sin(lat)))
    faces = _hull(pts, material)
    return [faces] if faces else []


def torus(mins: Point, maxs: Point, sides: int = 12, wall: int = 32, tube_sides: int = 8,
          material: str = DEFAULT_MATERIAL) -> list[tuple[Face, ...]]:
    """Ring mit rundem Querschnitt (Dicke `wall`), aus `sides` konvexen Segmenten."""
    sides = max(3, sides)
    tube_sides = max(3, tube_sides)
    c = [(mins[i] + maxs[i]) / 2 for i in range(3)]
    tube = max(1.0, min(wall / 2, (maxs[2] - mins[2]) / 2))
    ru = (maxs[0] - mins[0]) / 2 - tube
    rv = (maxs[1] - mins[1]) / 2 - tube
    if ru <= 0 or rv <= 0:
        return []

    def section(a: float) -> list[Point]:
        out = []
        for j in range(tube_sides):
            b = 2 * math.pi * j / tube_sides
            out.append((c[0] + (ru + tube * math.cos(b)) * math.cos(a), c[1] + (rv + tube * math.cos(b)) * math.sin(a),
                        c[2] + tube * math.sin(b)))
        return out

    result = []
    for i in range(sides):
        a0, a1 = 2 * math.pi * i / sides, 2 * math.pi * (i + 1) / sides
        faces = _hull(section(a0) + section(a1), material)
        if faces:
            result.append(faces)
    return result
