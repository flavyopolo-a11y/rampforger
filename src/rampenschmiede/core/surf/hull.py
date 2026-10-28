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


#: Ab so vielen Punkten wird mit numpy gesucht (Kugeln, Tori); darunter reicht die einfache Schleife
_VECTOR_FROM = 30


def hull_planes(points: Sequence[IPoint]) -> list[tuple[IPoint, int, list[IPoint]]]:
    """Alle Seitenebenen der Hülle: (ganzzahlige Außennormale, Abstand, Punkte auf der Ebene)."""
    pts = sorted(set(points))
    if len(pts) >= _VECTOR_FROM:
        return _hull_planes_np(pts)
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


def _hull_planes_np(pts: list[IPoint]) -> list[tuple[IPoint, int, list[IPoint]]]:
    """Wie `hull_planes`, die Dreiecke werden aber blockweise mit numpy geprüft (ganzzahlig)."""
    import numpy as np

    P = np.asarray(pts, dtype=np.int64)
    n = len(P)
    idx = np.array(list(combinations(range(n), 3)), dtype=np.int64)
    planes: dict[tuple[IPoint, int], list[IPoint]] = {}
    for start in range(0, len(idx), 20000):
        tri = idx[start:start + 20000]
        a, b, c = P[tri[:, 0]], P[tri[:, 1]], P[tri[:, 2]]
        normal = np.cross(b - a, c - a)
        keep = np.any(normal != 0, axis=1)
        tri, a, normal = tri[keep], a[keep], normal[keep]
        d = np.einsum("ij,ij->i", normal, a)
        side = P @ normal.T - d[None, :]
        below = np.all(side <= 0, axis=0)
        above = np.all(side >= 0, axis=0)
        for k in np.nonzero(below | above)[0]:
            nn = _primitive(tuple(int(x) for x in normal[k]))  # type: ignore[arg-type]
            if above[k] and not below[k]:
                nn = (-nn[0], -nn[1], -nn[2])
            dd = _dot(nn, pts[int(tri[k, 0])])
            if (nn, dd) in planes:
                continue
            on = P @ np.asarray(nn, dtype=np.int64) == dd
            planes[(nn, dd)] = [pts[i] for i in np.nonzero(on)[0]]
    return [(n_, d_, on) for (n_, d_), on in planes.items()]


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
