"""Konvexe Hülle aus ganzzahligen Punkten, exakt gerechnet.

Rampen-Segmente entstehen als Hülle ihrer beiden (gerundeten) Querschnitte. Weil alle
Punkte ganzzahlig sind und die Hülle mit ganzen Zahlen gerechnet wird, sind sämtliche
Eckpunkte ganzzahlig, und benachbarte Segmente teilen ihre Nahtpunkte exakt. Das ist
die wichtigste Regel gegen Rampbugs.
"""
from __future__ import annotations

from itertools import combinations
from typing import Callable, Sequence

from ..geometry.brush import faces_from_loops, order_on_plane
from ..model.objects import Face

IPoint = tuple[int, int, int]


def _sub(a: IPoint, b: IPoint) -> IPoint:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: IPoint, b: IPoint) -> IPoint:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: IPoint, b: IPoint) -> int:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _primitive(n: IPoint) -> IPoint:
    from math import gcd

    g = gcd(gcd(abs(n[0]), abs(n[1])), abs(n[2])) or 1
    return (n[0] // g, n[1] // g, n[2] // g)


def hull_planes(points: Sequence[IPoint]) -> list[tuple[IPoint, int, list[IPoint]]]:
    """Alle Seitenebenen der Hülle: (ganzzahlige Außennormale, Abstand, Punkte auf der Ebene)."""
    pts = sorted(set(points))
    planes: dict[tuple[IPoint, int], list[IPoint]] = {}
    for a, b, c in combinations(pts, 3):
        n = _cross(_sub(b, a), _sub(c, a))
        if n == (0, 0, 0):
            continue
        n = _primitive(n)
        d = _dot(n, a)
        if (n, d) in planes or ((-n[0], -n[1], -n[2]), -d) in planes:
            continue
        side = [_dot(n, p) - d for p in pts]
        if all(s <= 0 for s in side):
            planes[(n, d)] = [p for p, s in zip(pts, side) if s == 0]
        elif all(s >= 0 for s in side):
            nn = (-n[0], -n[1], -n[2])
            planes[(nn, -d)] = [p for p, s in zip(pts, side) if s == 0]
    return [(n, d, on) for (n, d), on in planes.items()]


def hull_faces(points: Sequence[IPoint], material_for: Callable[[IPoint, list[IPoint]], str]) -> tuple[Face, ...] | None:
    """Brush-Seiten der Hülle. `material_for(normal, punkte)` wählt das Material je Seite."""
    planes = hull_planes(points)
    if len(planes) < 4:
        return None
    faces: list[Face] = []
    for n, _d, on in planes:
        loop = order_on_plane(n, on)
        if len(loop) < 3:
            continue
        faces += faces_from_loops([loop], material_for(n, loop))
    return tuple(faces)
