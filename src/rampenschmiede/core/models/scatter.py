"""Props streuen: Modelle zufällig auf Flächen verteilen, und Detail-Kits je Map-Stil.

Ein Kit nennt Namensmuster statt fester Modelle. Welche Modelle es wirklich gibt, entscheidet
die Modell-Bibliothek des Spiels (CS:S bringt die HL2-Modelle mit). So passt ein Kit zu jeder
Installation, und Modelle aus eigenen Ordnern mit passendem Namen kommen dazu.

Gestreut wird senkrecht von oben: Für zufällige Punkte im Kreis wird die oberste Fläche unter
der Pinselmitte gesucht. Zu steile Stellen, Werkzeug-Texturen und Punkte zu nah an anderen
Props werden ausgelassen.
"""
from __future__ import annotations

import fnmatch
import math
import random
from dataclasses import dataclass

import numpy as np

from ...i18n import tr
from ..geometry.brush import ray_intersect_solid
from ..geometry.displacement import is_displacement_solid, solid_ray_face
from ..mathutil import Point
from ..model import Entity, MapDocument, Solid
from .library import ModelLibrary
from .props import entity_model, is_model_entity, new_prop

#: Höchstens so viele Modelle zeigt ein Kit (die ersten nach Namen)
MAX_KIT_MODELS = 40
#: Modelle, die nie in ein Kit gehören (Bruchstücke, LOD-Stufen, Ragdolls)
EXCLUDE = ("*gib*", "*chunk*", "*_lod*", "*damaged*", "*break*", "*ragdoll*", "*_skybox*", "*sky*")


@dataclass(frozen=True)
class DetailKit:
    key: str
    name: str
    description: str
    patterns: tuple[str, ...]
    #: Am Hang ausrichten (Felsen) statt aufrecht stehen (Bäume)
    align: bool = False


KITS: tuple[DetailKit, ...] = (
    DetailKit("wald", tr("Wald und Wiese"), tr("Bäume, Büsche und Farne."),
              ("models/props_foliage/*tree*", "models/props_foliage/*bush*", "models/props_foliage/*shrub*",
               "models/props_foliage/*fern*", "models/props_foliage/*grass*", "models/props/de_inferno/bush*",
               "models/props/pi_fern*")),
    DetailKit("felsen", tr("Felsen und Geröll"), tr("Steine und Felsbrocken, am Hang ausgerichtet."),
              ("models/props_wasteland/rock*", "models/props_foliage/rock*", "models/props/*rock*",
               "models/props_canal/rock*", "models/props_debris/*rock*", "models/props_nature/rock*"),
              align=True),
    DetailKit("wueste", tr("Wüste"), tr("Kakteen, Palmen, Steine und Kisten aus Dust und Aztec."),
              ("models/props/de_inferno/cactus*", "models/props/de_dust/*", "models/props/cs_militia/*rock*",
               "models/props_foliage/*palm*", "models/props/de_aztec/*")),
    DetailKit("industrie", tr("Industrie"), tr("Fässer, Kisten, Paletten und Absperrungen."),
              ("models/props_c17/oildrum*", "models/props_junk/wood_crate*", "models/props_junk/*pallet*",
               "models/props_industrial/*", "models/props_wasteland/barricade*", "models/props/de_nuke/*crate*",
               "models/props/de_train/*barrel*", "models/props_c17/concrete_barrier*")),
    DetailKit("stadt", tr("Stadt"), tr("Laternen, Bänke, Mülltonnen und Hydranten."),
              ("models/props_c17/lamppost*", "models/props_c17/bench*", "models/props_junk/trashbin*",
               "models/props_junk/trashdumpster*", "models/props_c17/fence*", "models/props/cs_office/*plant*",
               "models/props/cs_italy/*")),
)
KITS_BY_KEY = {k.key: k for k in KITS}
#: Passendes Kit je Welt-Stil
STYLE_KITS = {"tag": "wald", "abend": "wald", "nacht": "stadt", "wueste": "wueste", "industrie": "industrie",
              "neon": "stadt", "eis": "felsen", "dschungel": "wald", "retro": "stadt", "weltraum": "industrie",
              "inferno": "industrie", "pastell": "wald"}


def kit_models(kit: DetailKit, names: list[str]) -> list[str]:
    """Modelle aus `names` (alle Modelle des Spiels), die zum Kit passen."""
    out = []
    for name in names:
        low = name.lower()
        if any(fnmatch.fnmatch(low, p) for p in EXCLUDE):
            continue
        if any(fnmatch.fnmatch(low, p) for p in kit.patterns):
            out.append(name)
        if len(out) >= MAX_KIT_MODELS:
            break
    return out


@dataclass
class ScatterSettings:
    radius: float = 256.0
    count: int = 5
    #: Abstand zu anderen Props (Mitte zu Mitte)
    spacing: float = 96.0
    max_slope: float = 35.0
    align: bool = False
    terrain_only: bool = False
    #: So weit sinken die Modelle ein (sonst schweben sie an Hängen)
    sink: float = 2.0


def _is_tool_only(solid: Solid) -> bool:
    return all(f.material.upper().startswith("TOOLS/") for f in solid.faces)


