"""Startraum für neue Maps: Spawn, Sonne und eine dichte Skybox-Hülle.

Eine neue Map lässt sich damit sofort ohne Leck kompilieren. Die Hülle besteht aus sechs
normalen Brushes, die man verschieben, vergrößern oder löschen kann.
"""
from __future__ import annotations

from ..geometry import primitives
from ..mathutil import BBox, Point
from ..model import EditorInfo, Entity, MapDocument, MapObject, Solid

SKY = "TOOLS/TOOLSSKYBOX"
FLOOR = "DEV/DEV_MEASUREGENERIC01B"
HULL_COLOR = (90, 160, 220)

#: Welche Spawn-Entities ein Spiel braucht. Unbekannte Spiele bekommen alle.
SPAWN_CLASSES: dict[str, tuple[str, ...]] = {
    "css": ("info_player_counterterrorist", "info_player_terrorist"),
    "momentum": ("info_player_start",),
}
ALL_SPAWNS = ("info_player_start", "info_player_counterterrorist", "info_player_terrorist")


def _box(doc: MapDocument, mins: Point, maxs: Point, material: str) -> Solid:
    faces = primitives.block(mins, maxs, material)[0]
    return Solid(id=doc.new_id(), faces=faces, editor=EditorInfo(color=HULL_COLOR))


def hull_around(doc: MapDocument, inner: BBox, thickness: int = 16, floor_material: str = SKY,
                material: str = SKY) -> list[Solid]:
    """Sechs Brushes, die den Innenraum `inner` lückenlos umschließen (Wände überlappen nicht)."""
    (x0, y0, z0), (x1, y1, z1) = inner.mins, inner.maxs
    t = thickness
    return [
        _box(doc, (x0 - t, y0 - t, z0 - t), (x1 + t, y1 + t, z0), floor_material),  # Boden
        _box(doc, (x0 - t, y0 - t, z1), (x1 + t, y1 + t, z1 + t), material),        # Decke
        _box(doc, (x0 - t, y0 - t, z0), (x0, y1 + t, z1), material),                # -X
        _box(doc, (x1, y0 - t, z0), (x1 + t, y1 + t, z1), material),                # +X
        _box(doc, (x0, y0 - t, z0), (x1, y0, z1), material),                        # -Y
        _box(doc, (x0, y1, z0), (x1, y1 + t, z1), material),                        # +Y
    ]


def starter_room(doc: MapDocument, game: str | None = None, half_size: int = 512, height: int = 512) -> list[MapObject]:
    """Innenraum von (-half, -half, 0) bis (half, half, height), Boden-Oberkante bei z = 0."""
    inner = BBox((-half_size, -half_size, 0), (half_size, half_size, height))
    objs: list[MapObject] = list(hull_around(doc, inner, floor_material=FLOOR))
    classes = SPAWN_CLASSES.get(game or "", ALL_SPAWNS)
    for i, cls in enumerate(classes):
        x = -half_size // 2 + i * 64
        objs.append(Entity(id=doc.new_id(), classname=cls,
                           keyvalues=(("origin", f"{x} {-half_size // 2} 8"), ("angles", "0 90 0"))))
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
