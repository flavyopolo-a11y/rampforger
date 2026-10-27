"""BSP öffnen: eine kompilierte Map wieder in Brushes und Entities zurückverwandeln.

Eine BSP enthält die ursprünglichen Brushes noch als Ebenen-Listen (für die Kollision).
Daraus werden wieder Brushes mit Eckpunkten und Texturen, ähnlich wie BSPSource es macht.
Was beim Kompilieren verloren geht, kann nicht zurückkommen: Displacements werden zu
flachen Brushes, Overlays und Detail-Props fehlen, Detail-Brushes landen gesammelt in
einem `func_detail`. Statische Props werden wieder `prop_static`-Entities.
"""
from __future__ import annotations

import math
import os
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

from ..geometry.brush import face_polygons, vmf_points_from_loop
from ..mathutil import Plane
from ..model import EditorInfo, Entity, Face, MapDocument, MapObject, Output, Solid, TexAxis
from ..model.objects import default_tex_axes


class BspError(ValueError):
    pass


@dataclass
class BspReport:
    solids: int = 0
    entities: int = 0
    props: int = 0
    displacements: int = 0
    broken: int = 0
    warnings: list[str] = field(default_factory=list)


#: Diese Keys entstehen erst beim Kompilieren und gehören nicht in die Map
COMPILED_KEYS = {"model", "hammerid"}
#: Ecken, die so nah an ganzen Units liegen, werden eingerastet (BSP-Ebenen sind float32)
SNAP = 0.02

_FALLBACK = {
    "PLAYER_CLIP": "TOOLS/TOOLSPLAYERCLIP",
    "NPC_CLIP": "TOOLS/TOOLSNPCCLIP",
    "MONSTER_CLIP": "TOOLS/TOOLSNPCCLIP",
    "AREAPORTAL": "TOOLS/TOOLSAREAPORTAL",
    "WATER": "TOOLS/TOOLSNODRAW",
}
DETAIL_COLOR = (255, 200, 60)
#: vbsp benennt Materialien um und packt sie in die BSP: in Reichweite einer env_cubemap als
#: maps/<map>/<name>_x_y_z, für Displacement-Überblendungen <name>_wvt_patch, Wasser <name>_depth_n
_PATCHED = re.compile(r"^MAPS/[^/]+/(?P<name>.+?)(?:_-?\d+_-?\d+_-?\d+|_WVT_PATCH|_DEPTH_-?\d+)$")
#: Größe eines Displacement-Eintrags in der Datei (ddispinfo_t)
DISPINFO_SIZE = 176


def load_bsp(path: str | os.PathLike[str]) -> tuple[MapDocument, BspReport]:
    from srctools.bsp import BSP, BSP_LUMPS

    try:
        bsp = BSP(Path(path))
        brushes = bsp.brushes
        ents = bsp.ents
        models = bsp.bmodels
        no_texture = _untextured_sides(bsp)
        report_disp = len(bsp.lumps[BSP_LUMPS.DISPINFO].data) // DISPINFO_SIZE
    except Exception as exc:  # srctools wirft je nach Schaden verschiedene Fehler
        raise BspError(f"BSP konnte nicht gelesen werden: {exc}") from exc
    doc = MapDocument()
    report = BspReport(displacements=report_disp)
    objs: list[MapObject] = []

    # Welche Brushes gehören zu welchem Brush-Modell (Welt = Modell 0)?
    owner: dict[int, object] = {}
    for ent, model in models.items():
        for leaf in model.node.iter_leafs():
            for b in leaf.brushes:
                owner.setdefault(id(b), ent)

    world_ent = ents.spawn
    entity_ids: dict[int, int] = {}
    detail_id: int | None = None

    for ent in [world_ent, *(e for e in ents.entities if e is not world_ent)]:
        if ent is world_ent:
            doc.world_keyvalues = tuple((k, v) for k, v in ent.items() if k not in COMPILED_KEYS)
            continue
        classname = ent["classname"]
        if not classname:
            continue
        kvs = tuple((k, v) for k, v in ent.items() if k not in COMPILED_KEYS and k != "classname")
        outputs = tuple(Output(o.output, o.target, o.input, o.params, float(o.delay), int(o.times))
                        for o in ent.outputs)
        new = Entity(id=doc.new_id(), classname=classname, keyvalues=kvs, outputs=outputs)
        objs.append(new)
        entity_ids[id(ent)] = new.id
        report.entities += 1

    for index, brush in enumerate(brushes):
        ent = owner.get(id(brush), world_ent)
        parent = None if ent is world_ent else entity_ids.get(id(ent))
        offset = (0.0, 0.0, 0.0)
        if parent is not None:
            offset = _origin(ent["origin"])
        elif _is_detail(brush):
            if detail_id is None:
                detail_id = doc.new_id()
                objs.append(Entity(id=detail_id, classname="func_detail", editor=EditorInfo(color=DETAIL_COLOR)))
                report.entities += 1
            parent = detail_id
        solid = _solid(doc, brush, parent, offset, no_texture.get(index, set()), report)
        if solid is not None:
            objs.append(solid)
            report.solids += 1

    for prop in _static_props(bsp, report):
        objs.append(prop.replace(id=doc.new_id()))
        report.props += 1
        report.entities += 1

    doc._insert(objs)
    if report.displacements:
        report.warnings.append(f"{report.displacements} Displacements sind als flache Brushes übernommen")
    if report.broken:
        report.warnings.append(f"{report.broken} Brushes ließen sich nicht zurückrechnen und fehlen")
    return doc, report