class Ground:
    """Findet die oberste Fläche unter einem Punkt (Brushes und Gelände)."""

    def __init__(self, solids: list[Solid], terrain_only: bool = False) -> None:
        self.solids = [s for s in solids if not _is_tool_only(s)
                       and (not terrain_only or is_displacement_solid(s))]
        self._boxes = [s.bbox() for s in self.solids]

    def height(self, x: float, y: float, top: float, depth: float) -> float | None:
        o = (x, y, top)
        d = (0.0, 0.0, -1.0)
        best = None
        for s, bb in zip(self.solids, self._boxes):
            if bb is None or not (bb.mins[0] <= x <= bb.maxs[0] and bb.mins[1] <= y <= bb.maxs[1]):
                continue
            if bb.maxs[2] < top - depth or bb.mins[2] > top:
                continue
            if is_displacement_solid(s):
                hit = solid_ray_face(s, o, d)
                t = hit[0] if hit is not None else None
            else:
                t = ray_intersect_solid(s, o, d)
            if t is not None and t <= depth and (best is None or t < best):
                best = t
        return None if best is None else top - best

    def normal(self, x: float, y: float, z: float, step: float = 4.0) -> tuple[float, float, float] | None:
        """Flächennormale aus den Höhen ringsum."""
        top, depth = z + 64, 128
        hx1, hx0 = self.height(x + step, y, top, depth), self.height(x - step, y, top, depth)
        hy1, hy0 = self.height(x, y + step, top, depth), self.height(x, y - step, top, depth)
        if None in (hx1, hx0, hy1, hy0):
            return None
        n = np.array([-(hx1 - hx0) / (2 * step), -(hy1 - hy0) / (2 * step), 1.0])  # type: ignore[operator]
        n /= np.linalg.norm(n)
        return float(n[0]), float(n[1]), float(n[2])


def aligned_angles(normal: tuple[float, float, float], yaw: float) -> tuple[float, float, float]:
    """Pitch, Yaw, Roll, damit die Hochachse des Modells entlang `normal` zeigt (Source-Winkel)."""
    yr = math.radians(yaw)
    fwd = np.array([math.cos(yr), math.sin(yr), 0.0])
    up = np.asarray(normal, dtype=np.float64)
    fwd = fwd - up * (fwd @ up)
    fwd /= max(np.linalg.norm(fwd), 1e-9)
    left = np.cross(up, fwd)
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, -fwd[2]))))
    yaw_out = math.degrees(math.atan2(fwd[1], fwd[0]))
    roll = math.degrees(math.atan2(left[2], up[2]))
    return round(pitch, 2), round(yaw_out % 360, 2), round(roll, 2)


def existing_props(doc: MapDocument) -> list[tuple[Entity, Point]]:
    return [(e, e.origin) for e in doc.entities() if is_model_entity(e) and e.origin is not None]


def scatter(doc: MapDocument, ground: Ground, center: Point, models: list[str], library: ModelLibrary | None,
            settings: ScatterSettings, rng: random.Random, taken: list[Point] | None = None) -> list[Entity]:
    """Neue Props im Kreis um `center` (IDs aus dem Dokument). `taken`: schon belegte Punkte,
    wird um die neuen ergänzt."""
    if not models:
        return []
    taken = taken if taken is not None else [p for _, p in existing_props(doc)]
    cos_max = math.cos(math.radians(settings.max_slope))
    out: list[Entity] = []
    cx, cy, cz = center
    top = cz + max(settings.radius, 256.0)
    depth = 2 * max(settings.radius, 256.0)
    for _ in range(settings.count * 6):
        if len(out) >= settings.count:
            break
        r = settings.radius * math.sqrt(rng.random())
        a = rng.uniform(0, 2 * math.pi)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        if any((x - p[0]) ** 2 + (y - p[1]) ** 2 < settings.spacing ** 2 for p in taken):
            continue
        z = ground.height(x, y, top, depth)
        if z is None:
            continue
        n = ground.normal(x, y, z)
        if n is None or n[2] < cos_max:
            continue
        name = rng.choice(models)
        model = library.load(name) if library is not None else None
        yaw = rng.uniform(0, 360)
        ent = new_prop(name, (x, y, z - settings.sink), model, yaw)
        if settings.align:
            p, yw, rl = aligned_angles(n, yaw)
            ent = ent.with_keyvalue("angles", f"{p:g} {yw:g} {rl:g}")
        out.append(ent.replace(id=doc.new_id()))
        taken.append((x, y, z))
    return out


def props_in_circle(doc: MapDocument, center: Point, radius: float, models: list[str] | None = None) -> list[int]:
    """IDs der Props, deren Fuß im Kreis (von oben gesehen) liegt; optional nur diese Modelle."""
    wanted = {m.lower() for m in models} if models else None
    out = []
    for ent, p in existing_props(doc):
        if (p[0] - center[0]) ** 2 + (p[1] - center[1]) ** 2 > radius ** 2:
            continue
        if wanted is not None and entity_model(ent).lower() not in wanted:
            continue
        out.append(ent.id)
    return out


__all__ = ["KITS", "KITS_BY_KEY", "STYLE_KITS", "DetailKit", "Ground", "ScatterSettings", "aligned_angles",
           "kit_models", "props_in_circle", "scatter"]
