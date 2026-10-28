"""Das Dokument: einzige Wahrheit über die Map.

Lesen darf jeder. Schreiben dürfen nur Commands über die Methoden mit Unterstrich
(`_insert`, `_remove`, `_replace`). Nach jedem Command wird ein ChangeSet an alle
Beobachter gemeldet (Renderer, Panels, Prüfung).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator

from ..mathutil import BBox
from .objects import Entity, MapObject, Solid


@dataclass
class ChangeSet:
    added: set[int] = field(default_factory=set)
    modified: set[int] = field(default_factory=set)
    removed: set[int] = field(default_factory=set)
    world_changed: bool = False

    def merge(self, other: "ChangeSet") -> "ChangeSet":
        self.added |= other.added
        self.modified |= other.modified
        self.removed |= other.removed
        self.world_changed |= other.world_changed
        # Hinzugefügt und wieder entfernt heißt: nie da gewesen.
        both = self.added & self.removed
        self.added -= both
        self.removed -= both
        self.modified -= self.removed | self.added
        return self

    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.removed or self.world_changed)


DEFAULT_WORLD_KEYVALUES: tuple[tuple[str, str], ...] = (
    ("classname", "worldspawn"),
    ("skyname", "sky_day01_01"),
    ("maxpropscreenwidth", "-1"),
    ("detailvbsp", "detail.vbsp"),
    ("detailmaterial", "detail/detailsprites"),
)


@dataclass
class EditorState:
    """Editor-Zustand, der mit dem Projekt gespeichert wird."""

    grid_size: int = 16
    camera_position: tuple[float, float, float] = (-512.0, -512.0, 384.0)
    camera_angles: tuple[float, float] = (45.0, -25.0)  # Gier, Nick in Grad
    expert_mode: bool = False


class MapDocument:
    def __init__(self) -> None:
        self.world_keyvalues: tuple[tuple[str, str], ...] = DEFAULT_WORLD_KEYVALUES
        self.editor = EditorState()
        # Unverstandene Daten aus importierten Dateien (z. B. VMF-Blöcke), JSON-fähig
        self.extra: dict = {}
        self._objects: dict[int, MapObject] = {}
        self._next_id = 1
        self._listeners: list[Callable[[ChangeSet], None]] = []

    # ---- IDs -------------------------------------------------------------
    def new_id(self) -> int:
        nid = self._next_id
        self._next_id += 1
        return nid

    def reserve_ids_above(self, used: int) -> None:
        self._next_id = max(self._next_id, used + 1)

    # ---- Lesen -----------------------------------------------------------
    def __len__(self) -> int:
        return len(self._objects)

    def __contains__(self, oid: int) -> bool:
        return oid in self._objects

    def get(self, oid: int) -> MapObject | None:
        return self._objects.get(oid)

    def objects(self) -> Iterator[MapObject]:
        return iter(self._objects.values())

    def solids(self) -> Iterator[Solid]:
        return (o for o in self._objects.values() if isinstance(o, Solid))

    def entities(self) -> Iterator[Entity]:
        return (o for o in self._objects.values() if isinstance(o, Entity))

    def children(self, entity_id: int) -> list[Solid]:
        return [s for s in self.solids() if s.parent_id == entity_id]

    def attached(self, ids: Iterable[int]) -> list[Solid]:
        """Brushes, die zu den genannten Objekten gehören: Brushes einer Brush-Entity und
        die Kollisions-Brushes eines Bausteins (`extra["block_of"]`)."""
        owners = set(ids)
        return [s for s in self.solids() if s.id not in owners and owner_id(s) in owners]

    def world_get(self, key: str, default: str = "") -> str:
        for k, v in self.world_keyvalues:
            if k == key:
                return v
        return default

    def bbox(self, ids: Iterable[int] | None = None) -> BBox | None:
        """Umgebende Box; bei Brush-Entities und Bausteinen samt ihrer Brushes."""
        if ids is None:
            return BBox.union(object_bbox(o) for o in self._objects.values())
        known = [i for i in ids if i in self._objects]
        objs = [self._objects[i] for i in known]
        if any(isinstance(o, Entity) for o in objs):
            objs += self.attached(known)
        return BBox.union(object_bbox(o) for o in objs)

    def snapshot(self) -> "MapDocument":
        """Flache Kopie für Berechnungen in einem anderen Thread. Die Objekte sind
        unveränderlich, also reicht es, das Verzeichnis zu kopieren."""
        snap = MapDocument()
        snap.world_keyvalues = self.world_keyvalues
        snap._objects = dict(self._objects)
        snap._next_id = self._next_id
        return snap

    # ---- Beobachter ------------------------------------------------------
    def subscribe(self, listener: Callable[[ChangeSet], None]) -> None:
        self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[ChangeSet], None]) -> None:
        self._listeners.remove(listener)

    def notify(self, changes: ChangeSet) -> None:
        if changes.is_empty():
            return
        for listener in list(self._listeners):
            listener(changes)

    # ---- Schreiben (nur für Commands und Lader) --------------------------
    def _insert(self, objs: Iterable[MapObject]) -> ChangeSet:
        cs = ChangeSet()
        for o in objs:
            if o.id in self._objects:
                raise ValueError(f"ID {o.id} ist bereits vergeben")
            self._objects[o.id] = o
            self.reserve_ids_above(o.id)
            cs.added.add(o.id)
        return cs

    def _remove(self, ids: Iterable[int]) -> tuple[list[MapObject], ChangeSet]:
        cs = ChangeSet()
        removed: list[MapObject] = []
        for oid in ids:
            obj = self._objects.pop(oid, None)
            if obj is not None:
                removed.append(obj)
                cs.removed.add(oid)
        return removed, cs

    def _replace(self, objs: Iterable[MapObject]) -> tuple[list[MapObject], ChangeSet]:
        cs = ChangeSet()
        old: list[MapObject] = []
        for o in objs:
            prev = self._objects.get(o.id)
            if prev is None:
                raise KeyError(f"ID {o.id} existiert nicht")
            old.append(prev)
            self._objects[o.id] = o
            cs.modified.add(o.id)
        return old, cs

    def _set_world_keyvalues(self, kvs: tuple[tuple[str, str], ...]) -> ChangeSet:
        self.world_keyvalues = kvs
        return ChangeSet(world_changed=True)


POINT_ENTITY_HALF_SIZE = 8


def owner_id(obj: MapObject) -> int | None:
    """Zu welchem Objekt ein Brush gehört: seiner Brush-Entity oder seinem Baustein."""
    if isinstance(obj, Solid):
        if obj.parent_id is not None:
            return obj.parent_id
        return obj.extra.get("block_of")
    return None


#: Hülle von Entities mit Modell (Props). Der Kern kennt keine Spieldateien; der Editor
#: setzt diese Funktion, sobald eine Modell-Bibliothek da ist.
_entity_bounds: Callable[[Entity], BBox | None] | None = None


def set_entity_bounds(fn: Callable[[Entity], BBox | None] | None) -> None:
    global _entity_bounds
    _entity_bounds = fn


def object_bbox(obj: MapObject) -> BBox | None:
    if isinstance(obj, Solid):
        return obj.bbox()
    if _entity_bounds is not None:
        bb = _entity_bounds(obj)
        if bb is not None:
            return bb
    origin = obj.origin
    if origin is None:
        return None
    h = POINT_ENTITY_HALF_SIZE
    return BBox(
        (origin[0] - h, origin[1] - h, origin[2] - h),
        (origin[0] + h, origin[1] + h, origin[2] + h),
    )