def _untextured_sides(bsp) -> dict[int, set[int]]:
    """Je Brush die Seiten ohne Textur (Index -1 in der Datei). srctools liest -1 als
    letzte Textur der Liste, darum hier direkt aus den Rohdaten."""
    from srctools.bsp import BSP_LUMPS

    raw_sides = [row[1] for row in bsp.lump_layout["BRUSHSIDE"].iter_unpack(bsp.lumps[BSP_LUMPS.BRUSHSIDES].data)]
    out: dict[int, set[int]] = {}
    for index, (first, count, _contents) in enumerate(struct.iter_unpack("<iii", bsp.lumps[BSP_LUMPS.BRUSHES].data)):
        missing = {k for k in range(count) if raw_sides[first + k] < 0}
        if missing:
            out[index] = missing
    return out


def _has(brush, name: str) -> bool:
    flag = getattr(type(brush.contents), name, None)
    return flag is not None and bool(brush.contents & flag)


def _is_detail(brush) -> bool:
    return _has(brush, "DETAIL")


def _origin(raw: str) -> tuple[float, float, float]:
    try:
        x, y, z = (float(c) for c in raw.split())
    except ValueError:
        return (0.0, 0.0, 0.0)
    return (x, y, z)


def _snap(v: float) -> float:
    r = round(v)
    return float(r) if abs(v - r) < SNAP else round(v, 3)


def _solid(doc: MapDocument, brush, parent: int | None, offset, untextured: set[int],
           report: BspReport) -> Solid | None:
    sides = [(s, k in untextured) for k, s in enumerate(brush.sides) if not s.is_bevel_plane]
    if len(sides) < 4:
        report.broken += 1
        return None
    planes = []
    for s, _ in sides:
        n = s.plane.normal
        planes.append(Plane((n.x, n.y, n.z), s.plane.dist + n.x * offset[0] + n.y * offset[1] + n.z * offset[2]))
    polys = face_polygons(planes)
    fallback = next((m for name, m in _FALLBACK.items() if _has(brush, name)), "TOOLS/TOOLSNODRAW")
    faces: list[Face] = []
    for (side, bare), plane, poly in zip(sides, planes, polys):
        if not poly or len(poly) < 3:
            continue  # doppelte oder überflüssige Ebene
        loop = [(_snap(p[0]), _snap(p[1]), _snap(p[2])) for p in poly]
        loop = [p for k, p in enumerate(loop) if p != loop[k - 1]]
        if len(loop) < 3:
            continue
        faces.append(_face(loop, None if bare else side.texinfo, plane, fallback, offset))
    if len(faces) < 4:
        report.broken += 1
        return None
    return Solid(id=doc.new_id(), faces=tuple(faces), parent_id=parent)


