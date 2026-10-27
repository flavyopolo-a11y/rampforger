"""Bausteine: Objekte aus der Bibliothek, deren Regler sich nachträglich ändern lassen.

Ein Baustein besteht aus
- einer Wurzel-Entity (func_brush „nie fest“ oder func_detail), die in `extra["block"]`
  Vorlage, Reglerwerte und Platzierung speichert, mit den sichtbaren Brushes als Kindern,
- bei Kollision „Playerclip“ zusätzlich aus Welt-Brushes mit Playerclip-Textur, die über
  `extra["block_of"]` zur Wurzel gehören. Sie sind deckungsgleich mit den sichtbaren
  Brushes und geben dem Spieler die Kollision.

Ändern heißt: alle Brushes neu erzeugen und in einem Schritt austauschen (`SwapObjects`).
Die Wurzel behält ihre ID, damit Auswahl und Verweise erhalten bleiben.
"""
from __future__ import annotations

import dataclasses
import random
from typing import Callable, Iterable, Sequence

from .commands import Command, ReplaceObjects, SwapObjects
from .model import EditorInfo, Entity, MapDocument, MapObject, Solid, owner_id
from .surf.catalog import CATALOG, ORIGIN, Generated, Placement, generate

BLOCK_KEY = "block"
MEMBER_KEY = "block_of"
PLAYERCLIP = "TOOLS/TOOLSPLAYERCLIP"
CLIP_COLOR = (200, 90, 220)


def block_info(obj: MapObject | None) -> dict | None:
    if isinstance(obj, Entity):
        return obj.extra.get(BLOCK_KEY)
    return None


def is_block_root(obj: MapObject | None) -> bool:
    return block_info(obj) is not None


def is_clip_member(obj: MapObject | None) -> bool:
    return isinstance(obj, Solid) and obj.parent_id is None and MEMBER_KEY in obj.extra


def placement_of(info: dict) -> Placement:
    x, y, z, yaw = info["placement"]
    return Placement(x, y, z, yaw)


def _root_entity(root_id: int, collision: str, info: dict, editor: EditorInfo | None) -> Entity:
    if collision == "clip":
        # Nie fest: Die Kollision kommt von den Playerclip-Brushes in der Welt
        kvs = (("Solidity", "1"), ("vrad_brush_cast_shadows", "1"))
        classname = "func_brush"
    else:
        kvs = ()
        classname = "func_detail"
    return Entity(id=root_id, classname=classname, keyvalues=kvs,
                  editor=editor or EditorInfo(color=(220, 30, 220)), extra={BLOCK_KEY: info})


def build_block(doc: MapDocument, template: str, values: dict | None = None, at: Placement = ORIGIN,
                root_id: int | None = None, root_editor: EditorInfo | None = None,
                color: tuple[int, int, int] | None = None) -> tuple[list[MapObject], Generated]:
    """Erzeugt die Objekte eines Bausteins (Wurzel zuerst). IDs kommen aus dem Dokument."""
    t = CATALOG[template]
    v = t.values(values)
    gen = generate(t, v, at)
    info = {"template": template, "values": v, "placement": [at.x, at.y, at.z, at.yaw]}
    collision = v.get("kollision", "clip")
    root = _root_entity(root_id if root_id is not None else doc.new_id(), collision, info, root_editor)
    if color is None:
        rng = random.Random()
        color = (rng.randint(80, 255), rng.randint(80, 255), rng.randint(80, 255))
    objs: list[MapObject] = [root]
    for faces in gen.face_sets:
        objs.append(Solid(id=doc.new_id(), faces=faces, parent_id=root.id, editor=EditorInfo(color=color)))
    if collision == "clip":
        for faces in gen.face_sets:
            clip = tuple(dataclasses.replace(f, material=PLAYERCLIP) for f in faces)
            objs.append(Solid(id=doc.new_id(), faces=clip, editor=EditorInfo(color=CLIP_COLOR),
                              extra={MEMBER_KEY: root.id}))
    return objs, gen


def rebuild(doc: MapDocument, root: Entity, values: dict | None = None,
            at: Placement | None = None) -> tuple[list[MapObject], Generated]:
    """Neue Objekte für einen bestehenden Baustein (gleiche Wurzel-ID und Farbe)."""
    info = block_info(root)
    assert info is not None
    merged = {**info["values"], **(values or {})}
    kids = doc.children(root.id)
    color = kids[0].editor.color if kids else None
    return build_block(doc, info["template"], merged, at or placement_of(info), root.id, root.editor, color)


