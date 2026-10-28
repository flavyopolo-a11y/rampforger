"""Aufkleber: Decals (infodecal) und Overlays (info_overlay).

- Ein **Decal** ist ein Punkt auf einer Fläche; die Engine projiziert das Material (meist aus
  `decals/`) beim Laden auf die nächste Fläche, in Texturgröße.
- Ein **Overlay** ist ein Rechteck beliebiger Größe in der Ebene einer Fläche, mit beliebigem
  Material. vbsp schneidet es auf die Seiten zu, die in `sides` stehen.

Overlays aus dem Werkzeug tragen `extra["overlay_auto"]`: Beim Export stehen dann `BasisOrigin`
am Ursprung der Entity (es wandert also beim Verschieben mit) und in `sides` alle Seiten, die in
derselben Ebene liegen und das Rechteck berühren. So bleibt es auch nach Umbauten richtig.
Importierte Overlays bleiben, wie sie sind.
"""
from __future__ import annotations

import math
from typing import Iterable

from .mathutil import BBox
from .model import Entity, MapDocument

DECAL = "infodecal"
OVERLAY = "info_overlay"
AUTO = "overlay_auto"
#: Normale und Größe eines Decals aus dem Werkzeug (fürs Anzeigen; die Engine braucht sie nicht)
DECAL_NORMAL = "decal_normal"
DECAL_SIZE = "decal_size"
DEFAULT_DECAL = "decals/lambdaspray_2a"
#: Abstand der Vorschau über der Fläche, damit sie nicht flimmert
LIFT = 0.25
PLANE_EPS = 0.5

Vec = tuple[float, float, float]


def _norm(v) -> Vec:
    length = math.sqrt(sum(c * c for c in v)) or 1.0
    return (v[0] / length, v[1] / length, v[2] / length)


def _cross(a, b) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec(text: str) -> Vec | None:
    try:
        parts = [float(p) for p in text.split()]
    except ValueError:
        return None
    return (parts[0], parts[1], parts[2]) if len(parts) >= 3 else None


def _fmt(v: Iterable[float]) -> str:
    return " ".join(f"{round(c, 4):g}" for c in v)


def basis(normal) -> tuple[Vec, Vec]:
    """(U, V) in der Ebene: auf Wänden U waagerecht und V nach oben, auf Böden U = +X.
    U × V = Normale (so liest vbsp die Basis)."""
    n = _norm(normal)
    if abs(n[2]) > 0.7:
        u = _norm((1.0, 0.0, 0.0) if n[2] > 0 else (-1.0, 0.0, 0.0))
        u = _norm(_cross(_cross(n, u), n))  # in die Ebene kippen (schräge Böden)
    else:
        u = _norm(_cross((0.0, 0.0, 1.0), n))
    v = _cross(n, u)
    return u, v


def make_decal(doc: MapDocument, point, normal, material: str, size: tuple[int, int]) -> Entity:
    p = tuple(round(c) for c in point)
    return Entity(id=doc.new_id(), classname=DECAL,
                  keyvalues=(("texture", material.lower()), ("origin", _fmt(p))),
                  extra={DECAL_NORMAL: list(_norm(normal)), DECAL_SIZE: list(size)})


def make_overlay(doc: MapDocument, point, normal, material: str, width: float, height: float) -> Entity:
    n = _norm(normal)
    u, v = basis(n)
    p = tuple(round(c) for c in point)
    hw, hh = width / 2, height / 2
    # Ecken in Basis-Koordinaten; vbsp ordnet ihnen (StartU, StartV) … zu. Oben (V+) ist die
    # obere Bildkante (v = 0), damit Schrift aufrecht steht.
    kvs = (
        ("material", material.lower()),
        ("sides", ""),
        ("RenderOrder", "0"),
        ("StartU", "0"), ("EndU", "1"), ("StartV", "1"), ("EndV", "0"),
        ("BasisOrigin", _fmt(p)),
        ("BasisU", _fmt(u)), ("BasisV", _fmt(v)), ("BasisNormal", _fmt(n)),
        ("uv0", _fmt((-hw, -hh, 0))), ("uv1", _fmt((-hw, hh, 0))),
        ("uv2", _fmt((hw, hh, 0))), ("uv3", _fmt((hw, -hh, 0))),
        ("fademindist", "-1"), ("fadedist", "0"),
        ("origin", _fmt(p)), ("angles", "0 0 0"),
    )
    return Entity(id=doc.new_id(), classname=OVERLAY, keyvalues=kvs, extra={AUTO: True})