def _face(loop, texinfo, plane: Plane, fallback: str, offset) -> Face:
    points = vmf_points_from_loop(loop)
    if texinfo is None:
        u, v = default_tex_axes(plane.normal)
        return Face(points=points, material=fallback, uaxis=u, vaxis=v)
    material = original_material((texinfo.mat or fallback).upper().replace("\\", "/"))
    u = _axis(texinfo.s_off, texinfo.s_shift, offset)
    v = _axis(texinfo.t_off, texinfo.t_shift, offset)
    if u is None or v is None:
        u, v = default_tex_axes(plane.normal)
    lm = texinfo.lightmap_s_off
    lm_len = math.sqrt(lm.x * lm.x + lm.y * lm.y + lm.z * lm.z)
    lightmapscale = max(1, round(1 / lm_len)) if lm_len > 1e-9 else 16
    return Face(points=points, material=material, uaxis=u, vaxis=v, lightmapscale=lightmapscale)


def original_material(name: str) -> str:
    """Name vor dem Umbenennen durch vbsp (siehe _PATCHED), sonst unverändert."""
    hit = _PATCHED.match(name)
    return hit.group("name") if hit else name


def extract_materials(path: str | os.PathLike[str], target: str | os.PathLike[str]) -> int:
    """In die BSP gepackte Materialien und Texturen nach target/materials/... auspacken, damit
    Ansicht und Material-Browser sie finden (und sie beim Kompilieren wieder mitkommen).
    Umbenannte Kopien und Cubemap-Bilder unter materials/maps/ bleiben weg. Gibt die Anzahl
    der ausgepackten Dateien zurück."""
    from srctools.bsp import BSP

    try:
        pak = BSP(Path(path)).pakfile
    except Exception:  # noqa: BLE001 - beschädigter Pakfile-Lump: dann eben ohne
        return 0
    root = Path(target)
    count = 0
    for info in pak.infolist():
        name = info.filename.replace("\\", "/")
        low = name.lower()
        if info.is_dir() or not low.startswith("materials/") or low.startswith("materials/maps/"):
            continue
        if not low.endswith((".vmt", ".vtf")) or ".." in Path(low).parts:
            continue
        out = root / low
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(pak.read(info))
        count += 1
    return count


def _axis(vec, shift: float, offset) -> TexAxis | None:
    """BSP: u = Punkt · s + shift (Maßstab steckt in s). VMF: u = Punkt · achse / scale + offset."""
    length = math.sqrt(vec.x * vec.x + vec.y * vec.y + vec.z * vec.z)
    if length < 1e-9:
        return None
    scale = 1 / length
    # Brush-Entities mit Ursprung: Textur liegt relativ zum Ursprung
    shift -= (vec.x * offset[0] + vec.y * offset[1] + vec.z * offset[2])
    return TexAxis(_r(vec.x * scale), _r(vec.y * scale), _r(vec.z * scale), _r(shift), _r(scale))


def _r(v: float) -> float:
    out = round(v, 6)
    return 0.0 if out == 0 else out


def _static_props(bsp, report: BspReport) -> list[Entity]:
    try:
        props = list(bsp.props)
    except Exception as exc:
        report.warnings.append(f"Statische Props nicht lesbar: {exc}")
        return []
    out = []
    for p in props:
        kvs = [
            ("model", p.model),
            ("origin", f"{_fmt(p.origin.x)} {_fmt(p.origin.y)} {_fmt(p.origin.z)}"),
            ("angles", f"{_fmt(p.angles.pitch)} {_fmt(p.angles.yaw)} {_fmt(p.angles.roll)}"),
            ("skin", str(p.skin)),
            ("solid", str(p.solidity)),
            ("fademindist", _fmt(p.min_fade)),
            ("fademaxdist", _fmt(p.max_fade)),
        ]
        scale = p.scaling
        if isinstance(scale, (int, float)) and scale != 1:
            kvs.append(("modelscale", _fmt(scale)))
        out.append(Entity(id=0, classname="prop_static", keyvalues=tuple(kvs)))
    return out


def _fmt(v: float) -> str:
    v = round(float(v), 3)
    return str(int(v)) if v.is_integer() else str(v)
