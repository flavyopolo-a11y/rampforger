"""Materialien auf Objekte und einzelne Seiten anwenden, als ein Undo-Schritt.

Bei Bausteinen werden nicht die Brushes umgefärbt (sie würden beim nächsten Regler-
Ändern zurückspringen), sondern die Material-Regler des Bausteins gesetzt.
"""
from __future__ import annotations

import dataclasses
from typing import Callable, Iterable

from ..blocks import MEMBER_KEY, block_info, change_block
from ..commands import Command, MacroCommand, ReplaceObjects
from ..model import Entity, Face, MapDocument, MapObject, Solid
from ..surf.catalog import CATALOG

#: Seite eines Brushes: (Brush-ID, Index der Face)
FaceRef = tuple[int, int]
NODRAW = "TOOLS/TOOLSNODRAW"


def _block_roles(root: Entity) -> dict[str, str]:
    """Material → Regler-Schlüssel eines Bausteins (nur die vorhandenen Material-Regler)."""
    info = block_info(root)
    if info is None:
        return {}
    keys = {p.key for p in CATALOG[info["template"]].params}
    values = CATALOG[info["template"]].values(info["values"])
    return {str(values[k]).upper(): k for k in ("mat_surf", "mat_seite") if k in keys}


def _owner_block(doc: MapDocument, solid: Solid) -> Entity | None:
    if solid.parent_id is None:
        return None
    parent = doc.get(solid.parent_id)
    return parent if isinstance(parent, Entity) and block_info(parent) is not None else None


def _retexture(solid: Solid, fn: Callable[[Face], Face], indices: Iterable[int] | None = None) -> Solid:
    wanted = set(indices) if indices is not None else None
    faces = tuple(fn(f) if wanted is None or i in wanted else f for i, f in enumerate(solid.faces))
    return solid.replace(faces=faces)


def _block_command(doc: MapDocument, root: Entity, values: dict) -> Command | None:
    info = block_info(root)
    assert info is not None
    if all(info["values"].get(k) == v for k, v in values.items()):
        return None
    return change_block(doc, root.id, values)[0]


def apply_to_objects(doc: MapDocument, ids: Iterable[int], material: str) -> Command | None:
    """Alle Seiten der Objekte bekommen das Material. Bausteine: Surf- und Seiten-Regler."""
    material = material.upper()
    replaced: list[MapObject] = []
    cmds: list[Command] = []
    for oid in ids:
        obj = doc.get(oid)
        if isinstance(obj, Entity) and block_info(obj) is not None:
            roles = _block_roles(obj)
            cmd = _block_command(doc, obj, {k: material for k in roles.values()}) if roles else None
            if cmd is not None:
                cmds.append(cmd)
            continue
        solids = [obj] if isinstance(obj, Solid) else doc.children(oid) if isinstance(obj, Entity) else []
        for s in solids:
            if MEMBER_KEY in s.extra:
                continue
            new = _retexture(s, lambda f: dataclasses.replace(f, material=material))
            if new.faces != s.faces:
                replaced.append(new)
    if replaced:
        cmds.insert(0, ReplaceObjects(replaced, "Material anwenden"))
    return _combine(cmds, "Material anwenden")


def edit_faces(doc: MapDocument, refs: Iterable[FaceRef], fn: Callable[[Face], Face],
               description: str = "Seiten bearbeiten", merge_key: object | None = None) -> Command | None:
    """`fn` auf einzelne Seiten anwenden. Seiten von Bausteinen können nur ihr Material
    ändern (über die Regler), Ausrichtung gilt dort nicht dauerhaft und wird übersprungen."""
    by_solid: dict[int, list[int]] = {}
    for sid, idx in refs:
        by_solid.setdefault(sid, []).append(idx)
    replaced: list[MapObject] = []
    block_values: dict[int, dict] = {}
    for sid, indices in by_solid.items():
        solid = doc.get(sid)
        if not isinstance(solid, Solid):
            continue
        root = _owner_block(doc, solid)
        if root is not None:
            roles = _block_roles(root)
            for i in indices:
                old = solid.faces[i]
                new = fn(old)
                key = roles.get(old.material.upper())
                if key and new.material.upper() != old.material.upper():
                    block_values.setdefault(root.id, {})[key] = new.material.upper()
            continue
        new_solid = _retexture(solid, fn, indices)
        if new_solid.faces != solid.faces:
            replaced.append(new_solid)
    cmds: list[Command] = []
    if replaced:
        cmds.append(ReplaceObjects(replaced, description, merge_key=merge_key))
    for rid, values in block_values.items():
        root = doc.get(rid)
        assert isinstance(root, Entity)
        cmd = _block_command(doc, root, values)
        if cmd is not None:
            cmds.append(cmd)
    return _combine(cmds, description)


def _combine(cmds: list[Command], description: str) -> Command | None:
    if not cmds:
        return None
    return cmds[0] if len(cmds) == 1 else MacroCommand(cmds, description)


def replace_material(doc: MapDocument, old: str, new: str) -> Command | None:
    """Ein Material in der ganzen Map ersetzen (auch in Bausteinen)."""
    old_u, new_u = old.upper(), new.upper()
    refs: list[FaceRef] = []
    for s in doc.solids():
        if MEMBER_KEY in s.extra:
            continue
        refs += [(s.id, i) for i, f in enumerate(s.faces) if f.material.upper() == old_u]
    return edit_faces(doc, refs, lambda f: dataclasses.replace(f, material=new_u), "Material ersetzen")


__all__ = ["FaceRef", "apply_to_objects", "edit_faces", "replace_material"]
