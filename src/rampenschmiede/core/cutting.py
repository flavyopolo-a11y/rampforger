"""Schneide-Werkzeuge auf Objekt-Ebene: Brushes an einer Ebene teilen (Clip), mit einem
Brush aushöhlen (Carve) und ein Loch oder Fenster durch Brushes schneiden.

Bausteine bleiben unangetastet: Ihre Brushes entstehen aus den Reglern und würden beim
nächsten Neubau wieder heil. Wer einen Baustein schneiden will, löst ihn vorher.
"""
from __future__ import annotations

import dataclasses
from typing import Iterable, Literal

from .blocks import MEMBER_KEY, is_block_root
from .commands import Command, SwapObjects
from .geometry import primitives
from .geometry.csg import carve, split
from .mathutil import BBox, Point
from .model import MapDocument, Solid

Keep = Literal["both", "back", "front"]


def cuttable(doc: MapDocument, obj) -> bool:
    """Normale Brushes in der Welt oder in Brush-Entities, keine Teile von Bausteinen."""
    if not isinstance(obj, Solid) or MEMBER_KEY in obj.extra:
        return False
    return obj.parent_id is None or not is_block_root(doc.get(obj.parent_id))


def _solids(doc: MapDocument, ids: Iterable[int]) -> list[Solid]:
    out: dict[int, Solid] = {}
    for i in ids:
        obj = doc.get(i)
        if isinstance(obj, Solid):
            if cuttable(doc, obj):
                out[obj.id] = obj
        elif obj is not None and not is_block_root(obj):
            for child in doc.children(obj.id):
                if cuttable(doc, child):
                    out[child.id] = child
    return list(out.values())


def _pieces(doc: MapDocument, original: Solid, face_sets: list) -> list[Solid]:
    """Erstes Stück behält die ID (Auswahl bleibt), weitere bekommen neue."""
    out = []
    for k, faces in enumerate(face_sets):
        out.append(dataclasses.replace(original, id=original.id if k == 0 else doc.new_id(), faces=tuple(faces),
                                       vmf_id=original.vmf_id if k == 0 else None, extra=dict(original.extra)))
    return out


def clip(doc: MapDocument, ids: Iterable[int], points: tuple[Point, Point, Point],
         keep: Keep = "both") -> tuple[Command | None, list[int]]:
    """Brushes an der Ebene durch drei Punkte teilen. „back“ behält die Seite hinter der Ebene
    (gegen ihre Normale), „front“ die davor. Liefert Command und die IDs der Ergebnis-Brushes."""
    remove: list[int] = []
    add: list[Solid] = []
    for s in _solids(doc, ids):
        back, front = split(s.faces, points)
        if back is None or front is None:
            continue  # Ebene geht nicht durch diesen Brush
        sets = {"both": [back, front], "back": [back], "front": [front]}[keep]
        remove.append(s.id)
        add += _pieces(doc, s, sets)
    if not remove:
        return None, []
    return SwapObjects(remove, add, "Schneiden"), [s.id for s in add]


def carve_with(doc: MapDocument, cutter_ids: Iterable[int]) -> tuple[Command | None, list[int]]:
    """Alle anderen Brushes, die die Schneide-Brushes durchdringen, aushöhlen. Die
    Schneide-Brushes selbst bleiben (wie in Hammer)."""
    cutters = [c for i in cutter_ids if isinstance(c := doc.get(i), Solid)]
    cutters += [c for i in cutter_ids if (o := doc.get(i)) is not None and not isinstance(o, Solid)
                for c in doc.children(o.id) if isinstance(c, Solid)]
    skip = {c.id for c in cutters}
    targets = [s for s in doc.solids() if s.id not in skip and cuttable(doc, s)]
    return _carve(doc, targets, [c.faces for c in cutters], "Aushöhlen")


