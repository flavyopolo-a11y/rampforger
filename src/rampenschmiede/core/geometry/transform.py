"""Verschieben, Drehen, Skalieren von Brushes und Entities.

Für jede Face werden drei weit auseinanderliegende Punkte ihres Polygons transformiert
und auf ganze Units gerundet; daraus entsteht die neue Ebene. Weit auseinander heißt:
Die Rundung verändert den Winkel der Ebene so wenig wie möglich. Der neue Brush ist als
Schnitt von Halbräumen weiterhin konvex. Entartet er (Face verschwindet), wird die
Operation abgelehnt.

Texture Lock: Achsen und Offsets werden so mitgeführt, dass die Textur auf der Fläche
an derselben Stelle bleibt.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Callable

from ..mathutil import Point, add, dot, length, round_point, sub
from ..model.objects import Entity, Face, MapObject, Solid, TexAxis
from .brush import best_triangle, is_valid_solid
from .displacement import face_displacement, transform_displacement, with_displacement

Matrix3 = tuple[Point, Point, Point]  # Zeilen


def mat_mul_vec(m: Matrix3, v: Point) -> Point:
    return (dot(m[0], v), dot(m[1], v), dot(m[2], v))


def rotation_matrix(axis: int, degrees: float) -> Matrix3:
    """Drehung um X (0), Y (1) oder Z (2), gegen den Uhrzeigersinn beim Blick entlang -Achse."""
    # Für 90°-Vielfache exakte Werte, damit nichts gerundet werden muss.
    d = degrees % 360.0
    exact = {0.0: (1.0, 0.0), 90.0: (0.0, 1.0), 180.0: (-1.0, 0.0), 270.0: (0.0, -1.0)}
    c, s = exact.get(round(d, 9), (math.cos(math.radians(d)), math.sin(math.radians(d))))
    if axis == 2:
        return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))
    if axis == 0:
        return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


class TransformError(ValueError):
    """Die Transformation würde einen ungültigen Brush erzeugen."""


def _transform_solid(solid: Solid, point_fn: Callable[[Point], Point],
                     tex_fn: Callable[[TexAxis], TexAxis] | None) -> Solid:
    polys = solid.polygons()
    new_faces: list[Face] = []
    for face, poly in zip(solid.faces, polys):
        if poly is None:
            continue  # bereits entartete Face fällt weg
        a, b, c = best_triangle(poly)
        pts = tuple(tuple(float(x) for x in round_point(point_fn(p))) for p in (a, c, b))
        nf = dataclasses.replace(face, points=pts)  # type: ignore[arg-type]
        if tex_fn is not None:
            nf = dataclasses.replace(nf, uaxis=tex_fn(face.uaxis), vaxis=tex_fn(face.vaxis))
        disp = face_displacement(face)
        if disp is not None:
            o = point_fn((0.0, 0.0, 0.0))
            nf = with_displacement(nf, transform_displacement(disp, point_fn, lambda v, o=o: sub(point_fn(v), o)))
        new_faces.append(nf)
    result = solid.replace(faces=tuple(new_faces))
    if not is_valid_solid(result):
        raise TransformError("Die Form würde dabei entarten")
    return result


def _transform_entity(ent: Entity, point_fn: Callable[[Point], Point], yaw_delta: float | None = None) -> Entity:
    """Ursprung mitbewegen. Bei Bausteinen auch den Ankerpunkt: Verschieben und Drehen um Z
    kann der Baustein nachbilden, alles andere macht ihn zu normalen Brushes."""
    block = ent.extra.get("block")
    if block is not None:
        extra = dict(ent.extra)
        if yaw_delta is None:
            del extra["block"]
        else:
            x, y, z, yaw = block["placement"]
            px, py, pz = round_point(point_fn((float(x), float(y), float(z))))
            extra["block"] = {**block, "placement": [px, py, pz, round((yaw + yaw_delta) % 360, 6)]}
        ent = ent.replace(extra=extra)
    origin = ent.origin
    if origin is None:
        return ent
    x, y, z = round_point(point_fn(origin))
    return ent.with_keyvalue("origin", f"{x} {y} {z}")


def translate(obj: MapObject, delta: Point, texture_lock: bool = True) -> MapObject:
    d = round_point(delta)
    fdelta: Point = (float(d[0]), float(d[1]), float(d[2]))
    if isinstance(obj, Entity):
        return _transform_entity(obj, lambda p: add(p, fdelta), 0.0)

    def tex(ax: TexAxis) -> TexAxis:
        return dataclasses.replace(ax, offset=ax.offset - dot(fdelta, ax.vec) / ax.scale) if ax.scale else ax

    # Verschieben um ganze Units ist exakt: Ebenenpunkte direkt verschieben.
    faces = tuple(
        dataclasses.replace(
            f,
            points=tuple(add(p, fdelta) for p in f.points),  # type: ignore[arg-type]
            uaxis=tex(f.uaxis) if texture_lock else f.uaxis,
            vaxis=tex(f.vaxis) if texture_lock else f.vaxis,
        )
        for f in obj.faces
    )
    return obj.replace(faces=faces)


def rotate(obj: MapObject, pivot: Point, axis: int, degrees: float, texture_lock: bool = True) -> MapObject:
    m = rotation_matrix(axis, degrees)

    def fn(p: Point) -> Point:
        return add(mat_mul_vec(m, sub(p, pivot)), pivot)

    if isinstance(obj, Entity):
        ent = _transform_entity(obj, fn, degrees if axis == 2 else None)
        if axis == 2 and ent.origin is not None:
            # Gier-Winkel der Entity mitdrehen (nur Punkt-Entities: bei Brush-Entities würde
            # "angles" das ganze Modell im Spiel noch einmal drehen)
            raw = ent.get("angles", "0 0 0").split()
            if len(raw) == 3:
                try:
                    yaw = (float(raw[1]) + degrees) % 360
                    ent = ent.with_keyvalue("angles", f"{raw[0]} {yaw:g} {raw[2]}")
                except ValueError:
                    pass
        return ent

    def tex(ax: TexAxis) -> TexAxis:
        new_vec = mat_mul_vec(m, ax.vec)
        off = ax.offset + (dot(pivot, ax.vec) - dot(pivot, new_vec)) / ax.scale if ax.scale else ax.offset
        return TexAxis(new_vec[0], new_vec[1], new_vec[2], off, ax.scale)

    return _transform_solid(obj, fn, tex if texture_lock else None)


def scale_obj(obj: MapObject, pivot: Point, factors: Point, texture_lock: bool = True) -> MapObject:
    def fn(p: Point) -> Point:
        r = sub(p, pivot)
        return add((r[0] * factors[0], r[1] * factors[1], r[2] * factors[2]), pivot)

    if isinstance(obj, Entity):
        return _transform_entity(obj, fn)

    def tex(ax: TexAxis) -> TexAxis:
        f = length((ax.x * factors[0], ax.y * factors[1], ax.z * factors[2]))
        if not ax.scale or f < 1e-9:
            return ax
        new_scale = ax.scale * f
        off = ax.offset + dot(pivot, ax.vec) * (1 / ax.scale - 1 / new_scale)
        return dataclasses.replace(ax, scale=new_scale, offset=off)

    if any(f <= 0 for f in factors):
        raise TransformError("Skalierung muss größer als null sein")
    return _transform_solid(obj, fn, tex if texture_lock else None)


def mirror(obj: MapObject, pivot: Point, axis: int) -> MapObject:
    """Spiegeln: Punktreihenfolge kehrt sich um, damit die Normalen außen bleiben."""
    def fn(p: Point) -> Point:
        q = list(p)
        q[axis] = 2 * pivot[axis] - q[axis]
        return (q[0], q[1], q[2])

    if isinstance(obj, Entity):
        return _transform_entity(obj, fn)
    faces = []
    for f in obj.faces:
        p1, p2, p3 = (tuple(float(c) for c in round_point(fn(p))) for p in f.points)
        flip = [1.0, 1.0, 1.0]
        flip[axis] = -1.0
        u = TexAxis(f.uaxis.x * flip[0], f.uaxis.y * flip[1], f.uaxis.z * flip[2], f.uaxis.offset, f.uaxis.scale)
        v = TexAxis(f.vaxis.x * flip[0], f.vaxis.y * flip[1], f.vaxis.z * flip[2], f.vaxis.offset, f.vaxis.scale)
        faces.append(dataclasses.replace(f, points=(p1, p3, p2), uaxis=u, vaxis=v))  # type: ignore[arg-type]
    result = obj.replace(faces=tuple(faces))
    if not is_valid_solid(result):
        raise TransformError("Die Form würde dabei entarten")
    return result


__all__ = ["translate", "rotate", "scale_obj", "mirror", "rotation_matrix", "TransformError"]