def is_auto_overlay(ent: Entity) -> bool:
    return ent.classname.lower() == OVERLAY and bool(ent.extra.get(AUTO))


def overlay_corners(ent: Entity) -> tuple[Vec, list[Vec]] | None:
    """(Normale, vier Ecken in Weltkoordinaten) eines Overlays."""
    if ent.classname.lower() != OVERLAY:
        return None
    u, v, n = (_vec(ent.get(k)) for k in ("BasisU", "BasisV", "BasisNormal"))
    origin = ent.origin if is_auto_overlay(ent) else _vec(ent.get("BasisOrigin")) or ent.origin
    if u is None or v is None or n is None or origin is None:
        return None
    pts = []
    for i in range(4):
        c = _vec(ent.get(f"uv{i}"))
        if c is None:
            return None
        pts.append(tuple(origin[k] + u[k] * c[0] + v[k] * c[1] for k in range(3)))
    return _norm(n), pts  # type: ignore[return-value]


def decal_corners(ent: Entity) -> tuple[Vec, list[Vec]] | None:
    """Vorschau-Rechteck eines Decals aus dem Werkzeug (Normale und Größe sind gespeichert)."""
    if ent.classname.lower() != DECAL or ent.origin is None:
        return None
    raw_n, raw_s = ent.extra.get(DECAL_NORMAL), ent.extra.get(DECAL_SIZE)
    if not raw_n or not raw_s:
        return None
    n = _norm(raw_n)
    u, v = basis(n)
    hw, hh = raw_s[0] / 2, raw_s[1] / 2
    o = ent.origin
    pts = [tuple(o[k] + u[k] * a + v[k] * b for k in range(3)) for a, b in ((-hw, -hh), (-hw, hh), (hw, hh), (hw, -hh))]
    return n, pts  # type: ignore[return-value]


def sticker_corners(ent: Entity) -> tuple[Vec, list[Vec]] | None:
    return overlay_corners(ent) or decal_corners(ent)


def sticker_bbox(ent: Entity) -> BBox | None:
    q = sticker_corners(ent)
    if q is None:
        return None
    n, pts = q
    lifted = [tuple(p[k] + n[k] * s for k in range(3)) for p in pts for s in (-1.0, 1.0)]
    return BBox.from_points(lifted)  # type: ignore[arg-type]


def overlay_sides(doc: MapDocument, ent: Entity) -> list[tuple[int, int]]:
    """(Brush-ID, Seiten-Index) aller Seiten in der Ebene des Overlays, die es berühren."""
    q = overlay_corners(ent)
    if q is None:
        return []
    n, pts = q
    dist = _dot(n, pts[0])
    box = BBox.from_points(pts)
    assert box is not None
    box = BBox(tuple(c - 1 for c in box.mins), tuple(c + 1 for c in box.maxs))  # type: ignore[arg-type]
    out = []
    for s in doc.solids():
        bb = s.bbox()
        if bb is None or not bb.intersects(box):
            continue
        for i, (face, poly) in enumerate(zip(s.faces, s.polygons())):
            fn = face.plane.normal
            if not poly or _dot(fn, n) < 0.999 or abs(_dot(fn, poly[0]) - dist) > PLANE_EPS:
                continue
            fb = BBox.from_points(poly)
            if fb is not None and fb.intersects(box):
                out.append((s.id, i))
    return out


__all__ = ["AUTO", "DECAL", "DEFAULT_DECAL", "OVERLAY", "basis", "decal_corners", "is_auto_overlay", "make_decal",
           "make_overlay", "overlay_corners", "overlay_sides", "sticker_bbox", "sticker_corners"]
