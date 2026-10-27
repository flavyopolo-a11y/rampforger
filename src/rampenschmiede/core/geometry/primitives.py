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


def wedge(mins: Point, maxs: Point, material: str = DEFAULT_MATERIAL) -> list[tuple[Face, ...]]:
    """Keil: volle Grundfläche, Schräge fällt von der -Y-Seite zur +Y-Seite ab."""
    y0, y1, z0, z1 = _int(mins[1]), _int(maxs[1]), _int(mins[2]), _int(maxs[2])
    outline = [(y0, z0), (y1, z0), (y0, z1)]  # in (y, z), extrudiert entlang x
    faces = prism(outline, 0, _int(mins[0]), _int(maxs[0]), material)
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
