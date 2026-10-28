"""Startraum für neue Maps: Spawn, Sonne und eine dichte Skybox-Hülle.

Eine neue Map lässt sich damit sofort ohne Leck kompilieren. Die Hülle besteht aus sechs
normalen Brushes, die man verschieben, vergrößern oder löschen kann. Sie wächst mit: Ragt
etwas aus ihr heraus, wird sie größer (`grow_hull`), kleiner wird sie nie von selbst.
"""
from __future__ import annotations

import dataclasses
import math

from ..commands import Command, ReplaceObjects
from ..geometry import primitives
from ..mathutil import BBox, Point
from ..model import EditorInfo, Entity, MapDocument, MapObject, Solid, object_bbox

SKY = "TOOLS/TOOLSSKYBOX"
FLOOR = "DEV/DEV_MEASUREGENERIC01B"
HULL_COLOR = (90, 160, 220)
START_COLOR = (240, 150, 40)
#: Kantenlänge des Startblocks im Startraum
START_BLOCK = 512
#: Kennzeichen der Hüllen-Brushes in `Solid.extra`, Wert = Seite
HULL_KEY = "huelle"
HULL_SIDES = ("boden", "decke", "-x", "+x", "-y", "+y")
#: So viel Luft lässt die mitwachsende Hülle um den Inhalt, gerundet auf HULL_SNAP
HULL_MARGIN = 512
HULL_SNAP = 64

#: Welche Spawn-Entities ein Spiel braucht. Unbekannte Spiele bekommen alle.
SPAWN_CLASSES: dict[str, tuple[str, ...]] = {
    "css": ("info_player_counterterrorist", "info_player_terrorist"),
    "momentum": ("info_player_start",),
}
ALL_SPAWNS = ("info_player_start", "info_player_counterterrorist", "info_player_terrorist")


def _box(doc: MapDocument, mins: Point, maxs: Point, material: str, side: str) -> Solid:
    faces = primitives.block(mins, maxs, material)[0]
    return Solid(id=doc.new_id(), faces=faces, editor=EditorInfo(color=HULL_COLOR), extra={HULL_KEY: side})


def hull_around(doc: MapDocument, inner: BBox, thickness: int = 16, floor_material: str = SKY,
                material: str = SKY) -> list[Solid]:
    """Sechs Brushes, die den Innenraum `inner` lückenlos umschließen (Wände überlappen nicht)."""
    (x0, y0, z0), (x1, y1, z1) = inner.mins, inner.maxs
    t = thickness
    return [
        _box(doc, (x0 - t, y0 - t, z0 - t), (x1 + t, y1 + t, z0), floor_material, "boden"),
        _box(doc, (x0 - t, y0 - t, z1), (x1 + t, y1 + t, z1 + t), material, "decke"),
        _box(doc, (x0 - t, y0 - t, z0), (x0, y1 + t, z1), material, "-x"),
        _box(doc, (x1, y0 - t, z0), (x1 + t, y1 + t, z1), material, "+x"),
        _box(doc, (x0, y0 - t, z0), (x1, y0, z1), material, "-y"),
        _box(doc, (x0, y1, z0), (x1, y1 + t, z1), material, "+y"),
    ]


def start_zone_on(doc: MapDocument, block: Solid, yaw: float = 0.0) -> list[MapObject]:
    """Startzone auf `block`; sie folgt ihm beim Verschieben und Vergrößern."""
    from ..attach import SITS_ON, fit_on, link
    from ..blocks import build_block

    box = block.bbox()
    assert box is not None
    values, at = fit_on(box, yaw)
    objs, _gen = build_block(doc, "zone_start", {**values, "hoehe": 128}, at)
    objs[0] = objs[0].replace(extra={**objs[0].extra, SITS_ON: link(block.id, box)})
    return objs


def starter_room(doc: MapDocument, game: str | None = None, half_size: int = 4096, height: int = 3072) -> list[MapObject]:
    """Innenraum von (-half, -half, 0) bis (half, half, height), Boden-Oberkante bei z = 0."""
    inner = BBox((-half_size, -half_size, 0), (half_size, half_size, height))
    objs: list[MapObject] = list(hull_around(doc, inner, floor_material=FLOOR))
    # Startblock mit Startzone darauf (die Zone folgt dem Block), Spawns stehen in der Zone
    cx, cy = -half_size // 2, -half_size // 2
    half = START_BLOCK // 2
    block = Solid(id=doc.new_id(), faces=primitives.block((cx - half, cy - half, 0), (cx + half, cy + half, 32),
                                                          FLOOR)[0], editor=EditorInfo(color=START_COLOR))
    objs.append(block)
    objs += start_zone_on(doc, block, yaw=90)
    classes = SPAWN_CLASSES.get(game or "", ALL_SPAWNS)
    for i, cls in enumerate(classes):
        x = cx - 64 + i * 64
        objs.append(Entity(id=doc.new_id(), classname=cls,
                           keyvalues=(("origin", f"{x} {cy - 64} 40"), ("angles", "0 90 0"))))
    objs.append(Entity(id=doc.new_id(), classname="light_environment", keyvalues=(
        ("origin", f"0 0 {height - 64}"), ("_light", "255 240 220 300"), ("_ambient", "150 170 200 40"),
        ("angles", "-50 45 0"), ("pitch", "-50"))))
    return objs