def _carve(doc: MapDocument, targets: list[Solid], cutters: list[tuple], description: str) -> tuple[Command | None, list[int]]:
    boxes = [BBox.from_points([p for poly in _polys(c) for p in poly]) for c in cutters]
    remove: list[int] = []
    add: list[Solid] = []
    for s in targets:
        bb = s.bbox()
        if bb is None:
            continue
        current: list[tuple] = [s.faces]
        touched = False
        for cutter, cbox in zip(cutters, boxes):
            if cbox is None or not _overlap(bb, cbox):
                continue
            nxt: list[tuple] = []
            for faces in current:
                pieces = carve(faces, cutter)
                if pieces is None:
                    nxt.append(faces)
                else:
                    touched = True
                    nxt += pieces
            current = nxt
        if touched:
            remove.append(s.id)
            add += _pieces(doc, s, current)
    if not remove:
        return None, []
    return SwapObjects(remove, add, description), [s.id for s in add]


def hole(doc: MapDocument, ids: Iterable[int], axes: tuple[int, int, int],
         rect: tuple[float, float, float, float]) -> tuple[Command | None, list[int]]:
    """Loch oder Fenster: ein Rechteck aus einer 2D-Ansicht (min_h, min_v, max_h, max_v)
    ganz durch die gewählten Brushes schneiden. `axes` sind (waagerecht, senkrecht, Blickachse)."""
    targets = _solids(doc, ids)
    bb = BBox.union(s.bbox() for s in targets)
    if bb is None:
        return None, []
    h, v, axis = axes
    mins = [0, 0, 0]
    maxs = [0, 0, 0]
    mins[h], mins[v], maxs[h], maxs[v] = rect[0], rect[1], rect[2], rect[3]
    mins[axis], maxs[axis] = int(bb.mins[axis]) - 16, int(bb.maxs[axis]) + 16
    if maxs[h] <= mins[h] or maxs[v] <= mins[v]:
        return None, []
    cutter = primitives.block(tuple(mins), tuple(maxs))[0]  # type: ignore[arg-type]
    return _carve(doc, targets, [cutter], "Loch schneiden")


def _offset(faces, distance: float) -> tuple:
    """Alle Seiten um `distance` entlang ihrer Normale verschieben (positiv = nach außen)."""
    out = []
    for f in faces:
        n = f.plane.normal
        pts = tuple(tuple(_tidy(p[k] + n[k] * distance) for k in range(3)) for p in f.points)
        out.append(dataclasses.replace(f, points=pts, vmf_id=None))
    return tuple(out)


def _tidy(v: float) -> float:
    r = round(v)
    return float(r) if abs(v - r) < 1e-6 else round(v, 4)


def hollow(doc: MapDocument, ids: Iterable[int], thickness: float) -> tuple[Command | None, list[int]]:
    """Hohl machen (Strg+Shift+H): aus jedem Brush werden Wände der Stärke `thickness`.
    Positiv: Wände nach innen (Außenmaß bleibt), negativ: nach außen (Innenraum = alter Brush).
    Brushes, die für die Wandstärke zu dünn sind, bleiben unverändert."""
    remove: list[int] = []
    add: list[Solid] = []
    for s in _solids(doc, ids):
        if thickness > 0:
            outer, inner = s.faces, _offset(s.faces, -thickness)
        else:
            outer, inner = _offset(s.faces, -thickness), s.faces
        polys = _polys(inner)
        if len(polys) < 4 or len([p for p in _polys(outer) if p]) < 4:
            continue  # zu dünn: der innere Brush wäre leer
        inner_box = BBox.from_points([p for poly in polys for p in poly])
        if inner_box is None or min(inner_box.size) < 1:
            continue
        pieces = carve(outer, inner)
        if not pieces:
            continue
        remove.append(s.id)
        add += _pieces(doc, s, pieces)
    if not remove:
        return None, []
    return SwapObjects(remove, add, "Hohl machen"), [s.id for s in add]


def _polys(faces) -> list:
    from .geometry.brush import solid_polygons

    return [p for p in solid_polygons(faces) if p]


def _overlap(a: BBox, b: BBox) -> bool:
    return all(a.mins[i] < b.maxs[i] and b.mins[i] < a.maxs[i] for i in range(3))


__all__ = ["Keep", "carve_with", "clip", "cuttable", "hole", "hollow"]
