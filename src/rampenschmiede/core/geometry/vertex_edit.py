"""Ecken und Kanten eines Brushes verschieben (wie das Vertex-Werkzeug in Hammer).

Nach dem Verschieben ist der Brush die konvexe Hülle seiner Ecken, ganzzahlig gerechnet
(dieselbe Rechnung wie bei den Rampen, gegen Rampbugs). Liegt eine verschobene Ecke danach
im Inneren, wäre der Brush hohl: Das wird abgelehnt. Fallen Ecken zusammen, verschmelzen sie.

Jede neue Seite übernimmt Material und Texturachsen der alten Seite, aus der die meisten
ihrer Ecken stammen, so bleibt die Textur beim Ziehen liegen.
"""
from __future__ import annotations

import dataclasses
from typing import Iterable, Mapping

from ...i18n import tr
from ..model.objects import Face, Solid, default_tex_axes
from ..surf.hull import IPoint, hull_planes
from .brush import order_on_plane, vmf_points_from_loop

Edge = tuple[IPoint, IPoint]


class VertexError(ValueError):
    pass


def _ip(p) -> IPoint:
    return (int(round(p[0])), int(round(p[1])), int(round(p[2])))


def vertices(solid: Solid) -> list[IPoint]:
    """Ecken des Brushes, auf ganze Units gerundet."""
    return list(dict.fromkeys(_ip(p) for p in solid.vertices()))


def edges(solid: Solid) -> list[Edge]:
    """Kanten als Eckenpaare (jede einmal)."""
    seen: dict[tuple[IPoint, IPoint], None] = {}
    for poly in solid.polygons():
        if not poly:
            continue
        pts = [_ip(p) for p in poly]
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            if a != b:
                seen.setdefault((a, b) if a <= b else (b, a), None)
    return list(seen)


def midpoint(edge: Edge) -> tuple[float, float, float]:
    a, b = edge
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)


def _tex_ok(face: Face, normal) -> bool:
    """Texturachsen, die (fast) in Richtung der Normale zeigen, ergeben verzerrte Texturen."""
    def along(axis) -> float:
        v = axis.vec
        length = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5 or 1.0
        nl = (normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2) ** 0.5 or 1.0
        return abs(v[0] * normal[0] + v[1] * normal[1] + v[2] * normal[2]) / (length * nl)
    return along(face.uaxis) < 0.95 and along(face.vaxis) < 0.95


def move_vertices(solid: Solid, moves: Mapping[IPoint, IPoint], rebuild: bool = False) -> Solid:
    """Brush mit verschobenen Ecken. `moves`: alte Ecke → neue Lage (ganze Units).
    `rebuild` baut auch ohne Verschiebung neu, z. B. um Kommazahl-Ecken aufs Raster zu legen."""
    old = vertices(solid)
    if not moves and not rebuild:
        return solid
    target = {v: _ip(moves.get(v, v)) for v in old}
    new_pts = list(dict.fromkeys(target.values()))
    planes = hull_planes(new_pts)
    if len(planes) < 4:
        raise VertexError(tr("Der Brush würde flach: Ecken nicht aufeinander schieben"))
    on_hull = {p for _n, _d, on in planes for p in on}
    for v, p in target.items():
        if v in moves and p not in on_hull:
            raise VertexError(tr("So würde der Brush hohl (nicht konvex). Ecke weniger weit ziehen"))
    # Woher kommt jede neue Ecke?
    sources: dict[IPoint, list[IPoint]] = {}
    for v, p in target.items():
        sources.setdefault(p, []).append(v)
    old_faces = []
    for face, poly in zip(solid.faces, solid.polygons()):
        if poly:
            old_faces.append((face, {_ip(p) for p in poly}))
    faces: list[Face] = []
    used_ids: set[int] = set()
    for n, _d, on in planes:
        loop = order_on_plane(n, on)
        if len(loop) < 3:
            continue
        origin = {v for p in on for v in sources.get(p, [])}
        best = max(old_faces, key=lambda fp: (len(fp[1] & origin), _dot_n(fp[0], n)))
        src = best[0]
        pts = vmf_points_from_loop(loop)
        new = Face(points=pts, material=src.material, uaxis=src.uaxis, vaxis=src.vaxis, rotation=src.rotation,
                   lightmapscale=src.lightmapscale, smoothing_groups=src.smoothing_groups)
        if not _tex_ok(new, n):
            u, v = default_tex_axes(n)
            new = dataclasses.replace(new, uaxis=dataclasses.replace(u, scale=src.uaxis.scale),
                                      vaxis=dataclasses.replace(v, scale=src.vaxis.scale))
        same_plane = _same_plane(src, n, _d)
        if same_plane and src.vmf_id is not None and src.vmf_id not in used_ids:
            new = dataclasses.replace(new, vmf_id=src.vmf_id, extra=dict(src.extra))
            used_ids.add(src.vmf_id)
        elif same_plane:
            new = dataclasses.replace(new, extra=dict(src.extra))
        faces.append(new)
    return solid.replace(faces=tuple(faces))


def _dot_n(face: Face, n) -> float:
    fn = face.plane.normal
    length = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5 or 1.0
    return (fn[0] * n[0] + fn[1] * n[1] + fn[2] * n[2]) / length


def _same_plane(face: Face, n, d) -> bool:
    """Liegt die neue Seite in der Ebene der alten (dann bleiben Displacement und ID erhalten)?"""
    pl = face.plane
    length = (n[0] ** 2 + n[1] ** 2 + n[2] ** 2) ** 0.5 or 1.0
    nn = (n[0] / length, n[1] / length, n[2] / length)
    return (abs(pl.normal[0] - nn[0]) < 1e-6 and abs(pl.normal[1] - nn[1]) < 1e-6
            and abs(pl.normal[2] - nn[2]) < 1e-6 and abs(pl.dist - d / length) < 1e-4)


def off_grid(solid: Solid, tolerance: float = 0.01) -> bool:
    """Liegt eine Ecke nicht auf ganzen Units?"""
    return any(abs(c - round(c)) > tolerance for p in solid.vertices() for c in p)


def snap_to_grid(solid: Solid) -> Solid:
    """Alle Ecken auf ganze Units runden und den Brush daraus neu bauen (gegen Rampbugs)."""
    return move_vertices(solid, {}, rebuild=True)


def move_selected(solid: Solid, picked: Iterable[IPoint], delta: IPoint) -> Solid:
    """Die gewählten Ecken um `delta` verschieben."""
    d = _ip(delta)
    return move_vertices(solid, {v: (v[0] + d[0], v[1] + d[1], v[2] + d[2]) for v in picked})


__all__ = ["Edge", "VertexError", "edges", "midpoint", "move_selected", "move_vertices", "off_grid", "snap_to_grid",
           "vertices"]
