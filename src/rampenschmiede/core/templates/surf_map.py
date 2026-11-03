"""Assistent „Neue Surf-Map“: eine spielbare lineare Surf-Map aus Stages.

Jede Stage besteht aus einer Startplattform (mit Teleport-Ziel und Zeitnahme-Zone), einigen Rampen in einer
Linie, die nacheinander tiefer liegen, und einem Fall-Teleporter am Boden, der zurück zum
Anfang der Stage bringt. Am Ende steht eine Zielplattform. Um alles kommt eine dichte
Skybox-Hülle, die Map lässt sich also sofort kompilieren und durchspielen.

Die Rampen und Teleporter sind Bausteine und bleiben über ihre Regler änderbar.

Der Easy Mode plant genauer: Jede Stage kann einen Namen, eine eigene Rampenzahl und Rampenart
haben, Bonus-Strecken kommen in eigene Reihen neben die Hauptstrecke. Stages liegen entweder
hintereinander (man surft von Stage zu Stage) oder in Reihen nebeneinander; dann bringt ein
Teleporter am Ende jeder Stage zur nächsten, wie auf den meisten Stage-Maps.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...i18n import tr
from ..attach import SITS_ON, fit_on, link
from ..blocks import build_block
from ..geometry import primitives
from ..mathutil import BBox
from ..model import EditorInfo, Entity, MapDocument, MapObject, Solid, object_bbox
from ..surf.catalog import CATALOG, Placement, ramp_height
from .starter import cubemap, enclose_map, spawn_entities

#: Source-Maps dürfen von -16384 bis 16384 reichen
MAP_LIMIT = 16384
PLATFORM = "DEV/DEV_MEASUREGENERIC01B"
PLATFORM_COLOR = (120, 200, 140)
RAMP_KINDS = ("gerade", "ski", "banane", "welle", "trapez")


#: Anordnung der Stages: hintereinander auf einer Linie oder in Reihen nebeneinander
LAYOUTS = ("linie", "reihen")
#: Platz zwischen zwei Reihen zusätzlich zur Rampenbreite (Fall-Teleporter sind 1024 breiter)
ROW_SPACE = 1280


@dataclass(frozen=True)
class CourseSpec:
    """Eine Stage oder Bonus-Strecke: Name, Anzahl und Art der Rampen (leer = Art der Map)."""

    name: str = ""
    ramps: int = 2
    kind: str = ""


@dataclass(frozen=True)
class PlanItem:
    """Grundriss eines Teils der Map für den Layout-Plan (von oben, x0 < x1, y0 < y1)."""

    kind: str     # platform, ramp, start, stage, end, teleport
    rect: tuple[float, float, float, float]
    label: str = ""
    track: int = 0


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
    #: „linie“ (hintereinander) oder „reihen“ (nebeneinander, Teleporter zur nächsten Stage)
    layout: str = "linie"
    #: Stages einzeln geplant; leer = `stages` gleiche Stages mit `ramps_per_stage` Rampen
    stage_specs: tuple[CourseSpec, ...] = ()
    #: Bonus-Strecken (Bonus 1, 2, …), jede in einer eigenen Reihe
    bonuses: tuple[CourseSpec, ...] = field(default_factory=tuple)

    def stage_list(self) -> list[CourseSpec]:
        if self.stage_specs:
            return list(self.stage_specs)
        return [CourseSpec(ramps=self.ramps_per_stage) for _ in range(self.stages)]

    def kind_of(self, spec: CourseSpec) -> str:
        kind = spec.kind or self.ramp_kind
        return kind if kind in CATALOG else "gerade"

    @property
    def row_pitch(self) -> int:
        return (self.ramp_width + ROW_SPACE + 15) // 16 * 16


def _box(doc: MapDocument, mins, maxs, material: str = PLATFORM) -> Solid:
    faces = primitives.block(mins, maxs, material)[0]
    return Solid(id=doc.new_id(), faces=faces, editor=EditorInfo(color=PLATFORM_COLOR))


def _platform(doc: MapDocument, x: int, y: int, top: int, size: int) -> Solid:
    half = size // 2
    return _box(doc, (x, y - half, top - 32), (x + size, y + half, top))


def _zone(doc: MapDocument, template: str, platform: Solid, **values) -> list[MapObject]:
    """Zone auf einer Plattform; sie folgt ihr, wenn die Plattform verschoben wird."""
    box = platform.bbox()
    assert box is not None
    fit, at = fit_on(box)
    objs, _gen = build_block(doc, template, {**fit, "hoehe": 128, **values}, at)
    objs[0] = objs[0].replace(extra={**objs[0].extra, SITS_ON: link(platform.id, box)})
    return objs


def _ramp_setup(s: SurfMapSettings, kind: str) -> tuple[dict, float, float]:
    """Regler der Rampen, Höhe des Querschnitts und Höhenänderung entlang der Rampe."""
    values: dict = {"laenge": s.ramp_length, "breite": s.ramp_width, "winkel": s.angle}
    if kind == "ski":
        values["gefaelle"] = -s.ramp_length // 4
    full = CATALOG[kind].values(values)
    return values, ramp_height(full), full.get("gefaelle", 0)


def course_length(s: SurfMapSettings, spec: CourseSpec) -> int:
    """Plattform, Lücke und Rampen einer Stage (ohne Ziel- oder Übergangsplattform)."""
    return s.platform + s.gap + spec.ramps * (s.ramp_length + s.gap)


def _rows(s: SurfMapSettings) -> list[list[CourseSpec]]:
    stages = s.stage_list()
    main = [[st] for st in stages] if s.layout == "reihen" else [stages]
    return main + [[b] for b in s.bonuses]


def total_length(s: SurfMapSettings) -> int:
    """Länge der längsten Reihe in Units."""
    # Jede Reihe endet mit einer Plattform: Ziel oder Teleporter zur nächsten Stage
    return max(sum(course_length(s, c) for c in row) + s.platform for row in _rows(s))


def total_width(s: SurfMapSettings) -> int:
    """Breite aller Reihen nebeneinander in Units (Fall-Teleporter mitgerechnet)."""
    return (len(_rows(s)) - 1) * s.row_pitch + s.ramp_width + 1024


def plan_surf_map(s: SurfMapSettings) -> tuple[list[PlanItem], str]:
    """Grundriss der Map und, falls sie so nicht geht, warum (sonst ""). Schnell genug für eine
    Live-Vorschau: Die Rampen selbst werden dafür nicht gebaut."""
    plan: list[PlanItem] = []
    try:
        new_surf_map(MapDocument(), s, plan, _plan_only=True)
    except ValueError as exc:
        return plan, str(exc)
    return plan, ""


def new_surf_map(doc: MapDocument, s: SurfMapSettings, plan: list[PlanItem] | None = None,
                 _plan_only: bool = False) -> list[MapObject]:
    """Alle Objekte der Map. Die Rampen laufen entlang +X, Spieler starten im Westen.
    Die Map wird um den Nullpunkt gelegt. ValueError, wenn sie zu groß für Source wäre.
    `plan` sammelt auf Wunsch den Grundriss (für den Layout-Plan im Easy Mode)."""
    stages = s.stage_list()
    if not stages or any(st.ramps < 1 for st in stages) or any(b.ramps < 1 for b in s.bonuses):
        raise ValueError(tr("Mindestens eine Stage mit einer Rampe"))
    rows_count = len(_rows(s))
    pitch = s.row_pitch
    length = total_length(s)
    heights = [_ramp_setup(s, s.kind_of(c))[1] for c in (*stages, *s.bonuses)]
    x_start = -(length // 2) // 16 * 16
    top0 = int(max(heights)) + 512
    half_w = s.ramp_width // 2

    def row_y(row: int) -> int:
        return (row * pitch - (rows_count - 1) * pitch // 2) // 16 * 16

    def note(kind: str, x0: float, y: float, x1: float, half: float, label: str = "", track: int = 0) -> None:
        if plan is not None:
            plan.append(PlanItem(kind, (x0, y - half, x1, y + half), label, track))

    objs: list[MapObject] = []
    segments: list[tuple[int, int, int, str, int]] = []   # (x_anfang, x_ende, y, Ziel, Strecke) für Fall-Teleporter
    lowest = top0

    def start_platform(x: int, y: int, top: int, zone: str, zone_values: dict, dest: str, label: str,
                       track: int, spawns: bool) -> None:
        platform = _platform(doc, x, y, top, s.platform)
        objs.append(platform)
        objs.extend(_zone(doc, zone, platform, **zone_values))
        objs.append(cubemap(doc, (x + s.platform // 2, y, top + 128)))
        objs.append(Entity(id=doc.new_id(), classname="info_teleport_destination", keyvalues=(
            ("targetname", dest), ("origin", f"{x + 128} {y} {top + 8}"), ("angles", "0 0 0"))))
        if spawns:
            objs.extend(spawn_entities(doc, s.game, (x + s.platform // 2, y), top + 8, size=s.platform))
        note("start" if zone == "zone_start" else "stage", x, y, x + s.platform, s.platform / 2, label, track)

    def ramps(spec: CourseSpec, x: int, y: int, top: int, track: int) -> tuple[int, int]:
        nonlocal lowest
        kind = s.kind_of(spec)
        values, height, drop_along = _ramp_setup(s, kind)
        ramp_top = top - 96
        for _ in range(spec.ramps):
            anchor_z = int(ramp_top - height)
            if not _plan_only:
                ramp, _gen = build_block(doc, kind, values, Placement(x, y, anchor_z, 0))
                objs.extend(ramp)
            note("ramp", x, y, x + s.ramp_length, half_w, kind, track)
            lowest = min(lowest, anchor_z + min(0, drop_along))
            x += s.ramp_length + s.gap
            ramp_top += drop_along - s.drop
        # Nächste Plattform etwa auf halber Höhe der letzten Rampe: erreichbar mit Schwung
        return x, int(ramp_top + s.drop - height / 2)

    def end_platform(x: int, y: int, top: int, zone_values: dict, label: str, track: int) -> None:
        platform = _platform(doc, x, y, top, s.platform)
        objs.append(platform)
        objs.extend(_zone(doc, "zone_ende", platform, **zone_values))
        objs.append(cubemap(doc, (x + s.platform // 2, y, top + 128)))
        note("end", x, y, x + s.platform, s.platform / 2, label, track)

    # Hauptstrecke
    x, y, top = x_start, row_y(0), top0
    for i, spec in enumerate(stages):
        if s.layout == "reihen" and i > 0:
            x, y, top = x_start, row_y(i), top0
        start_x = x
        label = spec.name or tr("Stage {0}").format(i + 1)
        if i == 0:
            start_platform(x, y, top, "zone_start", {"name": spec.name}, "stage_1", label, 0, True)
        else:
            start_platform(x, y, top, "zone_stage", {"nummer": i + 1, "name": spec.name}, f"stage_{i + 1}",
                           label, 0, False)
        x, top = ramps(spec, x + s.platform + s.gap, y, top, 0)
        segments.append((start_x, x, y, f"stage_{i + 1}", 0))
        if s.layout == "reihen" and i < len(stages) - 1:
            # Ende der Stage: Plattform mit Teleporter zur nächsten Stage
            objs.append(_platform(doc, x, y, top, s.platform))
            tele, _gen = build_block(doc, "teleporter", {
                "laenge": s.platform, "breite": s.platform, "hoehe": 128, "ziel": f"stage_{i + 2}"},
                Placement(x, y, top, 0))
            objs.extend(tele)
            note("teleport", x, y, x + s.platform, s.platform / 2, "→ " + tr("Stage {0}").format(i + 2), 0)
            x += s.platform
    end_platform(x, y, top, {}, tr("Ziel"), 0)
    objs.append(Entity(id=doc.new_id(), classname="info_target", keyvalues=(
        ("targetname", "ziel"), ("origin", f"{x + s.platform // 2} {y} {top + 32}"))))
    ends = [x + s.platform]

    # Bonus-Strecken in eigenen Reihen
    first_bonus_row = rows_count - len(s.bonuses)
    for b, spec in enumerate(s.bonuses, start=1):
        x, y, top = x_start, row_y(first_bonus_row + b - 1), top0
        label = spec.name or tr("Bonus {0}").format(b)
        start_platform(x, y, top, "zone_start", {"bonus": b, "name": spec.name}, f"bonus_{b}", label, b, False)
        x, top = ramps(spec, x + s.platform + s.gap, y, top, b)
        segments.append((x_start, x, y, f"bonus_{b}", b))
        end_platform(x, y, top, {"bonus": b}, tr("Bonus-Ziel"), b)
        ends.append(x + s.platform)

    # Fall-Teleporter unter jeder Stage, über die ganze Breite
    floor = lowest - 256
    width = s.ramp_width + 1024
    for x0, x1, yy, dest, _track in segments:
        trig, _gen = build_block(doc, "teleporter", {
            "laenge": x1 - x0, "breite": width, "hoehe": 64, "ziel": dest}, Placement(x0, yy, floor, 0))
        objs.extend(trig)
    # Boden unter allem, damit man nicht ins Leere fällt
    ys = [seg[2] for seg in segments]
    objs.append(_box(doc, (x_start - 256, min(ys) - width // 2 - 256, floor - 32),
                     (max(ends) + 256, max(ys) + width // 2 + 256, floor)))
    objs.append(Entity(id=doc.new_id(), classname="light_environment", keyvalues=(
        ("origin", f"0 0 {top0 + 256}"), ("_light", "255 240 220 300"), ("_ambient", "150 170 200 40"),
        ("angles", "-50 45 0"), ("pitch", "-50"), ("SunSpreadAngle", "5"))))

    bounds = BBox.union(object_bbox(o) for o in objs)
    assert bounds is not None
    if any(abs(c) > MAP_LIMIT - 600 for c in (*bounds.mins, *bounds.maxs)):
        size = round(max(bounds.size)) + 2 * 528
        raise ValueError(
            tr('Die Map wäre mit Hülle etwa {0} Units lang; Source erlaubt höchstens {1}. Weniger Stages, weniger oder kürzere Rampen wählen.').format(size, 2 * MAP_LIMIT))
    if _plan_only:
        return objs
    objs += enclose_map(doc, margin=512, bounds=bounds)
    return objs
