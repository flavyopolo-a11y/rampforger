"""Wände aus einem Linienzug: je Abschnitt ein konvexer Brush, an den Ecken auf Gehrung
geschnitten, damit die Wände ohne Lücke und ohne Überlappung aneinanderstoßen.

Die Linie ist die Mitte der Wand. Bei sehr spitzen Ecken (unter MIN_MITER_DEG) würde die
Gehrung weit hinausragen; dort endet die Wand gerade und die nächste überlappt ein Stück.
"""
from __future__ import annotations

import math
from typing import Sequence

from ..model.objects import DEFAULT_MATERIAL, Face
from .primitives import _hull

P2 = tuple[float, float]
MIN_MITER_DEG = 25.0


def _sub(a: P2, b: P2) -> P2:
    return a[0] - b[0], a[1] - b[1]


def _norm(v: P2) -> P2:
    length = math.hypot(*v) or 1.0
    return v[0] / length, v[1] / length


def _left(d: P2) -> P2:
    return -d[1], d[0]


def _intersect(p: P2, d: P2, q: P2, e: P2) -> P2 | None:
    """Schnitt der Geraden p + t·d und q + s·e."""
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 1e-9:
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return p[0] + d[0] * t, p[1] + d[1] * t


def clean_points(points: Sequence[P2], closed: bool) -> list[P2]:
    """Doppelte Punkte entfernen (auch Anfang = Ende bei geschlossenem Zug)."""
    out: list[P2] = []
    for p in points:
        if not out or math.hypot(*_sub(p, out[-1])) > 1e-6:
            out.append((float(p[0]), float(p[1])))
    if closed and len(out) > 2 and math.hypot(*_sub(out[0], out[-1])) < 1e-6:
        out.pop()
    return out


def wall_outlines(points: Sequence[P2], thickness: float, closed: bool = False) -> list[list[P2]]:
    """Grundriss je Abschnitt (vier Ecken: links Anfang, links Ende, rechts Ende, rechts Anfang)."""
    pts = clean_points(points, closed)
    n = len(pts)
    if n < 2:
        return []
    segs = [(pts[i], pts[(i + 1) % n]) for i in range(n if closed and n > 2 else n - 1)]
    dirs = [_norm(_sub(b, a)) for a, b in segs]
    h = thickness / 2

    def corner(i: int, at_end: bool, side: float) -> P2:
        """Ecke von Abschnitt i am Anfang/Ende auf der linken (+1) oder rechten (-1) Seite."""
        a, b = segs[i]
        d = dirs[i]
        nrm = _left(d)
        p = b if at_end else a
        own = (p[0] + nrm[0] * h * side, p[1] + nrm[1] * h * side)
        j = i + 1 if at_end else i - 1
        if not closed and (j < 0 or j >= len(segs)):
            return own
        j %= len(segs)
        e = dirs[j]
        turn = math.degrees(math.acos(max(-1.0, min(1.0, d[0] * e[0] + d[1] * e[1]))))
        if 180 - turn < MIN_MITER_DEG:
            return own  # zu spitz: gerade enden
        other_nrm = _left(e)
        q = segs[j][0] if at_end else segs[j][1]
        q_off = (q[0] + other_nrm[0] * h * side, q[1] + other_nrm[1] * h * side)
        hit = _intersect(own, d, q_off, e)
        return hit if hit is not None else own

    out = []
    for i in range(len(segs)):
        out.append([corner(i, False, 1), corner(i, True, 1), corner(i, True, -1), corner(i, False, -1)])
    return out


def wall_faces(points: Sequence[P2], thickness: float, bottom: float, height: float, closed: bool = False,
               material: str = DEFAULT_MATERIAL) -> list[tuple[Face, ...]]:
    """Brushes der Wände (gültige, konvexe Hüllen mit ganzzahligen Ecken)."""
    out = []
    for quad in wall_outlines(points, thickness, closed):
        pts = [(x, y, z) for x, y in quad for z in (bottom, bottom + height)]
        faces = _hull(pts, material)
        if faces:
            out.append(faces)
    return out


__all__ = ["MIN_MITER_DEG", "clean_points", "wall_faces", "wall_outlines"]
