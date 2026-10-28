"""Suchen und Ersetzen (Strg+F) und Gehe zu ID (Strg+Shift+G), wie in Hammer.

Entities sucht man nach Klasse, Name oder irgendeinem Wert, Texturen nach Namen mit
Platzhaltern (`*`, `?`). Ersetzen ist je ein Undo-Schritt. Seiten von Rampen-Bausteinen
entstehen aus deren Reglern und werden beim Textur-Ersetzen nicht angefasst.
"""
from __future__ import annotations

import dataclasses
import fnmatch
import re
from typing import Iterable

from ..i18n import tr
from .blocks import MEMBER_KEY
from .commands import Command, ReplaceObjects
from .materials.apply import FaceRef, edit_faces
from .model import Entity, MapDocument, Solid, owner_id

FIELDS = ("klasse", "name", "alle")


def _wild(text: str) -> bool:
    return any(c in text for c in "*?")


def _matches(value: str, text: str, whole: bool) -> bool:
    if _wild(text):
        return fnmatch.fnmatchcase(value.lower(), text.lower())
    return value.lower() == text.lower() if whole else text.lower() in value.lower()


def find_entities(doc: MapDocument, text: str, field: str = "alle", whole: bool = False) -> list[int]:
    """IDs der Entities, deren Klasse, Name (targetname) oder irgendein Wert passt."""
    if not text:
        return []
    out = []
    for e in doc.entities():
        if field == "klasse":
            hit = _matches(e.classname, text, whole)
        elif field == "name":
            hit = _matches(e.get("targetname", ""), text, whole)
        else:
            hit = _matches(e.classname, text, whole) or any(_matches(v, text, whole) for _k, v in e.keyvalues) \
                or any(_matches(o.target, text, whole) for o in e.outputs)
        if hit:
            out.append(e.id)
    return sorted(out)


def _sub(value: str, text: str, new: str, whole: bool) -> str:
    if whole or _wild(text):
        return new if _matches(value, text, True) else value
    return re.sub(re.escape(text), lambda _m: new, value, flags=re.IGNORECASE)


def replace_in_entities(doc: MapDocument, ids: Iterable[int], text: str, new: str, field: str = "alle",
                        whole: bool = False) -> Command | None:
    """`text` in Klasse, Name oder allen Werten (samt I/O-Zielen) durch `new` ersetzen."""
    changed = []
    for i in ids:
        e = doc.get(i)
        if not isinstance(e, Entity):
            continue
        cls = e.classname
        kvs = e.keyvalues
        outputs = e.outputs
        if field in ("klasse", "alle"):
            cls = _sub(cls, text, new, whole)
        if field == "name":
            kvs = tuple((k, _sub(v, text, new, whole) if k.lower() == "targetname" else v) for k, v in kvs)
        elif field == "alle":
            kvs = tuple((k, _sub(v, text, new, whole)) for k, v in kvs)
            outputs = tuple(dataclasses.replace(o, target=_sub(o.target, text, new, whole)) for o in outputs)
        if (cls, kvs, outputs) != (e.classname, e.keyvalues, e.outputs):
            changed.append(e.replace(classname=cls, keyvalues=kvs, outputs=outputs))
    return ReplaceObjects(changed, "Ersetzen") if changed else None


def _pattern(pattern: str) -> str:
    return pattern.strip().replace("\\", "/").upper()


def material_match(material: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(material.upper(), _pattern(pattern))


def _solids_in(doc: MapDocument, ids: Iterable[int] | None) -> list[Solid]:
    if ids is None:
        return list(doc.solids())
    ids = set(ids)
    return [s for s in doc.solids() if s.id in ids or owner_id(s) in ids]


def find_material_users(doc: MapDocument, pattern: str, ids: Iterable[int] | None = None) -> list[int]:
    """Oberste Objekte (Brush, Brush-Entity, Baustein), die eine passende Textur tragen."""
    out: dict[int, None] = {}
    for s in _solids_in(doc, ids):
        if any(material_match(f.material, pattern) for f in s.faces):
            out[owner_id(s) or s.id] = None
    return list(out)


def replace_materials(doc: MapDocument, pattern: str, new: str, ids: Iterable[int] | None = None) -> Command | None:
    """Passende Texturen in der Map (oder nur in `ids`) ersetzen."""
    new_u = new.strip().replace("\\", "/").upper()
    if not new_u:
        return None
    refs: list[FaceRef] = []
    for s in _solids_in(doc, ids):
        if MEMBER_KEY in s.extra:
            continue
        refs += [(s.id, i) for i, f in enumerate(s.faces) if material_match(f.material, pattern)]
    return edit_faces(doc, refs, lambda f: dataclasses.replace(f, material=new_u), tr("Textur ersetzen"))


def used_materials(doc: MapDocument) -> list[str]:
    return sorted({f.material.upper() for s in doc.solids() for f in s.faces})


def goto_id(doc: MapDocument, text: str) -> int | None:
    """Objekt zu einer Zahl: zuerst die ID im exportierten VMF (wie Hammer und das Kompilier-Log
    sie nennen), dann die interne ID; sonst ein Entity-Name."""
    from .io.vmf import export_vmf

    t = text.strip().lstrip("#")
    if t.isdigit():
        n = int(t)
        exported = export_vmf(doc)
        hit = exported.solid_ids.get(n, exported.entity_ids.get(n))
        if hit is None and n in doc:
            hit = n
        if hit is not None:
            o = doc.get(hit)
            return owner_id(o) or hit if o is not None else hit
        return None
    names = find_entities(doc, t, "name", whole=True)
    return names[0] if names else None


__all__ = ["FIELDS", "find_entities", "find_material_users", "goto_id", "material_match", "replace_in_entities",
           "replace_materials", "used_materials"]
