"""Szenen-Ordner: jedes Objekt der Map landet in genau einem Ordner (Rampen, Welt, Trigger …).

Grundlage für den Szenen-Baum links, in dem man ganze Ordner ein- und ausblendet. Die
Einteilung wird aus den Objekten selbst abgeleitet und nicht gespeichert, sie passt also
auch für geöffnete BSPs und importierte VMFs.
"""
from __future__ import annotations

from dataclasses import dataclass

from .blocks import is_block_root, is_clip_member
from .model import Entity, MapDocument, MapObject, Solid
from .surf.catalog import CATALOG


@dataclass(frozen=True)
class Folder:
    key: str
    label: str
    icon: str


FOLDERS: tuple[Folder, ...] = (
    Folder("rampen", "Rampen", "ramp"),
    Folder("welt", "Welt", "shape"),
    Folder("trigger", "Trigger", "flag"),
    Folder("spawns", "Spawns", "entity"),
    Folder("teleport", "Teleport-Ziele", "entity"),
    Folder("lichter", "Lichter", "sun"),
    Folder("props", "Props", "prefab"),
    Folder("brush_entities", "Brush-Entities", "shape_block"),
    Folder("sonstiges", "Sonstiges", "entity"),
)

#: Was ein einzelnes Objekt eines Ordners ist (für die Anzeige der Auswahl)
SINGULAR = {
    "rampen": "Rampe", "welt": "Brush", "trigger": "Trigger", "spawns": "Spawn", "teleport": "Teleport-Ziel",
    "lichter": "Licht", "props": "Prop", "brush_entities": "Brush-Entity", "sonstiges": "Entity",
}
LIGHTS = {"light", "light_spot", "light_environment", "light_dynamic", "point_spotlight", "env_projectedtexture"}
#: Surf-Fläche: steiler als 44° (Normale z ≤ 0,72), aber nicht senkrecht
RAMP_NZ = (0.1, 0.72)


def is_ramp_solid(solid: Solid) -> bool:
    for face in solid.faces:
        if face.material.upper().startswith("TOOLS/"):
            continue
        nz = face.plane.normal[2]
        if RAMP_NZ[0] < nz <= RAMP_NZ[1]:
            return True
    return False


def entity_folder(ent: Entity, has_brushes: bool) -> str:
    c = ent.classname.lower()
    # Zonen und Kill-Zonen sind Bausteine, gehören aber zu den Triggern
    if c.startswith("trigger_"):
        return "trigger"
    if is_block_root(ent):
        return "rampen"
    if c.startswith("info_player_"):
        return "spawns"
    if c == "info_teleport_destination":
        return "teleport"
    if c in LIGHTS:
        return "lichter"
    if c.startswith("prop_"):
        return "props"
    if has_brushes:
        return "brush_entities"
    return "sonstiges"


def _plain_detail(obj: MapObject | None) -> bool:
    return isinstance(obj, Entity) and obj.classname.lower() == "func_detail" and not is_block_root(obj)


class SceneIndex:
    """Ordner-Einteilung mit Zwischenspeicher je Objekt (Objekte sind unveränderlich)."""

    def __init__(self) -> None:
        self._cache: dict[int, tuple[MapObject, str | None]] = {}

    def folders(self, doc: MapDocument) -> dict[str, list[int]]:
        """Ordner -> Objekt-IDs der Einträge. Brushes einer Brush-Entity stehen nicht einzeln
        drin (sie gehören zu ihrer Entity), außer bei einfachen func_detail: deren Brushes
        werden wie Welt-Brushes eingeteilt, damit Detail-Rampen bei den Rampen landen."""
        with_brushes = {s.parent_id for s in doc.solids() if s.parent_id is not None}
        out: dict[str, list[int]] = {f.key: [] for f in FOLDERS}
        seen: set[int] = set()
        for obj in doc.objects():
            seen.add(obj.id)
            hit = self._cache.get(obj.id)
            if hit is not None and hit[0] is obj:
                key = hit[1]
            else:
                key = self._folder(doc, obj, obj.id in with_brushes)
                self._cache[obj.id] = (obj, key)
            if key is not None:
                out[key].append(obj.id)
        for gone in set(self._cache) - seen:
            del self._cache[gone]
        return out

    @staticmethod
    def _folder(doc: MapDocument, obj: MapObject, has_brushes: bool) -> str | None:
        if isinstance(obj, Entity):
            if _plain_detail(obj):
                return None
            return entity_folder(obj, has_brushes)
        if is_clip_member(obj):
            return None
        if obj.parent_id is not None and not _plain_detail(doc.get(obj.parent_id)):
            return None
        return "rampen" if is_ramp_solid(obj) else "welt"


def kind_of(doc: MapDocument, obj: MapObject) -> str:
    """Art eines Objekts in Worten (Rampe, Brush, Licht …), wie der Szenen-Ordner es einteilt."""
    if isinstance(obj, Entity):
        if _plain_detail(obj):
            return "Detail-Gruppe"
        key = entity_folder(obj, bool(doc.children(obj.id)))
    else:
        parent = doc.get(obj.parent_id) if obj.parent_id is not None else None
        if isinstance(parent, Entity) and not _plain_detail(parent) and not is_block_root(parent):
            return f"Brush von {parent.classname}"
        key = "rampen" if is_ramp_solid(obj) else "welt"
    return SINGULAR[key]


def members(doc: MapDocument, ids: list[int]) -> list[int]:
    """Einträge plus alles, was an ihnen hängt (Brushes von Entities, Clip-Hüllen)."""
    return list(ids) + [s.id for s in doc.attached(ids)]


def label(obj: MapObject) -> str:
    if isinstance(obj, Entity):
        name = obj.get("targetname")
        info = obj.extra.get("block")
        if isinstance(info, dict):
            template = CATALOG.get(str(info.get("template")))
            return f"{template.name if template else info.get('template', 'Baustein')} #{obj.id}"
        if obj.classname.lower() in LIGHTS and not name:
            # Ohne Namen sehen alle Lichter gleich aus: Farbe und Helligkeit unterscheiden sie
            light = obj.get("_light").split()
            if len(light) >= 3:
                rgb = " ".join(light[:3])
                return f"{obj.classname} · {rgb}" + (f" · {light[3]}" if len(light) > 3 else "")
            return obj.classname
        if obj.classname == "prop_static" or obj.classname.startswith("prop_"):
            model = obj.get("model").rsplit("/", 1)[-1]
            return f"{obj.classname} · {model}" if model else obj.classname
        return f"{obj.classname} · {name}" if name else obj.classname
    main = max((f.material for f in obj.faces), key=lambda m: not m.upper().startswith("TOOLS/"), default="")
    return f"Brush {obj.id} · {main.rsplit('/', 1)[-1].lower()}"
