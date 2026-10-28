"""Probleme suchen (Alt+P), wie „Check for Problems“ in Hammer, plus Surf-Prüfungen.

Jedes Problem nennt die betroffenen Objekte (zum Hinspringen) und, wo es eine sichere
Reparatur gibt, eine Funktion, die das passende Command baut. Die Funktion bekommt das
Dokument zum Zeitpunkt der Reparatur, damit sie auch nach anderen Änderungen stimmt.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterable

from ...i18n import N_, tr
from ..blocks import MEMBER_KEY, is_block_root
from ..commands import Command, MacroCommand, RemoveObjects, ReplaceObjects
from ..decals import is_auto_overlay, overlay_sides
from ..geometry.displacement import is_displacement_solid
from ..geometry.vertex_edit import VertexError, off_grid, snap_to_grid
from ..materials.apply import replace_material
from ..model import DEFAULT_MATERIAL, Entity, MapDocument, Solid, owner_id
from ..models.props import MODEL_CLASSES, best_class, change_class, class_problem, entity_model
from ..zones import collect_zones, zone_problems

if TYPE_CHECKING:
    from ..entities.fgd import EntityCatalog
    from ..materials import MaterialLibrary
    from ..models.library import ModelLibrary
    from .seal import SealResult

#: Stufen (deutsche Schlüssel, übersetzt erst beim Anzeigen)
ERROR, WARNING, INFO = N_("Fehler"), N_("Warnung"), N_("Hinweis")

#: Source-Maps reichen von -16384 bis 16384 (CS:S)
MAP_LIMIT = 16384
#: Grenzen von vbsp (Source 2007/2013) und der Engine zur Laufzeit
MAX_BRUSHES = 8192
MAX_BRUSH_SIDES = 65536
MAX_SIDES_PER_BRUSH = 128
MAX_EDICTS = 2048
#: Steiler als das rutscht man; flacher kann man stehen (Bodennormale z ≥ 0,7)
SURF_MIN_DEGREES = math.degrees(math.acos(0.7))
#: Flächen zwischen diesem Winkel und SURF_MIN_DEGREES sehen nach Rampe aus, tragen aber
FLAT_RAMP_FROM = 38.0
FLAT_RAMP_MIN_AREA = 64 * 64
#: Spieler-Hülle (stehend) für steckende Spawns
PLAYER_HULL = ((-16.0, -16.0, 0.0), (16.0, 16.0, 72.0))
SPAWN_CLASSES = ("info_player_terrorist", "info_player_counterterrorist", "info_player_start")
#: Ziele, die keine benannte Entity sein müssen
SPECIAL_TARGETS = ("!self", "!activator", "!caller", "!player", "!pvsplayer", "!speechtarget", "!picker")
#: Klassen, deren Brushes nicht kollidieren
NON_SOLID_CLASSES = ("func_illusionary", "func_areaportal", "func_occluder", "func_buyzone", "func_bomb_target",
                     "func_hostage_rescue", "func_precipitation", "func_dustmotes", "func_dustcloud", "func_smokevolume")
NON_SOLID_MATERIALS = ("TOOLS/TOOLSTRIGGER", "TOOLS/TOOLSSKIP", "TOOLS/TOOLSHINT", "TOOLS/TOOLSAREAPORTAL",
                       "TOOLS/TOOLSOCCLUDER", "TOOLS/TOOLSFOG", "TOOLS/TOOLSDOTTED", "TOOLS/TOOLSORIGIN")

Fix = Callable[[MapDocument], "Command | None"]


@dataclass
class Problem:
    level: str
    area: str
    text: str
    ids: tuple[int, ...] = ()
    position: tuple[float, float, float] | None = None
    fix: Fix | None = None
    fix_label: str = ""
    extra: dict = field(default_factory=dict)


# ---- Hilfen -------------------------------------------------------------------------------

def _remove(ids: Iterable[int], text: str) -> Fix:
    ids = tuple(ids)
    return lambda doc: RemoveObjects([i for i in ids if i in doc], text) if any(i in doc for i in ids) else None


def _collides(doc: MapDocument, s: Solid) -> bool:
    if s.parent_id is not None:
        owner = doc.get(s.parent_id)
        if isinstance(owner, Entity):
            cls = owner.classname.lower()
            if cls.startswith("trigger_") or cls in NON_SOLID_CLASSES:
                return False
    return not all(f.material.upper() in NON_SOLID_MATERIALS for f in s.faces)


def _objects(n: int) -> str:
    return "1 Objekt" if n == 1 else f"{n} Objekte"


def _deg(a: float) -> str:
    return f"{a:.1f}°".replace(".", ",")


def _slope(normal) -> float:
    return math.degrees(math.acos(max(-1.0, min(1.0, normal[2]))))


def _area(poly) -> float:
    if not poly or len(poly) < 3:
        return 0.0
    ax = ay = az = 0.0
    o = poly[0]
    for a, b in zip(poly[1:], poly[2:]):
        u = (a[0] - o[0], a[1] - o[1], a[2] - o[2])
        v = (b[0] - o[0], b[1] - o[1], b[2] - o[2])
        ax += u[1] * v[2] - u[2] * v[1]
        ay += u[2] * v[0] - u[0] * v[2]
        az += u[0] * v[1] - u[1] * v[0]
    return 0.5 * math.sqrt(ax * ax + ay * ay + az * az)


def _box_in_brush(mins, maxs, s: Solid) -> bool:
    """Steckt die Box (um 1 Unit verkleinert) in dem konvexen Brush? Trennachsen der Brush-Ebenen."""
    bb = s.bbox()
    if bb is None:
        return False
    lo = [m + 1 for m in mins]
    hi = [m - 1 for m in maxs]
    if any(lo[i] >= bb.maxs[i] or hi[i] <= bb.mins[i] for i in range(3)):
        return False
    corners = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    for f in s.faces:
        pl = f.plane
        n, d = pl.normal, pl.dist
        if all(n[0] * c[0] + n[1] * c[1] + n[2] * c[2] - d > 0 for c in corners):
            return False
    return True


# ---- Prüfungen --------------------------------------------------------------------------

def _brushes(doc: MapDocument) -> list[Problem]:
    out: list[Problem] = []
    invalid = [s.id for s in doc.solids() if not s.is_valid()]
    if invalid:
        out.append(Problem(ERROR, tr("Brushes"), tr('{0} kaputte Brushes (leer, flach oder nicht konvex). vbsp würde sie verwerfen oder abbrechen').format(len(invalid)), tuple(invalid),
                           fix=_remove(invalid, tr("Kaputte Brushes löschen")), fix_label=tr("Löschen")))
    many = [s.id for s in doc.solids() if len(s.faces) > MAX_SIDES_PER_BRUSH]
    if many:
        out.append(Problem(ERROR, tr("Brushes"), tr('{0} Brushes mit mehr als {1} Seiten (vbsp-Grenze)').format(len(many), MAX_SIDES_PER_BRUSH), tuple(many)))
    seen: dict[tuple, int] = {}
    dupes: list[int] = []
    for s in sorted(doc.solids(), key=lambda s: s.id):
        if MEMBER_KEY in s.extra or is_displacement_solid(s):
            continue
        key = (s.parent_id, tuple(sorted((tuple(round(c, 3) for c in f.plane.normal), round(f.plane.dist, 3))
                                         for f in s.faces)))
        if key in seen:
            dupes.append(s.id)
        else:
            seen[key] = s.id
    if dupes:
        out.append(Problem(WARNING, tr("Brushes"), tr('{0} doppelte Brushes (liegen genau aufeinander, flimmern im Spiel)').format(len(dupes)), tuple(dupes),
                           fix=_remove(dupes, tr("Doppelte Brushes löschen")), fix_label=tr("Doppelte löschen")))
    return out


def _ramps(doc: MapDocument) -> list[Problem]:
    out: list[Problem] = []
    flat: list[int] = []
    flat_angles: list[float] = []
    bug: list[int] = []
    for s in doc.solids():
        if is_displacement_solid(s) or not _collides(doc, s):
            continue
        steep = False
        for f, poly in zip(s.faces, s.polygons()):
            a = _slope(f.plane.normal)
            if FLAT_RAMP_FROM <= a < SURF_MIN_DEGREES - 0.01 and _area(poly) >= FLAT_RAMP_MIN_AREA:
                flat.append(s.id)
                flat_angles.append(a)
                break
            if SURF_MIN_DEGREES <= a < 89.0:
                steep = True
        if steep and MEMBER_KEY not in s.extra and off_grid(s):
            bug.append(s.id)
    if flat:
        lo, hi = min(flat_angles), max(flat_angles)
        span = _deg(lo) if hi - lo < 0.05 else f"{_deg(lo)} bis {_deg(hi)}"
        out.append(Problem(WARNING, tr("Rampen"), tr('{0} Rampen zu flach zum Surfen ({1}). Ab {2} rutscht man, flacher bleibt man stehen').format(len(flat), span, _deg(SURF_MIN_DEGREES)), tuple(flat)))
    if bug:
        def fix(doc: MapDocument, ids=tuple(bug)) -> Command | None:
            new = []
            for i in ids:
                s = doc.get(i)
                if isinstance(s, Solid):
                    try:
                        new.append(snap_to_grid(s))
                    except VertexError:
                        continue
            return ReplaceObjects(new, tr("Ecken aufs Raster")) if new else None
        out.append(Problem(WARNING, tr("Rampen"), tr('{0} Rampen-Brushes mit Ecken zwischen ganzen Units: Rampbug-Gefahr').format(len(bug)), tuple(bug), fix=fix, fix_label=tr("Ecken aufs Raster")))
    return out


def _materials(doc: MapDocument, materials: "MaterialLibrary | None") -> list[Problem]:
    if materials is None:
        return []
    users: dict[str, dict[int, None]] = {}
    for s in doc.solids():
        owner = s.extra.get(MEMBER_KEY, s.id)
        for f in s.faces:
            users.setdefault(f.material.upper(), {})[owner] = None
    out = []
    for name in sorted(users):
        if not materials.exists(name):
            ids = tuple(users[name])
            out.append(Problem(WARNING, tr("Texturen"), tr('Textur fehlt im Spiel: {0} ({1}, im Spiel lila-schwarz)').format(name.lower(), _objects(len(ids))), ids,
                               fix=lambda doc, n=name: replace_material(doc, n, DEFAULT_MATERIAL),
                               fix_label=tr("Durch Standard ersetzen")))
    return out


def _models(doc: MapDocument, models: "ModelLibrary | None") -> list[Problem]:
    if models is None:
        return []
    missing: dict[str, list[int]] = {}
    wrong: list[Problem] = []
    for ent in doc.entities():
        if ent.classname.lower() not in MODEL_CLASSES or not ent.get("model", "").lower().endswith(".mdl"):
            continue
        name = entity_model(ent)
        model = models.load(name)
        if model is None:
            missing.setdefault(name, []).append(ent.id)
            continue
        problem = class_problem(ent.classname, model)
        if problem:
            new_cls = best_class(model)

            def fix(doc: MapDocument, eid=ent.id, cls=new_cls) -> Command | None:
                e = doc.get(eid)
                return ReplaceObjects([change_class(e, cls)], tr("Prop-Klasse ändern")) if isinstance(e, Entity) else None
            wrong.append(Problem(WARNING, tr("Modelle"), f"{ent.classname} {name}: {problem}", (ent.id,), ent.origin,
                                 fix=fix, fix_label=f"Zu {new_cls}"))
    out = [Problem(WARNING, tr("Modelle"), tr('Modell fehlt im Spiel: {0} ({1}×)').format(name, len(ids)), tuple(ids),
                   fix=_remove(ids, tr("Props ohne Modell löschen")), fix_label=tr("Löschen"))
           for name, ids in sorted(missing.items())]
    return out + wrong


def _entities(doc: MapDocument, catalog: "EntityCatalog | None") -> list[Problem]:
    out: list[Problem] = []
    names: dict[str, list[int]] = {}
    for e in doc.entities():
        tn = e.get("targetname", "").lower()
        if tn:
            names.setdefault(tn, []).append(e.id)

    def exists(target: str) -> bool:
        t = target.lower()
        if not t or t in SPECIAL_TARGETS:
            return True
        if t.endswith("*"):
            return any(n.startswith(t[:-1]) for n in names)
        return t in names or any(e.classname.lower() == t for e in doc.entities())

    empty: list[int] = []
    for e in doc.entities():
        cls = e.classname.lower()
        kids = doc.children(e.id)
        brush_class = cls.startswith("trigger_") or (
            catalog is not None and (c := catalog.get(cls)) is not None and c.kind == "solid")
        if brush_class and not kids and not is_block_root(e):
            empty.append(e.id)
        if cls == "trigger_teleport":
            target = e.get("target", "")
            if not target:
                out.append(Problem(ERROR, tr("Teleporter"), tr("Teleporter ohne Ziel: Spieler werden nicht teleportiert"),
                                   (e.id,)))
            elif target.lower() not in names:
                out.append(Problem(ERROR, tr("Teleporter"), tr('Teleporter-Ziel „{0}“ gibt es nicht').format(target), (e.id,)))
            if e.get("spawnflags", "0") in ("", "0"):
                def fix(doc: MapDocument, eid=e.id) -> Command | None:
                    ent = doc.get(eid)
                    if not isinstance(ent, Entity):
                        return None
                    kvs = tuple((k, v) for k, v in ent.keyvalues if k.lower() != "spawnflags") + (("spawnflags", "1"),)
                    return ReplaceObjects([ent.replace(keyvalues=kvs)], tr("Teleporter: Spieler auslösen"))
                out.append(Problem(WARNING, tr("Teleporter"), tr("Teleporter reagiert auf niemanden (Flag „Clients“ fehlt)"),
                                   (e.id,), fix=fix, fix_label="Flag setzen"))
        for o in e.outputs:
            if not exists(o.target):
                out.append(Problem(WARNING, tr("Entities"), tr('{0}: Ausgang {1} zielt auf „{2}“, das es nicht gibt').format(e.classname, o.output, o.target), (e.id,)))
    floating = [e.id for e in doc.entities() if is_auto_overlay(e) and not overlay_sides(doc, e)]
    if floating:
        out.append(Problem(WARNING, tr("Aufkleber"), tr('Overlays ohne Fläche darunter: {0}. Im Spiel unsichtbar, auf eine Fläche schieben oder löschen').format(
            len(floating)), tuple(floating),
                           fix=_remove(floating, tr("Overlays ohne Fläche löschen")), fix_label=tr("Löschen")))
    if empty:
        out.append(Problem(WARNING, tr("Entities"), tr('{0} Brush-Entities ohne Brushes').format(len(empty)), tuple(empty),
                           fix=_remove(empty, tr("Leere Brush-Entities löschen")), fix_label=tr("Löschen")))
    return out


def _spawns(doc: MapDocument) -> list[Problem]:
    spawns = [e for e in doc.entities() if e.classname.lower() in SPAWN_CLASSES]
    out: list[Problem] = []
    if not spawns:
        return [Problem(ERROR, tr("Spawns"), tr("Kein Spawn: CS:S braucht info_player_terrorist oder "
                        "info_player_counterterrorist, Momentum info_player_start"))]
    t = sum(e.classname.lower() == "info_player_terrorist" for e in spawns)
    ct = sum(e.classname.lower() == "info_player_counterterrorist" for e in spawns)
    if (t == 0) != (ct == 0):
        team = "Terroristen" if t == 0 else "Counter-Terroristen"
        out.append(Problem(INFO, tr("Spawns"), tr('CS:S: keine Spawns für {0}, wer dieses Team wählt, spawnt nicht').format(team)))
    elif t == 0 and ct == 0:
        out.append(Problem(WARNING, tr("Spawns"), tr("Nur info_player_start: CS:S-Server brauchen T- oder CT-Spawns")))
    solids = [s for s in doc.solids() if not is_displacement_solid(s) and _collides(doc, s)]
    for e in spawns:
        o = e.origin
        if o is None:
            continue
        mins = tuple(o[i] + PLAYER_HULL[0][i] for i in range(3))
        maxs = tuple(o[i] + PLAYER_HULL[1][i] for i in range(3))
        hit = next((s for s in solids if _box_in_brush(mins, maxs, s)), None)
        if hit is not None:
            out.append(Problem(ERROR, tr("Spawns"), tr('{0} steckt in Brush {1}: Spieler hängen fest').format(e.classname, hit.id),
                               (e.id, hit.id), o))
    return out


def _zones(doc: MapDocument) -> list[Problem]:
    zones = collect_zones(doc)
    out = []
    for text in zone_problems(zones):
        z = next((z for z in zones if text.startswith(f"{z.label} liegt")), None)
        out.append(Problem(WARNING, tr("Zonen"), text, (z.entity_id,) if z else ()))
    return out


def _limits(doc: MapDocument) -> list[Problem]:
    out: list[Problem] = []
    outside = []
    for o in doc.objects():
        if isinstance(o, Solid) and owner_id(o) is not None:
            continue  # zählt mit seiner Entity bzw. seinem Baustein
        bb = doc.bbox([o.id])
        if bb is not None and any(abs(c) > MAP_LIMIT for c in (*bb.mins, *bb.maxs)):
            outside.append(o.id)
    if outside:
        out.append(Problem(ERROR, tr("Grenzen"), tr('{0} Objekte außerhalb der Map-Grenze (±{1})').format(len(outside), MAP_LIMIT),
                           tuple(outside)))
    brushes = sum(1 for _ in doc.solids())
    sides = sum(len(s.faces) for s in doc.solids())
    ents = sum(1 for e in doc.entities() if e.classname.lower() not in ("prop_static", "info_overlay", "light",
                                                                         "light_spot", "info_node"))
    for count, limit, what in ((brushes, MAX_BRUSHES, tr("Brushes")), (sides, MAX_BRUSH_SIDES, tr("Brush-Seiten")),
                               (ents, MAX_EDICTS, tr("Entities im Spiel"))):
        if count > limit:
            out.append(Problem(ERROR, tr("Grenzen"), tr('{0} {1}, erlaubt sind {2}').format(count, what, limit)))
        elif count > limit * 0.85:
            out.append(Problem(WARNING, tr("Grenzen"), tr('{0} {1}, nah an der Grenze von {2}').format(count, what, limit)))
    return out


def _seal(doc: MapDocument, seal: "SealResult | None") -> list[Problem]:
    if seal is None or seal.sealed or seal.unknown:
        return []
    from .seal import describe
    return [Problem(ERROR, tr("Dichtheit"), tr("{0}. Tipp: Testen → Map mit Skybox umhüllen").format(describe(doc, seal)),
                    tuple(i for i in (seal.entity_id,) if i is not None),
                    seal.path[0] if seal.path else None, extra={"leak": list(seal.path)})]


def find_problems(doc: MapDocument, materials: "MaterialLibrary | None" = None,
                  models: "ModelLibrary | None" = None, catalog: "EntityCatalog | None" = None,
                  seal: "SealResult | None" = None) -> list[Problem]:
    """Alle Prüfungen; Fehler zuerst."""
    found = (_seal(doc, seal) + _spawns(doc) + _entities(doc, catalog) + _brushes(doc) + _ramps(doc)
             + _limits(doc) + _zones(doc) + _materials(doc, materials) + _models(doc, models))
    order = {ERROR: 0, WARNING: 1, INFO: 2}
    return sorted(found, key=lambda p: order[p.level])


def fix_all(doc: MapDocument, problems: Iterable[Problem]) -> Command | None:
    """Alle reparierbaren Probleme in einem Undo-Schritt (Reparaturen bauen nacheinander auf)."""
    from ..commands import Deferred

    fixes = [p.fix for p in problems if p.fix is not None]
    if not fixes:
        return None
    steps = [lambda d, f=f: f(d) or MacroCommand([], "") for f in fixes]
    return Deferred(steps, "Probleme reparieren")


__all__ = ["ERROR", "INFO", "MAP_LIMIT", "Problem", "SURF_MIN_DEGREES", "WARNING", "find_problems", "fix_all"]
