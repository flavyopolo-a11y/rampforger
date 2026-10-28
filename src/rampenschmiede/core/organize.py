"""Ordnen wie in Hammer: Gruppen, Brushes an eine Entity binden, zurück zur Welt, Mehrfach
kopieren, Auswahl ans Raster.

Gruppen stehen in `EditorInfo.group_id` (wie `groupid` in VMF). Wer ein Mitglied anklickt,
bekommt die ganze Gruppe, solange „Gruppen ignorieren“ aus ist. Rampen-Bausteine bleiben, was
sie sind: Binden und Zur-Welt verlangen, dass sie vorher gelöst werden.
"""
from __future__ import annotations

import dataclasses
from typing import Iterable, Sequence

from .blocks import clone_objects, is_block_root, transform_command
from .commands import AddObjects, Command, Deferred, ReplaceObjects, SwapObjects
from .geometry import transform
from .mathutil import Point
from .model import EditorInfo, Entity, MapDocument, MapObject, Solid, owner_id

TRIGGER = "TOOLS/TOOLSTRIGGER"
#: Häufige Brush-Entities zuerst (Strg+T)
COMMON_BRUSH_CLASSES = (
    "func_detail", "func_illusionary", "func_wall", "func_brush", "func_breakable", "func_door",
    "func_button", "func_rotating", "func_movelinear", "func_water_analog", "func_ladder",
    "trigger_multiple", "trigger_once", "trigger_push", "trigger_teleport", "trigger_hurt",
    "func_buyzone", "func_bomb_target", "func_hostage_rescue", "func_areaportal", "func_occluder",
)


class OrganizeError(ValueError):
    pass


# ---- Gruppen -------------------------------------------------------------------------------

def group_of(obj: MapObject) -> int | None:
    return obj.editor.group_id


def new_group_id(doc: MapDocument) -> int:
    used = [g for o in doc.objects() if (g := o.editor.group_id) is not None]
    return max(used, default=0) + 1


def _roots(doc: MapDocument, objs: Iterable[MapObject]) -> list[MapObject]:
    """Oberste Objekte: Brushes einer Entity zählen als die Entity."""
    out: dict[int, MapObject] = {}
    for o in objs:
        owner = owner_id(o)
        root = doc.get(owner) if owner is not None else o
        if root is not None:
            out.setdefault(root.id, root)
    return list(out.values())


def group(doc: MapDocument, objs: Sequence[MapObject]) -> tuple[Command, int] | None:
    roots = _roots(doc, objs)
    if len(roots) < 2:
        return None
    gid = new_group_id(doc)
    new = [o.replace(editor=dataclasses.replace(o.editor, group_id=gid)) for o in roots]
    return ReplaceObjects(new, "Gruppieren"), gid


def ungroup(doc: MapDocument, objs: Sequence[MapObject]) -> Command | None:
    gids = {g for o in _roots(doc, objs) if (g := o.editor.group_id) is not None}
    if not gids:
        return None
    new = [o.replace(editor=dataclasses.replace(o.editor, group_id=None))
           for o in doc.objects() if o.editor.group_id in gids]
    return ReplaceObjects(new, "Gruppe auflösen")


def expand_groups(doc: MapDocument, ids: Iterable[int]) -> set[int]:
    """Auswahl um alle Mitglieder der berührten Gruppen erweitern."""
    ids = set(ids)
    gids = {g for i in ids if (o := doc.get(i)) is not None and (g := o.editor.group_id) is not None}
    if not gids:
        return ids
    return ids | {o.id for o in doc.objects() if o.editor.group_id in gids}


# ---- Binden und lösen ------------------------------------------------------------------------

def _solids_of(doc: MapDocument, objs: Iterable[MapObject]) -> tuple[list[Solid], set[int]]:
    """Brushes der Auswahl und die Entities, aus denen sie stammen."""
    solids: dict[int, Solid] = {}
    sources: set[int] = set()
    for o in objs:
        if isinstance(o, Solid):
            if o.extra.get("block_of") is not None or (
                    o.parent_id is not None and is_block_root(doc.get(o.parent_id))):
                raise OrganizeError("Rampen-Bausteine erst lösen (Bibliothek: „Baustein lösen“)")
            solids[o.id] = o
            if o.parent_id is not None:
                sources.add(o.parent_id)
        elif isinstance(o, Entity):
            if is_block_root(o):
                raise OrganizeError("Rampen-Bausteine erst lösen (Bibliothek: „Baustein lösen“)")
            kids = doc.children(o.id)
            if kids:
                sources.add(o.id)
            for s in kids:
                solids[s.id] = s
    return list(solids.values()), sources


