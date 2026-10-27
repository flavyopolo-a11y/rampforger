"""Map-Thema: welche Materialien Rampen, Rampenseiten und Wände bekommen.

Das Thema hängt am Dokument (`doc.extra["theme"]`, wird mit dem Projekt gespeichert).
Neue Rampen aus der Bibliothek übernehmen es, und `apply_theme` färbt bestehende Rampen,
Bhop-Blöcke und Wände in einem Undo-Schritt um. Werkzeug-Texturen (Nodraw, Clip,
Trigger, Skybox) bleiben immer unverändert.
"""
from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass, fields
from typing import Iterable

from ..blocks import MEMBER_KEY, block_info, change_block
from ..commands import Command, MacroCommand, ReplaceObjects
from ..model import Entity, MapDocument, MapObject, Solid
from ..surf.catalog import CATALOG, Template

THEME_KEY = "theme"
#: Brush-Entities, deren Brushes wie Wände behandelt werden
WALL_ENTITIES = {"func_detail", "func_brush", "func_wall", "func_illusionary"}


@dataclass
class Theme:
    ramp: str = ""          # Surf-Fläche
    ramp_side: str = ""     # Lippe, Enden, Kanten
    wall: str = ""          # Wände, Böden, Plattformen, Bhop-Blöcke
    #: Kollision neuer und umgefärbter Rampen: "clip" (Playerclip, empfohlen) oder "detail"
    collision: str = "clip"
    #: Gewählte Farben, damit der Assistent sie beim nächsten Mal wieder zeigt (#rrggbb)
    colors: dict | None = None

    def is_set(self) -> bool:
        return bool(self.ramp or self.ramp_side or self.wall)


def get_theme(doc: MapDocument) -> Theme:
    raw = doc.extra.get(THEME_KEY)
    if not isinstance(raw, dict):
        return Theme()
    known = {f.name for f in fields(Theme)}
    return Theme(**{k: v for k, v in raw.items() if k in known})


def set_theme(doc: MapDocument, theme: Theme) -> None:
    doc.extra[THEME_KEY] = asdict(theme)


def block_defaults(doc: MapDocument, template: Template) -> dict:
    """Werte, die eine neue Vorlage aus dem Thema der Map bekommt."""
    return theme_values(get_theme(doc), template)


def theme_values(theme: Theme, template: Template) -> dict:
    """Regler-Werte eines Themas für eine Vorlage (nur vorhandene Regler)."""
    keys = {p.key for p in template.params}
    out: dict = {}
    if "kollision" in keys:
        out["kollision"] = theme.collision
    if not theme.is_set():
        return out
    if template.category == "Bhop":
        if "mat_seite" in keys and theme.wall:
            out["mat_seite"] = theme.wall
        return out
    if "mat_surf" in keys and theme.ramp:
        out["mat_surf"] = theme.ramp
    if "mat_seite" in keys and theme.ramp_side:
        out["mat_seite"] = theme.ramp_side
    return out


def _is_tool(material: str) -> bool:
    return material.upper().startswith("TOOLS/")


def apply_theme(doc: MapDocument, theme: Theme, ids: Iterable[int] | None = None) -> Command | None:
    """Thema auf die ganze Map (ids=None) oder nur auf die genannten Objekte anwenden."""
    if ids is None:
        roots = [o for o in doc.objects() if not (isinstance(o, Solid) and (o.parent_id is not None or MEMBER_KEY in o.extra))]
    else:
        roots = [o for i in ids if (o := doc.get(i)) is not None]
    cmds: list[Command] = []
    replaced: list[MapObject] = []
    for obj in roots:
        if isinstance(obj, Entity):
            info = block_info(obj)
            if info is not None:
                values = theme_values(theme, CATALOG[info["template"]])
                if values and any(info["values"].get(k) != v for k, v in values.items()):
                    cmds.append(change_block(doc, obj.id, values)[0])
                continue
            if obj.classname in WALL_ENTITIES and theme.wall:
                replaced += _walls(doc.children(obj.id), theme.wall)
            continue
        if isinstance(obj, Solid) and theme.wall:
            replaced += _walls([obj], theme.wall)
    if replaced:
        cmds.insert(0, ReplaceObjects(replaced, "Thema anwenden"))
    if not cmds:
        return None
    return cmds[0] if len(cmds) == 1 else MacroCommand(cmds, "Thema anwenden")


def _walls(solids: Iterable[Solid], wall: str) -> list[Solid]:
    out = []
    for s in solids:
        if MEMBER_KEY in s.extra:
            continue
        faces = tuple(f if _is_tool(f.material) else dataclasses.replace(f, material=wall.upper())
                      for f in s.faces)
        if faces != s.faces:
            out.append(s.replace(faces=faces))
    return out


__all__ = ["THEME_KEY", "Theme", "apply_theme", "block_defaults", "get_theme", "set_theme", "theme_values"]