def enclose_map(doc: MapDocument, margin: int = 256, snap: int = 64, bounds: BBox | None = None) -> list[Solid]:
    """Skybox-Hülle um alles, was in der Map ist (oder um `bounds`), mit Abstand `margin`,
    auf `snap` gerundet."""
    import math

    bounds = bounds or doc.bbox()
    if bounds is None:
        bounds = BBox((0, 0, 0), (0, 0, 0))
    lo = tuple(int(math.floor((bounds.mins[i] - margin) / snap) * snap) for i in range(3))
    hi = tuple(int(math.ceil((bounds.maxs[i] + margin) / snap) * snap) for i in range(3))
    return hull_around(doc, BBox(lo, hi))


def hull_parts(doc: MapDocument) -> dict[str, Solid] | None:
    """Die sechs Brushes der mitwachsenden Hülle, oder None, wenn es sie nicht (mehr) genau
    einmal gibt (gelöscht, doppelt, von Hand umgebaut)."""
    parts: dict[str, Solid] = {}
    for s in doc.solids():
        side = s.extra.get(HULL_KEY)
        if side is None:
            continue
        if side in parts or side not in HULL_SIDES:
            return None
        parts[side] = s
    return parts if len(parts) == len(HULL_SIDES) else None


def _main_material(s: Solid) -> str:
    counts: dict[str, int] = {}
    for f in s.faces:
        counts[f.material] = counts.get(f.material, 0) + 1
    return max(counts, key=lambda m: counts[m])


def grow_hull(doc: MapDocument, margin: int = HULL_MARGIN, snap: int = HULL_SNAP) -> Command | None:
    """Hülle vergrößern, wenn der Inhalt ihr näher kommt als `margin` oder aus ihr herausragt.
    Die Brushes behalten ihre IDs und Materialien. Liefert None, wenn alles passt."""
    parts = hull_parts(doc)
    if parts is None:
        return None
    boxes = {side: s.bbox() for side, s in parts.items()}
    if any(b is None for b in boxes.values()):
        return None
    inner_lo = [boxes["-x"].maxs[0], boxes["-y"].maxs[1], boxes["boden"].maxs[2]]  # type: ignore[union-attr]
    inner_hi = [boxes["+x"].mins[0], boxes["+y"].mins[1], boxes["decke"].mins[2]]  # type: ignore[union-attr]
    hull_ids = {s.id for s in parts.values()}
    # Brushes brauchen Platz drumherum, Punkt-Entities (Spawn, Sonne) nur ein wenig
    solids = BBox.union(object_bbox(o) for o in doc.objects()
                        if o.id not in hull_ids and isinstance(o, Solid))
    points = BBox.union(object_bbox(o) for o in doc.objects()
                        if isinstance(o, Entity) and not doc.children(o.id))
    lo, hi = list(inner_lo), list(inner_hi)
    for box, room in ((solids, margin), (points, 16)):
        if box is None:
            continue
        for i in range(3):
            # Der Boden ist Teil der Map: Was auf ihm steht, schiebt ihn nicht nach unten
            need_lo = box.mins[i] - (room if i < 2 or box.mins[2] < inner_lo[2] else 0)
            need_hi = box.maxs[i] + room
            if need_lo < lo[i]:
                lo[i] = int(math.floor(need_lo / snap) * snap)
            if need_hi > hi[i]:
                hi[i] = int(math.ceil(need_hi / snap) * snap)
    if lo == inner_lo and hi == inner_hi:
        return None
    thickness = int(round(boxes["boden"].maxs[2] - boxes["boden"].mins[2])) or 16  # type: ignore[union-attr]
    tmp = MapDocument()
    fresh = hull_around(tmp, BBox(tuple(lo), tuple(hi)), thickness,  # type: ignore[arg-type]
                        floor_material=_main_material(parts["boden"]), material=_main_material(parts["decke"]))
    new: list[MapObject] = []
    for f in fresh:
        side = f.extra[HULL_KEY]
        old = parts[side]
        faces = f.faces if side in ("boden", "decke") else tuple(
            dataclasses.replace(face, material=_main_material(old)) for face in f.faces)
        new.append(dataclasses.replace(old, faces=faces))
    return ReplaceObjects(new, "Hülle vergrößern")

