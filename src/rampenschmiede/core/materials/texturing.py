"""Textur-Ausrichtung einzelner Seiten wie im Face-Editor von Hammer.

Alle Funktionen sind rein: Sie nehmen eine Face und liefern eine neue. Die Formel für
Texturkoordinaten ist die von Source: texel = Punkt · Achse / Skalierung + Verschiebung.
"""
from __future__ import annotations

import dataclasses
import math
from typing import Sequence

from ..mathutil import Point
from ..model.objects import Face, TexAxis, default_tex_axes

JUSTIFY = ("fit", "left", "right", "top", "bottom", "center")


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Point, b: Point) -> Point:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(v: Point) -> Point:
    n = math.sqrt(_dot(v, v))
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-12 else (0.0, 0.0, 0.0)


def _clean(v: Point) -> Point:
    return tuple(0.0 if abs(c) < 1e-9 else round(c, 9) for c in v)  # type: ignore[return-value]


def set_values(face: Face, *, shift: tuple[float | None, float | None] = (None, None),
               scale: tuple[float | None, float | None] = (None, None), rotation: float | None = None,
               lightmapscale: int | None = None, material: str | None = None) -> Face:
    """Felder des Face-Editors setzen. None lässt den Wert unverändert. Eine neue Drehung
    dreht beide Achsen um die Differenz zur alten um die Normale."""
    u, v = face.uaxis, face.vaxis
    if rotation is not None and abs(rotation - face.rotation) > 1e-9:
        u, v = _rotate_axes(face, u, v, rotation - face.rotation)
    u = TexAxis(u.x, u.y, u.z, u.offset if shift[0] is None else shift[0], u.scale if scale[0] is None else scale[0])
    v = TexAxis(v.x, v.y, v.z, v.offset if shift[1] is None else shift[1], v.scale if scale[1] is None else scale[1])
    return dataclasses.replace(
        face, uaxis=u, vaxis=v,
        rotation=face.rotation if rotation is None else rotation % 360,
        lightmapscale=face.lightmapscale if lightmapscale is None else lightmapscale,
        material=face.material if material is None else material.upper())


def _rotate_axes(face: Face, u: TexAxis, v: TexAxis, degrees: float) -> tuple[TexAxis, TexAxis]:
    n = _unit(face.plane.normal)
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)

    def rot(vec: Point) -> Point:
        # Rodrigues: Drehung um n
        k = _cross(n, vec)
        d = _dot(n, vec)
        return _clean(tuple(vec[i] * c + k[i] * s + n[i] * d * (1 - c) for i in range(3)))  # type: ignore[arg-type]

    return u.with_vec(rot(u.vec)), v.with_vec(rot(v.vec))


def align_world(face: Face) -> Face:
    """Achsen nach der dominanten Weltachse (wie neue Brushes), Skalierung bleibt."""
    du, dv = default_tex_axes(face.plane.normal)
    return dataclasses.replace(face, uaxis=TexAxis(du.x, du.y, du.z, face.uaxis.offset, face.uaxis.scale),
                               vaxis=TexAxis(dv.x, dv.y, dv.z, face.vaxis.offset, face.vaxis.scale), rotation=0.0)


def align_face(face: Face) -> Face:
    """Achsen in der Ebene der Seite: v zeigt hangabwärts, u liegt waagrecht. Auf Rampen
    läuft die Textur so entlang der Schräge statt verzerrt."""
    n = _unit(face.plane.normal)
    if abs(n[2]) > 0.999:
        return align_world(face)
    down = (0.0, 0.0, -1.0)
    v = _unit(tuple(down[i] - n[i] * _dot(down, n) for i in range(3)))  # type: ignore[arg-type]
    u = _unit(_cross(n, v))
    return dataclasses.replace(face, uaxis=TexAxis(*_clean(u), face.uaxis.offset, face.uaxis.scale),
                               vaxis=TexAxis(*_clean(v), face.vaxis.offset, face.vaxis.scale), rotation=0.0)


def justify(face: Face, polygon: Sequence[Point], tex_size: tuple[int, int], mode: str) -> Face:
    """Textur an der Seite ausrichten: fit (genau einmal einpassen), left/right/top/bottom
    (Kante bündig), center (mittig)."""
    if mode not in JUSTIFY or not polygon:
        return face
    u, v = face.uaxis, face.vaxis
    us = [_dot(p, u.vec) for p in polygon]
    vs = [_dot(p, v.vec) for p in polygon]
    w, h = tex_size
    su, sv = u.scale or 1.0, v.scale or 1.0
    ou, ov = u.offset, v.offset
    if mode == "fit":
        su = (max(us) - min(us)) / w or su
        sv = (max(vs) - min(vs)) / h or sv
        ou, ov = -min(us) / su, -min(vs) / sv
    elif mode == "left":
        ou = -min(us) / su
    elif mode == "right":
        ou = w - max(us) / su
    elif mode == "top":
        ov = -min(vs) / sv
    elif mode == "bottom":
        ov = h - max(vs) / sv
    elif mode == "center":
        ou = w / 2 - (min(us) + max(us)) / 2 / su
        ov = h / 2 - (min(vs) + max(vs)) / 2 / sv
    ou, ov = _wrap(ou, w), _wrap(ov, h)
    return dataclasses.replace(face, uaxis=TexAxis(u.x, u.y, u.z, ou, round(su, 6)),
                               vaxis=TexAxis(v.x, v.y, v.z, ov, round(sv, 6)))


def shift_by(face: Face, delta: Point, tex_size: tuple[int, int] | None = None) -> Face:
    """Textur so verschieben, dass sie einer Bewegung `delta` (Welt-Units) auf der Seite folgt:
    Der Punkt der Textur, der vorher unter der Maus lag, liegt danach wieder darunter."""
    u, v = face.uaxis, face.vaxis
    ou = u.offset - _dot(delta, u.vec) / (u.scale or 1.0)
    ov = v.offset - _dot(delta, v.vec) / (v.scale or 1.0)
    if tex_size:
        ou, ov = _wrap(ou, tex_size[0]), _wrap(ov, tex_size[1])
    return dataclasses.replace(face, uaxis=TexAxis(u.x, u.y, u.z, round(ou, 4), u.scale),
                               vaxis=TexAxis(v.x, v.y, v.z, round(ov, 4), v.scale))


def scale_by(face: Face, factor: float, anchor: Point, tex_size: tuple[int, int] | None = None) -> Face:
    """Textur um `factor` größer oder kleiner machen; der Punkt `anchor` bleibt stehen."""
    out = []
    for ax, size in ((face.uaxis, tex_size[0] if tex_size else 0), (face.vaxis, tex_size[1] if tex_size else 0)):
        old = ax.scale or 1.0
        new = min(64.0, max(0.01, old * factor))
        p = _dot(anchor, ax.vec)
        offset = ax.offset + p / old - p / new
        out.append(TexAxis(ax.x, ax.y, ax.z, round(_wrap(offset, size) if size else offset, 4), round(new, 6)))
    return dataclasses.replace(face, uaxis=out[0], vaxis=out[1])


def _wrap(offset: float, size: int) -> float:
    """Verschiebung in den Bereich einer Texturbreite bringen (wie Hammer)."""
    r = round(offset % size, 4) if size else offset
    return 0.0 if r == size else r


__all__ = ["JUSTIFY", "align_face", "align_world", "justify", "scale_by", "set_values", "shift_by"]