def change_block(doc: MapDocument, root_id: int, values: dict | None = None, at: Placement | None = None,
                 merge_key: object | None = None) -> tuple[Command, Generated]:
    root = doc.get(root_id)
    assert isinstance(root, Entity) and is_block_root(root)
    new, gen = rebuild(doc, root, values, at)
    old = [root_id] + [s.id for s in doc.attached([root_id])]
    return SwapObjects(old, new, "Baustein ändern", merge_key), gen


def dissolve(doc: MapDocument, root_ids: Iterable[int]) -> Command | None:
    """Baustein lösen: Die Brushes bleiben, sind aber nicht mehr über Regler veränderbar.
    Die Playerclip-Brushes werden zu normalen Welt-Brushes."""
    changed: list[MapObject] = []
    for rid in root_ids:
        root = doc.get(rid)
        if not is_block_root(root):
            continue
        assert isinstance(root, Entity)
        extra = {k: v for k, v in root.extra.items() if k != BLOCK_KEY}
        changed.append(root.replace(extra=extra))
        for s in doc.attached([rid]):
            if MEMBER_KEY in s.extra:
                changed.append(s.replace(extra={k: v for k, v in s.extra.items() if k != MEMBER_KEY}))
    return ReplaceObjects(changed, "Baustein lösen") if changed else None


def transform_command(doc: MapDocument, originals: Sequence[MapObject], fn: Callable[[MapObject], MapObject],
                      description: str, merge_key: object | None = None) -> Command:
    """Command, das `fn` auf alle `originals` anwendet (Auswahl samt zugehöriger Brushes).

    Gedrehte Bausteine werden aus ihren Reglern neu erzeugt statt Punkt für Punkt gedreht,
    damit Nähte exakt und Ecken ganzzahlig bleiben. `fn` darf TransformError werfen.
    """
    roots = {o.id: fn(o) for o in originals if is_block_root(o)}
    if not roots:
        return ReplaceObjects([fn(o) for o in originals], description, merge_key=merge_key)
    regen = {rid: r for rid, r in roots.items()
             if (info := block_info(r)) is not None
             and info["placement"][3] != block_info(doc.get(rid))["placement"][3]}  # type: ignore[index]
    add: list[MapObject] = []
    for o in originals:
        if o.id in regen:
            add += rebuild(doc, regen[o.id])[0]  # type: ignore[arg-type]
        elif o.id in roots:
            add.append(roots[o.id])
        elif owner_id(o) not in regen:
            add.append(fn(o))
    return SwapObjects([o.id for o in originals], add, description, merge_key)


def clone_objects(doc: MapDocument, objs: Sequence[MapObject]) -> tuple[list[MapObject], list[int]]:
    """Kopien mit neuen IDs; Zugehörigkeiten (Brush-Entity, Baustein) werden mitgeführt.
    Liefert die Kopien und die IDs der obersten Objekte (für die Auswahl)."""
    id_map = {o.id: doc.new_id() for o in objs}
    out: list[MapObject] = []
    roots: list[int] = []
    for o in objs:
        nid = id_map[o.id]
        if isinstance(o, Entity):
            out.append(o.replace(id=nid, vmf_id=None))
            roots.append(nid)
            continue
        parent = id_map.get(o.parent_id) if o.parent_id is not None else None
        extra = o.extra
        if MEMBER_KEY in extra:
            if extra[MEMBER_KEY] in id_map:
                extra = {**extra, MEMBER_KEY: id_map[extra[MEMBER_KEY]]}
            else:
                extra = {k: v for k, v in extra.items() if k != MEMBER_KEY}
        out.append(o.replace(id=nid, parent_id=parent, vmf_id=None, extra=extra))
        if owner_id(out[-1]) is None:
            roots.append(nid)
    return out, roots


__all__ = [
    "BLOCK_KEY",
    "MEMBER_KEY",
    "PLAYERCLIP",
    "block_info",
    "build_block",
    "change_block",
    "clone_objects",
    "dissolve",
    "is_block_root",
    "is_clip_member",
    "placement_of",
    "rebuild",
    "transform_command",
]
