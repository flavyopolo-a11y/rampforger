"""Vom Log-Eintrag zum Objekt: Brush-ID, Entity-Nummer oder Position auflösen."""
from __future__ import annotations

from dataclasses import dataclass

from ..io.vmf import ExportResult
from ..mathutil import vec
from ..model import Entity, MapDocument, object_bbox
from .logparse import LogLine


@dataclass(frozen=True)
class Target:
    object_ids: tuple[int, ...] = ()
    position: tuple[float, float, float] | None = None


def resolve(line: LogLine, export: ExportResult | None, doc: MapDocument) -> Target | None:
    ids: list[int] = []
    if export is not None:
        if line.brush_id is not None:
            oid = export.solid_ids.get(line.brush_id)
            if oid is not None and oid in doc:
                ids.append(oid)
        if not ids and line.entity_index:
            i = line.entity_index - 1  # 0 ist die Welt
            if 0 <= i < len(export.entity_order) and export.entity_order[i] in doc:
                ids.append(export.entity_order[i])
    if not ids and line.position is not None:
        near = nearest_object(doc, line.position)
        if near is not None:
            ids.append(near)
    if not ids and line.position is None:
        return None
    return Target(tuple(ids), line.position)


def nearest_object(doc: MapDocument, pos: tuple[float, float, float], max_dist: float = 64.0) -> int | None:
    """Das Objekt, dessen Box der Position am nächsten ist (Point-Entities bevorzugt)."""
    best, best_d = None, max_dist
    for obj in doc.objects():
        box = object_bbox(obj)
        if box is None:
            continue
        clamped = tuple(min(max(pos[i], box.mins[i]), box.maxs[i]) for i in range(3))
        d = vec.length(vec.sub(pos, clamped))
        if isinstance(obj, Entity):
            d -= 0.5  # bei Gleichstand gewinnt die Entity, die das Leck meldet
        if d < best_d:
            best, best_d = obj.id, d
    return best
