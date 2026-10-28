"""Zeitnahme-Zonen: auslesen, prüfen und als Momentum-Zonendatei schreiben.

In der Map sind Zonen trigger_multiple mit Namen nach dem „mod_zone“-Standard:
`mod_zone_start`, `mod_zone_end`, `mod_zone_checkpoint_<n>` (Stage n) und
`mod_zone_bonus_<b>_start` / `_end`. bhoptimer und andere CS:S-Timer hängen sich
automatisch daran, die Map läuft also auf CS:S-Servern ohne Nacharbeit.

Momentum liest Zonen nicht aus der BSP, sondern aus einer JSON-Datei (Format 1, siehe
momentum-mod/website, libs/formats/zone). `momentum_zones` baut sie aus denselben
Triggern: Startzone und Stage-Zonen werden Segmente der Hauptstrecke, jede Bonus-Strecke
bekommt ein Segment mit eigener Ziel-Zone.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

from ..i18n import tr
from .model import Entity, MapDocument

#: Grenzen des Momentum-Formats (libs/formats/zone/src/zone-validator.ts)
MOMENTUM_FORMAT = 1
MOMENTUM_MAX_COORD = 65536
MOMENTUM_MAX_BONUS = 25

_NAME_RE = re.compile(r"^mod_zone_(?:bonus_?(?P<bonus>[1-9])_)?"
                      r"(?:(?P<kind>start|end)|checkpoint_?(?P<number>\d+))$")


@dataclass(frozen=True)
class Zone:
    entity_id: int
    name: str
    kind: str                 # start, end oder stage
    track: int                # 0 = Hauptstrecke, sonst Bonus-Nummer
    number: int               # Stage-Nummer (nur bei stage)
    points: tuple[tuple[float, float], ...]   # Grundriss gegen den Uhrzeigersinn
    bottom: float
    height: float
    yaw: float

    @property
    def center(self) -> tuple[float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    @property
    def label(self) -> str:
        where = f"Bonus {self.track} " if self.track else ""
        if self.kind == "stage":
            return f"{where}Stage {self.number}"
        return where + ("Startzone" if self.kind == "start" else "Zielzone")


def parse_zone_name(name: str) -> tuple[str, int, int] | None:
    """(Art, Strecke, Stage) aus einem mod_zone-Namen, sonst None."""
    m = _NAME_RE.match(name.strip().lower())
    if m is None:
        return None
    track = int(m["bonus"]) if m["bonus"] else 0
    if m["kind"]:
        return m["kind"], track, 0
    return "stage", track, int(m["number"])


def _hull_2d(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Konvexe Hülle gegen den Uhrzeigersinn, ohne Punkte auf Kanten."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 1e-9:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 1e-9:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _yaw_of(ent: Entity) -> float:
    block = ent.extra.get("block")
    if block:
        return float(block["placement"][3])
    angles = ent.get("angles").split()
    return float(angles[1]) if len(angles) == 3 else 0.0


def collect_zones(doc: MapDocument) -> list[Zone]:
    """Alle Zonen-Trigger der Map mit Grundriss und Höhe."""
    out: list[Zone] = []
    for ent in doc.entities():
        if ent.classname != "trigger_multiple":
            continue
        parsed = parse_zone_name(ent.get("targetname"))
        if parsed is None:
            continue
        verts = [v for s in doc.children(ent.id) for v in s.vertices()]
        if not verts:
            continue
        hull = _hull_2d([(round(v[0], 3), round(v[1], 3)) for v in verts])
        if len(hull) < 3:
            continue
        bottom = min(v[2] for v in verts)
        top = max(v[2] for v in verts)
        kind, track, number = parsed
        out.append(Zone(ent.id, ent.get("targetname"), kind, track, number, tuple(hull),
                        bottom, top - bottom, _yaw_of(ent)))
    return out


def zone_problems(zones: list[Zone]) -> list[str]:
    """Hinweise, warum der Timer mit diesen Zonen nicht sauber laufen würde."""
    if not zones:
        return []
    problems: list[str] = []
    tracks = sorted({z.track for z in zones})
    for track in tracks:
        mine = [z for z in zones if z.track == track]
        where = f"Bonus {track}" if track else "Hauptstrecke"
        starts = sum(z.kind == "start" for z in mine)
        ends = sum(z.kind == "end" for z in mine)
        if starts == 0:
            problems.append(f"{where}: Startzone fehlt")
        if ends == 0:
            problems.append(f"{where}: Zielzone fehlt")
        if track and any(z.kind == "stage" for z in mine):
            problems.append(tr('{0}: Stages gibt es nur auf der Hauptstrecke (Momentum)').format(where))
    stages = sorted(z.number for z in zones if z.kind == "stage" and z.track == 0)
    if stages:
        dupes = sorted({n for n in stages if stages.count(n) > 1})
        if dupes:
            problems.append(tr("Stage doppelt vergeben: ") + ", ".join(map(str, dupes)))
        expected = list(range(2, 2 + len(set(stages))))
        if sorted(set(stages)) != expected:
            problems.append(tr("Stages sollten lückenlos ab 2 nummeriert sein (Stage 1 ist die Startzone), "
                            "gefunden: ") + ", ".join(map(str, sorted(set(stages)))))
    bonuses = [t for t in tracks if t]
    if bonuses and bonuses != list(range(1, len(bonuses) + 1)):
        problems.append(tr("Boni sollten lückenlos ab 1 nummeriert sein, gefunden: ") + ", ".join(map(str, bonuses)))
    for z in zones:
        if any(abs(c) > MOMENTUM_MAX_COORD for p in z.points for c in p):
            problems.append(tr('{0} liegt außerhalb der Map').format(z.label))
    return problems


def _region(z: Zone, tele: bool) -> dict:
    region: dict = {
        "points": [[_num(x), _num(y)] for x, y in z.points],
        "bottom": _num(z.bottom),
        "height": _num(z.height),
    }
    if tele:
        cx, cy = z.center
        region["teleDestPos"] = [_num(cx), _num(cy), _num(z.bottom)]
        region["teleDestYaw"] = _num(z.yaw)
    return region


def _num(v: float) -> float | int:
    r = round(v, 3)
    return int(r) if float(r).is_integer() else r


def _segment(start: Zone, name: str | None = None) -> dict:
    seg: dict = {
        "limitStartGroundSpeed": True,
        "checkpointsRequired": True,
        "checkpointsOrdered": True,
        "checkpoints": [{"regions": [_region(start, tele=True)]}],
        "cancel": [],
    }
    if name:
        seg["name"] = name
    return seg


def _first(zones: list[Zone], kind: str, track: int) -> Zone | None:
    return next((z for z in zones if z.kind == kind and z.track == track), None)


def momentum_zones(zones: list[Zone], timestamp_ms: int | None = None) -> dict | None:
    """Momentum-Zonendatei als Dict; None, wenn Start- oder Zielzone der Hauptstrecke fehlt."""
    start, end = _first(zones, "start", 0), _first(zones, "end", 0)
    if start is None or end is None:
        return None
    stages: dict[int, Zone] = {}
    for z in sorted(zones, key=lambda z: z.number):
        if z.kind == "stage" and z.track == 0:
            stages.setdefault(z.number, z)
    segments = [_segment(start)] + [_segment(stages[n]) for n in sorted(stages)]
    bonuses = []
    for track in sorted({z.track for z in zones if z.track})[:MOMENTUM_MAX_BONUS]:
        b_start, b_end = _first(zones, "start", track), _first(zones, "end", track)
        if b_start is None or b_end is None:
            continue
        bonuses.append({"zones": {"segments": [_segment(b_start, f"Bonus {track}")],
                                  "end": {"regions": [_region(b_end, tele=False)]}}})
    return {
        "formatVersion": MOMENTUM_FORMAT,
        "dataTimestamp": timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
        "tracks": {
            "main": {
                "stagesEndAtStageStarts": True,
                "zones": {"segments": segments, "end": {"regions": [_region(end, tele=False)]}},
            },
            "bonuses": bonuses,
        },
    }


__all__ = [
    "Zone",
    "collect_zones",
    "momentum_zones",
    "parse_zone_name",
    "zone_problems",
]
