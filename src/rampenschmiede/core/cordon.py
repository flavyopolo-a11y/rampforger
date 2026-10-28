"""Cordon („Bereich“): nur einen Teil der Map bauen.

Große Maps brauchen zum Kompilieren lange. Mit einem Bereich baut die Rampenschmiede nur, was
darin liegt, und schließt ihn mit einer Skybox-Hülle ab, damit es kein Leck gibt. Die Map
selbst bleibt unverändert; gespeichert wird der Bereich in `doc.extra["cordon"]`.

Was zählt: Brushes, die den Bereich berühren (ganz, nicht abgeschnitten), Punkt-Entities mit
dem Ursprung darin und Brush-Entities, deren Mitte darin liegt (samt allen ihren Brushes).
Entities ohne Lage (Logik) bleiben immer drin.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .mathutil import BBox
from .model import MapDocument, Solid, owner_id
from .templates.starter import ALL_SPAWNS, hull_around

KEY = "cordon"
#: Kleinster Bereich je Achse
MIN_SIZE = 64


@dataclass
class CordonResult:
    doc: MapDocument
    dropped: int
    spawns: int


def get_cordon(doc: MapDocument) -> tuple[BBox | None, bool]:
    """(Bereich, aktiv). Ohne gesetzten Bereich (None, False)."""
    raw = doc.extra.get(KEY)
    if not isinstance(raw, dict):
        return None, False
    try:
        box = BBox(tuple(float(v) for v in raw["mins"]), tuple(float(v) for v in raw["maxs"]))  # type: ignore[arg-type]
    except (KeyError, TypeError, ValueError):
        return None, False
    return box, bool(raw.get("aktiv", True))


def active_cordon(doc: MapDocument) -> BBox | None:
    box, on = get_cordon(doc)
    return box if on else None


def normalized(box: BBox) -> BBox:
    """Ecken sortieren, auf ganze Zahlen runden, Mindestgröße einhalten."""
    lo, hi = [], []
    for i in range(3):
        a, b = sorted((box.mins[i], box.maxs[i]))
        a, b = math.floor(a), math.ceil(b)
        if b - a < MIN_SIZE:
            mid = (a + b) // 2
            a, b = mid - MIN_SIZE // 2, mid + MIN_SIZE // 2
        lo.append(a)
        hi.append(b)
    return BBox(tuple(lo), tuple(hi))  # type: ignore[arg-type]


def set_cordon(doc: MapDocument, box: BBox | None, active: bool = True) -> None:
    """Bereich setzen (None löscht ihn)."""
    if box is None:
        doc.extra.pop(KEY, None)
        return
    box = normalized(box)
    doc.extra[KEY] = {"mins": list(box.mins), "maxs": list(box.maxs), "aktiv": bool(active)}


def set_active(doc: MapDocument, active: bool) -> bool:
    box, _ = get_cordon(doc)
    if box is None:
        return False
    set_cordon(doc, box, active)
    return True


def apply_cordon(doc: MapDocument, box: BBox) -> CordonResult:
    """Kopie der Map, die nur den Bereich enthält, ringsum mit Skybox abgedichtet."""
    out = doc.snapshot()
    out.extra = {k: v for k, v in doc.extra.items() if k != KEY}
    keep_entities: set[int] = set()
    drop: set[int] = set()
    brush_children: dict[int, list[Solid]] = {}
    for s in doc.solids():
        owner = owner_id(s)
        if owner is not None:
            brush_children.setdefault(owner, []).append(s)
    for e in doc.entities():
        kids = brush_children.get(e.id)
        if kids:
            bb = BBox.union(s.bbox() for s in kids)
            if bb is not None and box.contains(bb.center):
                keep_entities.add(e.id)
            else:
                drop.add(e.id)
        elif e.origin is None or box.contains(e.origin):
            keep_entities.add(e.id)
        else:
            drop.add(e.id)
    for s in doc.solids():
        owner = owner_id(s)
        if owner is not None and doc.get(owner) is not None:
            if owner in drop:
                drop.add(s.id)
            continue
        bb = s.bbox()
        if bb is None or not bb.intersects(box):
            drop.add(s.id)
    for oid in drop:
        out._objects.pop(oid, None)
    for wall in hull_around(out, box):
        out._objects[wall.id] = wall.replace(extra={})
    spawns = sum(1 for oid in keep_entities if (e := doc.get(oid)) is not None and e.classname.lower() in ALL_SPAWNS)
    return CordonResult(out, len(drop), spawns)


__all__ = ["CordonResult", "KEY", "active_cordon", "apply_cordon", "get_cordon", "normalized", "set_active",
           "set_cordon"]
