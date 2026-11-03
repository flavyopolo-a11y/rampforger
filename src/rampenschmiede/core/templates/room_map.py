"""Rahmen einer Surf-Map aus Räumen (Easy Mode): jede Stage und jeder Bonus ist ein eigener Raum.

Ein Raum ist ein großes, freies Quadrat mit unsichtbaren Skybox-Wänden. Darin stehen nur eine
Startplattform (Teleport-Ziel, Zeitnahme-Zone, beim ersten Raum die Spawns) und eine tiefer liegende
Zielplattform, die zur nächsten Stage teleportiert oder die Zielzone trägt. Den Boden deckt ein
Fall-Teleporter, der zurück zum Start des Raums bringt. Die Rampen dazwischen malt man selbst, in
jede Richtung und mit Kurven; die Zielplattform verschiebt man dorthin, wo die Strecke endet.

Eine lineare Map ist ein einziger großer Raum. Die Räume liegen in einem Raster nebeneinander.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ...i18n import N_, tr
from ..attach import SITS_ON, fit_on, link
from ..blocks import build_block
from ..geometry import primitives
from ..mathutil import BBox
from ..model import EditorInfo, Entity, MapDocument, MapObject, Solid, object_bbox
from ..surf.catalog import Placement
from .starter import SKY, cubemap, enclose_map, spawn_entities
from .surf_map import MAP_LIMIT, PLATFORM, PLATFORM_COLOR, PlanItem

#: Größe eines Stage-Raums: Name, Kantenlänge, Höhe (Units)
STAGE_ROOMS = ((N_("Klein"), 3072, 3072), (N_("Mittel"), 4096, 3584), (N_("Groß"), 6144, 4096),
               (N_("Riesig"), 8192, 4608))
#: Größe des einen Raums einer linearen Map
LINEAR_ROOMS = ((N_("Mittel"), 8192, 4608), (N_("Groß"), 12288, 5632), (N_("Riesig"), 16384, 6144))
PLATFORM_SIZE = 512
WALL = 32
WALL_COLOR = (90, 150, 220)


@dataclass(frozen=True)
class RoomSpec:
    """Ein Raum: Name (leer = „Stage 1“ …) und Kantenlänge in Units."""

    name: str = ""
    size: int = 4096


@dataclass
class RoomMapSettings:
    game: str | None = None
    stages: tuple[RoomSpec, ...] = (RoomSpec(), RoomSpec(), RoomSpec())
    bonuses: tuple[RoomSpec, ...] = field(default_factory=tuple)
    #: True: eine durchgehende Strecke in einem Raum (nur die erste Stage zählt)
    linear: bool = False

    def courses(self) -> list[tuple[str, int, RoomSpec]]:
        """(Art, Nummer, Raum) in Bau-Reihenfolge: „stage“ 1, 2, … und „bonus“ 1, 2, …"""
        mains = self.stages[:1] if self.linear else self.stages
        return [("stage", i, s) for i, s in enumerate(mains, 1)] + [("bonus", i, b) for i, b in enumerate(self.bonuses, 1)]


def room_height(size: int) -> int:
    for _name, s, h in (*STAGE_ROOMS, *LINEAR_ROOMS):
        if s >= size:
            return h
    return LINEAR_ROOMS[-1][2]


def room_grid(sizes: list[int]) -> list[tuple[int, int]]:
    """Südwest-Ecke jedes Raums (x, y), im Raster um den Nullpunkt gelegt. Reihen von West nach Ost,
    die erste Reihe im Norden, damit man die Stages wie Text liest."""
    if not sizes:
        return []
    cols = math.ceil(math.sqrt(len(sizes)))
    rows = [sizes[i:i + cols] for i in range(0, len(sizes), cols)]
    widths = [sum(r) for r in rows]
    depths = [max(r) for r in rows]
    total_w, total_d = max(widths), sum(depths)
    out: list[tuple[int, int]] = []
    y_top = total_d // 2
    for row, depth in zip(rows, depths):
        x = -(total_w // 2)
        for size in row:
            out.append((x // 16 * 16, (y_top - size) // 16 * 16))
            x += size
        y_top -= depth
    return out


def _box(doc: MapDocument, mins, maxs, material: str = PLATFORM, color=PLATFORM_COLOR) -> Solid:
    faces = primitives.block(mins, maxs, material)[0]
    return Solid(id=doc.new_id(), faces=faces, editor=EditorInfo(color=color))


def _zone(doc: MapDocument, template: str, platform: Solid, **values) -> list[MapObject]:
    box = platform.bbox()
    assert box is not None
    fit, at = fit_on(box)
    objs, _gen = build_block(doc, template, {**fit, "hoehe": 128, **values}, at)
    objs[0] = objs[0].replace(extra={**objs[0].extra, SITS_ON: link(platform.id, box)})
    return objs


def plan_room_map(s: RoomMapSettings) -> tuple[list[PlanItem], str]:
    """Grundriss (Räume, Plattformen) und, falls es so nicht geht, warum (sonst "")."""
    plan: list[PlanItem] = []
    try:
        new_room_map(MapDocument(), s, plan, _plan_only=True)
    except ValueError as exc:
        return plan, str(exc)
    return plan, ""


def new_room_map(doc: MapDocument, s: RoomMapSettings, plan: list[PlanItem] | None = None,
                 _plan_only: bool = False) -> list[MapObject]:
    courses = s.courses()
    if not courses or courses[0][0] != "stage":
        raise ValueError(tr("Mindestens eine Stage"))
    sizes = [spec.size for _kind, _n, spec in courses]
    corners = room_grid(sizes)
    xs = [x for x, _y in corners] + [x + size for (x, _y), size in zip(corners, sizes)]
    ys = [y for _x, y in corners] + [y + size for (_x, y), size in zip(corners, sizes)]
    top = max(room_height(size) for size in sizes)
    extent = max(max(xs) - min(xs), max(ys) - min(ys))
    if extent + 256 > 2 * MAP_LIMIT:
        raise ValueError(tr("Die Map wäre mit Hülle etwa {0} Units breit; Source erlaubt höchstens {1}. "
                            "Weniger oder kleinere Räume wählen.").format(extent + 256, 2 * MAP_LIMIT))
    stage_count = sum(1 for kind, _n, _spec in courses if kind == "stage")
    half = PLATFORM_SIZE // 2
    objs: list[MapObject] = []

    def note(kind: str, rect, label: str = "", track: int = 0) -> None:
        if plan is not None:
            plan.append(PlanItem(kind, rect, label, track))

    def platform(x: int, y: int, z: int) -> Solid:
        solid = _box(doc, (x, y - half, z - 32), (x + PLATFORM_SIZE, y + half, z))
        objs.append(solid)
        objs.append(cubemap(doc, (x + half, y, z + 128)))
        return solid

    for (kind, number, spec), (x0, y0) in zip(courses, corners):
        size = spec.size
        height = room_height(size)
        track = 0 if kind == "stage" else number
        if kind == "stage":
            label = spec.name or (tr("Strecke") if s.linear else tr("Stage {0}").format(number))
            dest = f"stage_{number}"
        else:
            label = spec.name or tr("Bonus {0}").format(number)
            dest = f"bonus_{number}"
        note("room", (x0, y0, x0 + size, y0 + size), label, track)
        cy = y0 + size // 2
        # Start im Westen oben, Ziel im Osten tiefer: dazwischen ist alles frei zum Malen
        sx, sz = x0 + 512, height - 512
        ex, ez = x0 + size - 256 - PLATFORM_SIZE, max(768, height // 3)
        start = platform(sx, cy, sz)
        if kind == "stage" and number == 1:
            objs.extend(_zone(doc, "zone_start", start, name=spec.name))
            objs.extend(spawn_entities(doc, s.game, (sx + half, cy), sz + 8, size=PLATFORM_SIZE))
            note("start", (sx, cy - half, sx + PLATFORM_SIZE, cy + half), tr("Start"), track)
        elif kind == "stage":
            objs.extend(_zone(doc, "zone_stage", start, nummer=number, name=spec.name))
            note("stage", (sx, cy - half, sx + PLATFORM_SIZE, cy + half), tr("Start"), track)
        else:
            objs.extend(_zone(doc, "zone_start", start, bonus=number, name=spec.name))
            note("start", (sx, cy - half, sx + PLATFORM_SIZE, cy + half), tr("Start"), track)
        objs.append(Entity(id=doc.new_id(), classname="info_teleport_destination", keyvalues=(
            ("targetname", dest), ("origin", f"{sx + 128} {cy} {sz + 8}"), ("angles", "0 0 0"))))

        end = platform(ex, cy, ez)
        end_rect = (ex, cy - half, ex + PLATFORM_SIZE, cy + half)
        if kind == "stage" and number < stage_count:
            tele, _gen = build_block(doc, "teleporter", {
                "laenge": PLATFORM_SIZE, "breite": PLATFORM_SIZE, "hoehe": 128, "ziel": f"stage_{number + 1}"},
                Placement(ex, cy, ez, 0))
            objs.extend(tele)
            note("teleport", end_rect, "→ " + tr("Stage {0}").format(number + 1), track)
        else:
            objs.extend(_zone(doc, "zone_ende", end, **({"bonus": number} if kind == "bonus" else {})))
            note("end", end_rect, tr("Ziel") if kind == "stage" else tr("Bonus-Ziel"), track)

        # Fall-Teleporter über den ganzen Boden: wer fällt, startet den Raum neu
        trig, _gen = build_block(doc, "teleporter", {
            "laenge": size - 2 * WALL, "breite": size - 2 * WALL, "hoehe": 64, "ziel": dest},
            Placement(x0 + WALL, cy, 0, 0))
        objs.extend(trig)
        # Unsichtbare Wände (Skybox): jeder Raum für sich, man sieht trotzdem den Himmel
        x1, y1 = x0 + size, y0 + size
        for mins, maxs in (((x0, y0, 0), (x0 + WALL, y1, top)), ((x1 - WALL, y0, 0), (x1, y1, top)),
                           ((x0 + WALL, y0, 0), (x1 - WALL, y0 + WALL, top)),
                           ((x0 + WALL, y1 - WALL, 0), (x1 - WALL, y1, top))):
            objs.append(_box(doc, mins, maxs, SKY, WALL_COLOR))

    # Boden unter allem
    objs.append(_box(doc, (min(xs), min(ys), -32), (max(xs), max(ys), 0)))
    objs.append(Entity(id=doc.new_id(), classname="light_environment", keyvalues=(
        ("origin", f"0 0 {top - 128}"), ("_light", "255 240 220 300"), ("_ambient", "150 170 200 40"),
        ("angles", "-50 45 0"), ("pitch", "-50"), ("SunSpreadAngle", "5"))))
    if _plan_only:
        return objs
    bounds = BBox.union(object_bbox(o) for o in objs)
    assert bounds is not None
    objs += enclose_map(doc, margin=16, bounds=bounds)
    return objs


__all__ = ["LINEAR_ROOMS", "STAGE_ROOMS", "RoomMapSettings", "RoomSpec", "new_room_map", "plan_room_map",
           "room_grid", "room_height"]
