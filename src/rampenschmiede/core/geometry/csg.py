"""Schneiden (Clip) und Aushöhlen (Carve) konvexer Brushes, nur auf Face-Ebene.

Ein Brush ist ein Schnitt von Halbräumen. Schneiden heißt: eine Ebene dazunehmen und die
Seiten wegwerfen, die danach keine Fläche mehr haben. Aushöhlen zerlegt einen Brush an den
Ebenen eines zweiten in Stücke, die außerhalb liegen (wie Carve in Hammer). Liegen die
Schnittpunkte auf ganzen Zahlen, bleiben alle Ecken ganzzahlig (siehe E32).
"""
from __future__ import annotations

import dataclasses
from collections import Counter
from typing import Sequence

from ..mathutil import Plane, Point, dot
from ..model.objects import Face, default_tex_axes
from .brush import polygon_area, solid_polygons

SIDE_EPSILON = 0.01
MIN_AREA = 1e-3

Faces = tuple[Face, ...]


def make_face(points: tuple[Point, Point, Point], material: str) -> Face:
    u, v = default_tex_axes(Plane.from_vmf_points(*points).normal)
    return Face(points=points, material=material, uaxis=u, vaxis=v)


def oriented(points: tuple[Point, Point, Point], outward: Point) -> tuple[Point, Point, Point]:
    """Punkte so ordnen, dass die Normale der Ebene in Richtung `outward` zeigt."""
    if dot(Plane.from_vmf_points(*points).normal, outward) < 0:
        return (points[0], points[2], points[1])
    return points


def flipped(face: Face) -> Face:
    """Dieselbe Ebene, Normale umgedreht (Rückseite)."""
    p1, p2, p3 = face.points
    return make_face((p1, p3, p2), face.material)


def main_material(faces: Sequence[Face]) -> str:
    """Häufigstes Material außer Werkzeug-Texturen, für neue Schnittflächen."""
    counts = Counter(f.material for f in faces if not f.material.upper().startswith("TOOLS/"))
    if not counts:
        counts = Counter(f.material for f in faces)
    return counts.most_common(1)[0][0]


def _vertices(faces: Sequence[Face]) -> list[Point]:
    return [p for poly in solid_polygons(faces) if poly for p in poly]


def keep_behind(faces: Faces, cut: Face) -> Faces | None:
    """Teil des Brushes hinter der Ebene von `cut` (deren Normale zeigt nach außen).
    None, wenn nichts übrig bleibt; unverändert, wenn der Brush ganz dahinter liegt."""
    plane = cut.plane
    dists = [plane.distance(p) for p in _vertices(faces)]
    if not dists or all(d >= -SIDE_EPSILON for d in dists):
        return None
    if all(d <= SIDE_EPSILON for d in dists):
        return faces
    new = (*faces, cut)
    polys = solid_polygons(new)
    kept = tuple(f for f, poly in zip(new, polys) if poly is not None and polygon_area(poly) > MIN_AREA)
    if len(kept) < 4 or cut not in kept:
        return None
    # Kopien dürfen keine alten VMF-IDs mit dem Original teilen
    return tuple(dataclasses.replace(f, vmf_id=None) for f in kept)


def split(faces: Faces, points: tuple[Point, Point, Point], material: str | None = None) -> tuple[Faces | None, Faces | None]:
    """Brush an der Ebene durch drei Punkte teilen: (hinter der Ebene, davor)."""
    cut = make_face(points, material or main_material(faces))
    return keep_behind(faces, cut), keep_behind(faces, flipped(cut))


def carve(target: Faces, cutter: Sequence[Face], material: str | None = None) -> list[Faces] | None:
    """Stücke von `target` außerhalb von `cutter`. None, wenn sich beide nicht durchdringen
    (dann bleibt der Brush, wie er ist). Eine leere Liste heißt: ganz verschluckt."""
    material = material or main_material(target)
    rest: Faces | None = target
    pieces: list[Faces] = []
    for face in cutter:
        cut = make_face(face.points, material)
        assert rest is not None
        inside = keep_behind(rest, cut)
        if inside is None:
            return None  # ganz vor dieser Ebene: keine Überschneidung
        outside = keep_behind(rest, flipped(cut))
        if outside is not None:
            pieces.append(outside)
        rest = inside
    return pieces


__all__ = ["carve", "flipped", "keep_behind", "main_material", "make_face", "oriented", "split"]
