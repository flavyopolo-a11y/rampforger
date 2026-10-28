"""Map-Statistik: was die Map enthält und wie nah sie an den Grenzen von Source liegt.

Die Grenzen gelten für BSP-Version 20 (CS:S, Momentum, Source 2013). Was vbsp nach dem
Kompilieren zählt (Planes, Leafs, Lightmaps …), kennt der Editor nicht; diese Zahlen hier
sind die, die man beim Bauen selbst in der Hand hat.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..geometry.displacement import has_displacement
from ..model import Entity, MapDocument

#: Entities, die vbsp/vrad entfernen oder die nicht übers Netz gehen (zählen nicht zum Edict-Limit)
NOT_NETWORKED = {"func_detail", "prop_static", "info_overlay", "infodecal", "light", "light_spot",
                 "light_environment", "env_cubemap", "info_lighting", "func_viscluster", "info_null",
                 "info_node", "info_node_hint", "func_areaportal", "func_occluder", "info_overlay_transition",
                 "func_ladder", "worldspawn"}
#: Koordinaten, die die Engine noch darstellt
MAP_EXTENT = 16384


@dataclass(frozen=True)
class Stat:
    key: str
    label: str
    value: int
    limit: int | None = None
    hint: str = ""

    @property
    def share(self) -> float | None:
        return self.value / self.limit if self.limit else None

    @property
    def level(self) -> str:
        """„ok“, „knapp“ (ab 75 %) oder „zu viel“."""
        s = self.share
        if s is None or s < 0.75:
            return "ok"
        return "knapp" if s <= 1.0 else "zu viel"


def map_stats(doc: MapDocument) -> list[Stat]:
    solids = list(doc.solids())
    entities = [o for o in doc.objects() if isinstance(o, Entity)]
    brush_ents = [e for e in entities if doc.children(e.id)]
    sides = sum(len(s.faces) for s in solids)
    disps = sum(1 for s in solids for f in s.faces if has_displacement(f))
    materials = {f.material.upper() for s in solids for f in s.faces}
    overlays = sum(1 for e in entities if e.classname == "info_overlay")
    props = sum(1 for e in entities if e.classname == "prop_static")
    lights = sum(1 for e in entities if e.classname.startswith("light"))
    networked = sum(1 for e in entities if e.classname.lower() not in NOT_NETWORKED)
    bb = doc.bbox()
    extent = 0 if bb is None else int(max(max(abs(v) for v in bb.mins), max(abs(v) for v in bb.maxs)))
    return [
        Stat("brushes", "Brushes", len(solids), 8192, "MAX_MAP_BRUSHES"),
        Stat("sides", "Brush-Seiten", sides, 65536, "MAX_MAP_BRUSHSIDES"),
        Stat("entities", "Entities", len(entities), 8192, "MAX_MAP_ENTITIES"),
        Stat("edicts", "Davon im Spiel vernetzt (ca.)", networked, 2048,
             "Edict-Limit der Engine; darüber stürzt die Map beim Laden ab"),
        Stat("brush_entities", "Brush-Entities", len(brush_ents)),
        Stat("props", "Props (prop_static)", props),
        Stat("lights", "Lichter", lights),
        Stat("overlays", "Overlays", overlays, 512, "MAX_MAP_OVERLAYS"),
        Stat("displacements", "Displacements", disps, 2048, "MAX_MAP_DISPINFO"),
        Stat("materials", "Verschiedene Materialien", len(materials), 2048, "MAX_MAP_TEXDATA"),
        Stat("extent", "Größte Koordinate", extent, MAP_EXTENT, "Weiter draußen wird nichts mehr gezeichnet"),
    ]


__all__ = ["MAP_EXTENT", "Stat", "map_stats"]
