"""3D-Skybox mit einem Klick.

Source zeigt hinter den Skybox-Flächen erst die 3D-Skybox, dann den gemalten Himmel. Die 3D-Skybox
ist ein eigener, abgedichteter Raum irgendwo in der Map mit einer `sky_camera`: Was darin steht,
erscheint im Spiel SCALE-mal so groß rund um die Map, als Berge, Häuser oder Dünen am Horizont.
Ein Punkt W der Map entspricht dabei dem Punkt `kamera + W / SCALE` im Skybox-Raum.

Die Rampenschmiede legt den Raum unter (sonst über, sonst neben) die Map, stellt die Kamera so,
dass die Map über der Mitte des Raums liegt, und baut ringsum eine Kulisse. Alles trägt
`extra["skybox3d"]` und ist eine Gruppe; ein neuer Aufruf ersetzt die alte Kulisse. Die
mitwachsende Hülle und „Map umhüllen“ lassen den Raum außen vor.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from ..i18n import tr
from .commands import AddObjects, Command, MacroCommand, RemoveObjects
from .geometry import primitives
from .mathutil import BBox
from .model import EditorInfo, Entity, MapDocument, MapObject, Solid, owner_id

KEY = "skybox3d"
SCALE = 16
#: Kulisse beginnt so weit unter dem Boden der Map (in Map-Units)
GROUND_DROP = 512
#: Abstand des Raums von der Map
GAP = 512
LIMIT = 16000
SKY = "TOOLS/TOOLSSKYBOX"
COLOR = (120, 170, 230)


@dataclass(frozen=True)
class SkyStyle:
    key: str
    name: str
    description: str
    #: Material-Kandidaten aus CS:S/HL2 (erstes vorhandenes gewinnt), dann Wortsuche
    ground: tuple[str, ...]
    ground_words: tuple[tuple[str, ...], ...]
    detail: tuple[str, ...]
    detail_words: tuple[tuple[str, ...], ...]
    #: Ersatzfarben, wenn das Spiel nichts Passendes hat
    ground_color: tuple[int, int, int]
    detail_color: tuple[int, int, int]


STYLES: tuple[SkyStyle, ...] = (
    SkyStyle("berge", tr("Berge"), tr("Ein Ring aus Bergen am Horizont, die Map steht im Tal."),
             ("nature/blendgrassgravel001a", "nature/grassfloor002a", "nature/dirtfloor003a"),
             (("grass",), ("dirt",)),
             ("nature/rockwall004a", "nature/cliffface001a", "nature/rockfloor005a"),
             (("rock",), ("cliff",), ("stone",)),
             (88, 112, 70), (118, 112, 104)),
    SkyStyle("stadt", tr("Stadt"), tr("Hochhäuser ringsum, die Map steht mitten in einer Stadt."),
             ("concrete/concretefloor001a", "concrete/concretefloor028a"),
             (("concrete", "floor"), ("asphalt",)),
             ("concrete/concretewall001a", "building_template/buildingset040a"),
             (("building",), ("concrete", "wall")),
             (70, 72, 78), (120, 124, 132)),
    SkyStyle("wueste", tr("Wüste"), tr("Flache Dünen bis zum Horizont."),
             ("de_dust/sandfloor01", "nature/sandfloor010a"),
             (("sand",),),
             ("de_dust/sandfloor01", "nature/sandfloor010a"),
             (("sand",),),
             (196, 168, 120), (186, 156, 108)),
    SkyStyle("leer", tr("Leer"), tr("Nur Raum und Kamera mit Boden, die Kulisse baust du selbst."),
             ("nature/blendgrassgravel001a",), (("grass",),), (), (), (88, 112, 70), (118, 112, 104)),
)
STYLE_BY_KEY = {s.key: s for s in STYLES}


def is_sky3d(obj: MapObject | None, doc: MapDocument | None = None) -> bool:
    if obj is None:
        return False
    if KEY in obj.extra:
        return True
    if doc is not None:
        owner = owner_id(obj)
        return owner is not None and KEY in getattr(doc.get(owner), "extra", {})
    return False


def skybox_ids(doc: MapDocument) -> list[int]:
    return [o.id for o in doc.objects() if is_sky3d(o, doc)]


def main_bounds(doc: MapDocument) -> BBox | None:
    """Umgebende Box der Map ohne 3D-Skybox."""
    from .model import object_bbox

    return BBox.union(object_bbox(o) for o in doc.objects() if not is_sky3d(o, doc))


def pick_material(library, names: tuple[str, ...], words: tuple[tuple[str, ...], ...]) -> str:
    """Erstes vorhandene Material aus `names`, sonst das erste mit allen `words`; leer wenn keins."""
    if library is None:
        return ""
    from .materials.library import normalize

    for n in names:
        if library.exists(n):
            return normalize(n)
    if not words:
        return ""
    candidates = [n for n in library.names() if not n.startswith(("tools/", "skybox/", "decals/", "overlays/",
                                                                     "dev/", "models/", "effects/"))]
    for ws in words:
        for n in candidates:
            if all(w in n for w in ws):
                return n
    return ""


@dataclass
class Layout:
    """Lage des Skybox-Raums: Innenraum, Kamera und Boden-Oberkante."""
    inner: BBox
    camera: tuple[int, int, int]
    ground_top: int
    #: Halbe Breite des Bereichs, den die Map (verkleinert) überdeckt
    footprint: float


def layout(doc: MapDocument) -> Layout:
    main = main_bounds(doc) or BBox((-1024, -1024, 0), (1024, 1024, 512))
    ext = max(main.maxs[0] - main.mins[0], main.maxs[1] - main.mins[1], 1024)
    footprint = ext / SCALE / 2
    half = int(min(2048, max(768, math.ceil((footprint + 768) / 64) * 64)))
    # Höhen relativ zur Unterkante des Raums. Die Kamera muss im freien Raum stehen: Liegt der
    # Kulissen-Boden über dem Ursprung der Map (d > 0), wird die Bodenplatte dicker.
    d = (main.mins[2] - GROUND_DROP) / SCALE
    cam_rel = 16 - d if d < 0 else 32
    ground_rel = int(math.ceil(cam_rel + d))
    top_rel = (main.maxs[2] - main.mins[2] + GROUND_DROP) / SCALE
    height = int(math.ceil((ground_rel + max(448, top_rel + 128)) / 64) * 64)
    cx = int(round((main.mins[0] + main.maxs[0]) / 2 / 64) * 64)
    cy = int(round((main.mins[1] + main.maxs[1]) / 2 / 64) * 64)
    z0 = int(math.floor((main.mins[2] - GAP - 16 - height) / 64) * 64)
    if z0 - 16 < -LIMIT:
        z0 = int(math.ceil((main.maxs[2] + GAP + 16) / 64) * 64)
        if z0 + height + 16 > LIMIT:
            # Weder darunter noch darüber Platz: daneben
            z0 = int(math.floor(main.mins[2] / 64) * 64)
            cx = int(math.floor((main.mins[0] - GAP - 16 - half) / 64) * 64)
    inner = BBox((cx - half, cy - half, z0), (cx + half, cy + half, z0 + height))
    mcx, mcy = (main.mins[0] + main.maxs[0]) / 2, (main.mins[1] + main.maxs[1]) / 2
    cam = (int(round(cx - mcx / SCALE)), int(round(cy - mcy / SCALE)), int(round(z0 + cam_rel)))
    return Layout(inner, cam, z0 + ground_rel, footprint)


def _ring(rng: random.Random, lay: Layout, count: int, size: tuple[int, int]) -> list[tuple[float, float, float]]:
    """Mittelpunkte und Größe von Kulissen-Teilen rings um die Map, innerhalb des Raums."""
    (x0, y0, _), (x1, y1, _) = lay.inner.mins, lay.inner.maxs
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half = (x1 - x0) / 2
    inner_r = lay.footprint + 64
    out = []
    for i in range(count):
        s = rng.uniform(*size)
        r_max = half - s / 2 - 16
        if r_max <= inner_r:
            continue
        a = 2 * math.pi * (i + rng.uniform(-0.3, 0.3)) / count
        r = rng.uniform(max(inner_r + s / 2, r_max * 0.6), r_max)
        # Quadratischer Raum: Ecken dürfen weiter hinaus
        k = 1 / max(abs(math.cos(a)), abs(math.sin(a)))
        r = min(r * (1 + (k - 1) * rng.random()), half * k - s / 2 - 16)
        out.append((cx + math.cos(a) * r, cy + math.sin(a) * r, s))
    return out


def build_skybox(doc: MapDocument, style: SkyStyle, ground: str, detail: str, fog: dict[str, str] | None = None,
                 seed: int = 7) -> list[MapObject]:
    """Raum, Kamera, Boden und Kulisse. `ground`/`detail` sind die Materialien."""
    from .organize import new_group_id
    from .templates.starter import hull_around

    lay = layout(doc)
    gid = new_group_id(doc)
    info = EditorInfo(color=COLOR, group_id=gid)
    objs: list[MapObject] = []
    for wall in hull_around(doc, lay.inner, material=SKY):
        objs.append(wall.replace(extra={KEY: "raum"}, editor=info))
    (x0, y0, z0), (x1, y1, _) = lay.inner.mins, lay.inner.maxs
    for faces in primitives.block((x0, y0, z0), (x1, y1, lay.ground_top), ground):
        objs.append(Solid(id=doc.new_id(), faces=faces, editor=info, extra={KEY: "boden"}))
    rng = random.Random(seed)
    g = lay.ground_top
    parts: list[tuple] = []
    if style.key == "berge":
        for x, y, s in _ring(rng, lay, 22, (160, 360)):
            h = rng.uniform(0.45, 0.9) * s
            parts += primitives.spike((x - s / 2, y - s / 2, g - 8), (x + s / 2, y + s / 2, g + h), rng.choice((5, 6, 7)),
                                      detail)
    elif style.key == "stadt":
        for x, y, s in _ring(rng, lay, 40, (40, 110)):
            h = rng.choice((1.5, 2.5, 3.5, 5.0)) * s * rng.uniform(0.8, 1.2)
            w = s * rng.uniform(0.6, 1.0)
            parts += primitives.block((x - s / 2, y - w / 2, g), (x + s / 2, y + w / 2, g + h), detail)
    elif style.key == "wueste":
        for x, y, s in _ring(rng, lay, 18, (220, 480)):
            parts += primitives.spike((x - s / 2, y - s / 3, g - 8), (x + s / 2, y + s / 3, g + rng.uniform(24, 72)),
                                      8, detail)
    for faces in parts:
        objs.append(Solid(id=doc.new_id(), faces=faces, editor=info, extra={KEY: "kulisse"}))
    kvs = [("origin", " ".join(str(c) for c in lay.camera)), ("scale", str(SCALE)), ("use_angles", "0")]
    if fog:
        kvs += [("fogenable", "1"), ("fogblend", "0"), ("fogcolor", fog.get("fogcolor", "200 200 200")),
                ("fogcolor2", fog.get("fogcolor2", fog.get("fogcolor", "200 200 200"))),
                ("fogstart", fog.get("fogstart", "2048")), ("fogend", fog.get("fogend", "16384")),
                ("fogdir", "1 0 0")]
    else:
        kvs.append(("fogenable", "0"))
    objs.append(Entity(id=doc.new_id(), classname="sky_camera", keyvalues=tuple(kvs), editor=info,
                       extra={KEY: "kamera"}))
    return objs


def map_fog(doc: MapDocument) -> dict[str, str] | None:
    """Nebel der Map (env_fog_controller), damit die Kulisse im selben Dunst steht."""
    for e in doc.entities():
        if e.classname.lower() == "env_fog_controller" and e.get("fogenable", "0") not in ("", "0"):
            return {k: e.get(k) for k in ("fogcolor", "fogcolor2", "fogstart", "fogend") if e.get(k)}
    return None


def skybox_command(doc: MapDocument, style: SkyStyle, ground: str, detail: str) -> tuple[Command, list[MapObject]]:
    """Alte 3D-Skybox ersetzen (ein Undo-Schritt). Die Lage richtet sich nach der Map ohne sie."""
    old = skybox_ids(doc)
    objs = build_skybox(doc, style, ground, detail, map_fog(doc))
    cmds: list[Command] = []
    if old:
        cmds.append(RemoveObjects(old))
    cmds.append(AddObjects(objs))
    return MacroCommand(cmds, f"3D-Skybox „{style.name}“"), objs


def remove_command(doc: MapDocument) -> Command | None:
    old = skybox_ids(doc)
    return RemoveObjects(old, "3D-Skybox entfernen") if old else None


__all__ = ["KEY", "SCALE", "STYLES", "STYLE_BY_KEY", "SkyStyle", "build_skybox", "is_sky3d", "layout", "main_bounds",
           "map_fog", "pick_material", "remove_command", "skybox_command", "skybox_ids"]
