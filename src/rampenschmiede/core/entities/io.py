"""I/O-Verbindungen zwischen Entities: wen ein Ausgang trifft, wer eine Entity anspricht,
und Linien dafür in den Ansichten."""
from __future__ import annotations

from typing import Iterable

from ..mathutil import BBox, Point
from ..model import Entity, MapDocument, Output, object_bbox

#: Farben der Verbindungslinien: ausgehend (grün), eingehend (orange)
OUT_COLOR = (0.35, 0.85, 0.45)
IN_COLOR = (1.0, 0.6, 0.2)


def entities_named(doc: MapDocument, name: str) -> list[Entity]:
    """Ziele eines Ausgangs: über den Namen (oder Klassennamen), mit * am Ende als Präfix.
    Sonderziele wie !activator stehen erst im Spiel fest."""
    if not name or name.startswith("!"):
        return []
    low = name.lower()
    if low.endswith("*"):
        return [e for e in doc.entities() if e.get("targetname").lower().startswith(low[:-1])]
    return [e for e in doc.entities() if e.get("targetname").lower() == low or e.classname.lower() == low]


def incoming(doc: MapDocument, ent: Entity) -> list[tuple[Entity, Output]]:
    """Ausgänge anderer Entities, die diese Entity treffen."""
    if not ent.get("targetname"):
        return []
    out = []
    for other in doc.entities():
        for o in other.outputs:
            if any(t.id == ent.id for t in entities_named(doc, o.target)):
                out.append((other, o))
    return out


def target_names(doc: MapDocument) -> list[str]:
    return sorted({n for e in doc.entities() if (n := e.get("targetname"))}, key=str.lower)


def entity_center(doc: MapDocument, ent: Entity) -> Point | None:
    """Mitte einer Entity: Ursprung, bei Brush-Entities die Mitte ihrer Brushes."""
    bb = BBox.union(s.bbox() for s in doc.children(ent.id)) or object_bbox(ent)
    return bb.center if bb is not None else None


def io_segments(doc: MapDocument, ids: Iterable[int]) -> list[tuple[Point, Point, tuple[float, float, float]]]:
    """Linien von den gewählten Entities zu ihren Zielen und von ihren Quellen zu ihnen."""
    segs = []
    seen: set[tuple[int, int]] = set()
    for i in ids:
        ent = doc.get(i)
        if not isinstance(ent, Entity):
            continue
        a = entity_center(doc, ent)
        if a is None:
            continue
        for o in ent.outputs:
            for t in entities_named(doc, o.target):
                b = entity_center(doc, t)
                if b is not None and t.id != ent.id and (ent.id, t.id) not in seen:
                    seen.add((ent.id, t.id))
                    segs.append((a, b, OUT_COLOR))
        for src, _ in incoming(doc, ent):
            b = entity_center(doc, src)
            if b is not None and src.id != ent.id and (src.id, ent.id) not in seen:
                seen.add((src.id, ent.id))
                segs.append((b, a, IN_COLOR))
    return segs