def _emptied(doc: MapDocument, sources: set[int], moved: set[int]) -> list[int]:
    return [eid for eid in sources if all(s.id in moved for s in doc.children(eid))]


def tie_to_entity(doc: MapDocument, objs: Sequence[MapObject], classname: str,
                  keyvalues: tuple[tuple[str, str], ...] = ()) -> tuple[Command, int]:
    """Brushes der Auswahl in eine neue Brush-Entity packen (Strg+T)."""
    solids, sources = _solids_of(doc, objs)
    if not solids:
        raise OrganizeError("Erst Brushes auswählen, die zur Entity werden sollen")
    kvs = tuple(keyvalues)
    if classname.startswith("trigger_") and not any(k == "spawnflags" for k, _ in kvs):
        kvs += (("spawnflags", "1"),)  # Spieler lösen aus
    ent = Entity(id=doc.new_id(), classname=classname, keyvalues=kvs, editor=EditorInfo(color=(220, 30, 220)))
    moved = []
    for s in solids:
        faces = s.faces
        if classname.startswith("trigger_"):
            faces = tuple(dataclasses.replace(f, material=TRIGGER) for f in faces)
        moved.append(s.replace(parent_id=ent.id, faces=faces))
    gone = _emptied(doc, sources, {s.id for s in solids})
    return SwapObjects([s.id for s in solids] + gone, [ent, *moved], f"An {classname} binden"), ent.id


def move_to_world(doc: MapDocument, objs: Sequence[MapObject]) -> tuple[Command, list[int]]:
    """Brushes aus ihren Entities lösen (Strg+Shift+W); leere Entities verschwinden."""
    solids, sources = _solids_of(doc, objs)
    solids = [s for s in solids if s.parent_id is not None]
    if not solids:
        raise OrganizeError("In der Auswahl sind keine Brushes einer Entity")
    moved = [s.replace(parent_id=None) for s in solids]
    gone = _emptied(doc, sources, {s.id for s in solids})
    return SwapObjects([s.id for s in solids] + gone, moved, "Zur Welt"), [s.id for s in moved]


# ---- Mehrfach kopieren -------------------------------------------------------------------------

def multi_copy(doc: MapDocument, objs: Sequence[MapObject], count: int, offset: Point,
               rotation: Point = (0.0, 0.0, 0.0), pivot: Point | None = None, texture_lock: bool = True,
               make_group: bool = False) -> tuple[Command, list[int]]:
    """`count` Kopien, die n-te um n·`offset` verschoben und um n·`rotation` (Grad um X, Y, Z,
    um `pivot`) gedreht. Gibt das Command und die IDs der obersten Kopien zurück."""
    roots = _roots(doc, objs)
    if not roots or count < 1:
        raise OrganizeError("Erst etwas auswählen, das kopiert werden soll")
    everything = roots + doc.attached(o.id for o in roots)
    if pivot is None:
        bb = doc.bbox(o.id for o in roots)
        pivot = bb.center if bb is not None else (0.0, 0.0, 0.0)
    gid = new_group_id(doc) if make_group else None
    top_ids: list[int] = []
    steps = []
    for n in range(1, count + 1):
        clones, tops = clone_objects(doc, everything)
        if gid is not None:
            clones = [c.replace(editor=dataclasses.replace(c.editor, group_id=gid)) if c.id in tops else c
                      for c in clones]
        top_ids += tops

        def fn(o: MapObject, n: int = n) -> MapObject:
            for axis in (0, 1, 2):
                if rotation[axis]:
                    o = transform.rotate(o, pivot, axis, rotation[axis] * n, texture_lock)  # type: ignore[arg-type]
            return transform.translate(o, (offset[0] * n, offset[1] * n, offset[2] * n), texture_lock)

        steps.append(lambda _doc, c=clones: AddObjects(c))
        if any(rotation) or any(offset):
            steps.append(lambda d, c=clones, f=fn: transform_command(d, [d.get(o.id) for o in c], f, "Kopie"))
    return Deferred(steps, f"{count}× kopieren"), top_ids


def snap_delta(bbox_mins: Point, grid: int) -> Point:
    """Verschiebung, die die untere Ecke der Auswahl aufs Raster legt (Strg+B)."""
    return tuple(round(m / grid) * grid - m for m in bbox_mins)  # type: ignore[return-value]


__all__ = ["COMMON_BRUSH_CLASSES", "OrganizeError", "expand_groups", "group", "group_of", "move_to_world",
           "multi_copy", "new_group_id", "snap_delta", "tie_to_entity", "ungroup"]
