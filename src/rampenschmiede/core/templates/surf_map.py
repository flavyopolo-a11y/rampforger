"""Assistent „Neue Surf-Map“: eine spielbare lineare Surf-Map aus Stages.

Jede Stage besteht aus einer Startplattform (mit Teleport-Ziel und Zeitnahme-Zone), einigen Rampen in einer
Linie, die nacheinander tiefer liegen, und einem Fall-Teleporter am Boden, der zurück zum
Anfang der Stage bringt. Am Ende steht eine Zielplattform. Um alles kommt eine dichte
Skybox-Hülle, die Map lässt sich also sofort kompilieren und durchspielen.

Die Rampen und Teleporter sind Bausteine und bleiben über ihre Regler änderbar.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..blocks import build_block
from ..geometry import primitives
from ..mathutil import BBox
from ..model import EditorInfo, Entity, MapDocument, MapObject, Solid, object_bbox
from ..surf.catalog import CATALOG, Placement, ramp_height
from .starter import ALL_SPAWNS, SPAWN_CLASSES, enclose_map

#: Source-Maps dürfen von -16384 bis 16384 reichen
MAP_LIMIT = 16384
PLATFORM = "DEV/DEV_MEASUREGENERIC01B"
PLATFORM_COLOR = (120, 200, 140)
RAMP_KINDS = ("gerade", "ski", "banane", "welle", "trapez")


@dataclass
class SurfMapSettings:
    game: str | None = None
    stages: int = 3
    ramps_per_stage: int = 2
    ramp_kind: str = "gerade"
    ramp_length: int = 2048
    ramp_width: int = 960
    angle: float = 50.0
    #: Lücke zwischen zwei Rampen, über die man springt
    gap: int = 256
    #: Wie viel tiefer jede folgende Rampe liegt
    drop: int = 192
    platform: int = 512


def _box(doc: MapDocument, mins, maxs, material: str = PLATFORM) -> Solid:
    faces = primitives.block(mins, maxs, material)[0]
    return Solid(id=doc.new_id(), faces=faces, editor=EditorInfo(color=PLATFORM_COLOR))


def _platform(doc: MapDocument, x: int, top: int, size: int) -> Solid:
    half = size // 2
    return _box(doc, (x, -half, top - 32), (x + size, half, top))


def _zone(doc: MapDocument, template: str, x: int, top: int, size: int, **values) -> list[MapObject]:
    """Zone über einer Plattform, 32 Units Rand rundherum."""
    inner = size - 64
    objs, _gen = build_block(doc, template, {"laenge": inner, "breite": inner, "hoehe": 128, **values},
                             Placement(x + 32, 0, top, 0))
    return objs


def total_length(s: SurfMapSettings) -> int:
    per_stage = s.platform + s.gap + s.ramps_per_stage * (s.ramp_length + s.gap)
    return s.stages * per_stage + s.platform


def new_surf_map(doc: MapDocument, s: SurfMapSettings) -> list[MapObject]:
    """Alle Objekte der Map. Die Rampen laufen entlang +X, Spieler starten im Westen.
    Die Map wird um den Nullpunkt gelegt. ValueError, wenn sie zu groß für Source wäre."""
    if s.stages < 1 or s.ramps_per_stage < 1:
        raise ValueError("Mindestens eine Stage mit einer Rampe")
    length = total_length(s)
    kind = s.ramp_kind if s.ramp_kind in CATALOG else "gerade"
    ramp_values = {"laenge": s.ramp_length, "breite": s.ramp_width, "winkel": s.angle}
    template = CATALOG[kind]
    if kind == "ski":
        ramp_values["gefaelle"] = -s.ramp_length // 4
    height = ramp_height(template.values(ramp_values))
    drop_along = template.values(ramp_values).get("gefaelle", 0)

    objs: list[MapObject] = []
    stages: list[tuple[int, int, int]] = []  # (x_anfang, x_ende, Plattform-Oberkante)
    x, top = -(length // 2) // 16 * 16, int(height) + 512
    lowest = top
    for stage in range(s.stages):
        start_x, platform_top = x, top
        objs.append(_platform(doc, x, top, s.platform))
        if stage == 0:
            objs += _zone(doc, "zone_start", x, top, s.platform)
        else:
            objs += _zone(doc, "zone_stage", x, top, s.platform, nummer=stage + 1)
        name = f"stage_{stage + 1}"
        objs.append(Entity(id=doc.new_id(), classname="info_teleport_destination", keyvalues=(
            ("targetname", name), ("origin", f"{x + 128} 0 {top + 8}"), ("angles", "0 0 0"))))
        if stage == 0:
            for i, cls in enumerate(SPAWN_CLASSES.get(s.game or "", ALL_SPAWNS)):
                objs.append(Entity(id=doc.new_id(), classname=cls, keyvalues=(
                    ("origin", f"{x + 96} {(i - 1) * 64} {top + 8}"), ("angles", "0 0 0"))))
        x += s.platform + s.gap
        ramp_top = top - 96
        for _ in range(s.ramps_per_stage):
            anchor_z = int(ramp_top - height)
            ramp, _gen = build_block(doc, kind, ramp_values, Placement(x, 0, anchor_z, 0))
            objs += ramp
            lowest = min(lowest, anchor_z + min(0, drop_along))
            x += s.ramp_length + s.gap
            ramp_top += drop_along - s.drop
        # Nächste Plattform etwa auf halber Höhe der letzten Rampe: erreichbar mit Schwung
        top = int(ramp_top + s.drop - height / 2)
        stages.append((start_x, x, platform_top))

    # Ziel
    objs.append(_platform(doc, x, top, s.platform))
    objs += _zone(doc, "zone_ende", x, top, s.platform)
    objs.append(Entity(id=doc.new_id(), classname="info_target", keyvalues=(
        ("targetname", "ziel"), ("origin", f"{x + s.platform // 2} 0 {top + 32}"))))
    end_x = x + s.platform

    # Fall-Teleporter unter jeder Stage, über die ganze Breite
    floor = lowest - 256
    width = s.ramp_width + 1024
    for i, (x0, x1, _top) in enumerate(stages):
        trig, _gen = build_block(doc, "teleporter", {
            "laenge": x1 - x0, "breite": width, "hoehe": 64, "ziel": f"stage_{i + 1}"}, Placement(x0, 0, floor, 0))
        objs += trig
    # Boden unter allem, damit man nicht ins Leere fällt
    first_x = stages[0][0]
    objs.append(_box(doc, (first_x - 256, -width // 2 - 256, floor - 32), (end_x + 256, width // 2 + 256, floor)))
    objs.append(Entity(id=doc.new_id(), classname="light_environment", keyvalues=(
        ("origin", f"0 0 {top + 256}"), ("_light", "255 240 220 300"), ("_ambient", "150 170 200 40"),
        ("angles", "-50 45 0"), ("pitch", "-50"))))

    bounds = BBox.union(object_bbox(o) for o in objs)
    assert bounds is not None
    if any(abs(c) > MAP_LIMIT - 600 for c in (*bounds.mins, *bounds.maxs)):
        size = round(max(bounds.size)) + 2 * 528
        raise ValueError(
            f"Die Map wäre mit Hülle etwa {size} Units lang; Source erlaubt höchstens {2 * MAP_LIMIT}. "
            "Weniger Stages, weniger oder kürzere Rampen wählen.")
    objs += enclose_map(doc, margin=512, bounds=bounds)
    return objs
