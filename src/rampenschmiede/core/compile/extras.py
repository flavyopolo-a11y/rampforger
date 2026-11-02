"""Entities, die beim Kompilieren automatisch dazukommen, wenn die Map sie nicht selbst hat.

- `shadow_control`: Die dynamischen Schatten von Spielern und Props fallen sonst in eine feste
  Standardrichtung, unabhängig von der Sonne. Er bekommt die Richtung der Sonne.
- `env_tonemap_controller` mit `logic_auto`: Nur bei einem HDR-Build (vrad `-both` oder `-hdr`).
  Ohne ihn regelt CS:S die Belichtung so stark nach, dass helle Surf-Himmel überstrahlen und der
  Bloom „pumpt“. Gesetzt werden ruhige, enge Werte.

Die Map selbst bleibt unverändert, die Entities stehen nur im VMF für die Compiler. Wer eigene
Werte will, setzt die Entity selbst in die Map; dann kommt nichts dazu.
"""
from __future__ import annotations

import math

from ...i18n import tr
from ..lights import SUN_CLASS, light_direction
from ..model import Entity, MapDocument, Output
from .plan import split_args

TONEMAP_NAME = "rs_tonemap"
#: Belichtung und Bloom für HDR (eng, damit helle Himmel nicht überstrahlen)
TONEMAP_INPUTS = (("SetAutoExposureMin", "0.8"), ("SetAutoExposureMax", "1.2"), ("SetBloomScale", "0.2"))
SHADOW_COLOR = "80 80 80"
SHADOW_DISTANCE = "75"


def is_hdr_build(vrad_args: str) -> bool:
    args = {a.lower() for a in split_args(vrad_args)}
    return "-both" in args or "-hdr" in args


def shadow_angles(sun: Entity) -> str:
    """`angles` für shadow_control: Richtung, in die die Schatten fallen (Pitch positiv = nach unten)."""
    x, y, z = light_direction(sun)
    pitch = math.degrees(math.atan2(-z, math.hypot(x, y)))
    yaw = math.degrees(math.atan2(y, x)) % 360.0
    return f"{round(pitch)} {round(yaw)} 0"


def _origin(sun: Entity | None, offset: int) -> str:
    o = sun.origin if sun is not None and sun.origin is not None else (0.0, 0.0, 0.0)
    return f"{round(o[0]) + offset} {round(o[1])} {round(o[2])}"


def build_extras(doc: MapDocument, vrad_args: str = "", run_vrad: bool = True) -> tuple[MapDocument, list[str]]:
    """Kopie von `doc` mit den fehlenden Entities (oder `doc` selbst, wenn nichts fehlt) und
    eine Zeile je ergänzter Entity für das Log."""
    classes = {e.classname.lower() for e in doc.entities()}
    sun = next((e for e in doc.entities() if e.classname.lower() == SUN_CLASS), None)
    add: list[tuple[str, tuple[tuple[str, str], ...], tuple[Output, ...]]] = []
    notes: list[str] = []
    if sun is not None and "shadow_control" not in classes:
        add.append(("shadow_control", (("origin", _origin(sun, 32)), ("angles", shadow_angles(sun)),
                                       ("color", SHADOW_COLOR), ("distance", SHADOW_DISTANCE),
                                       ("disableallshadows", "0")), ()))
        notes.append(tr("shadow_control ergänzt: Schatten fallen in Richtung der Sonne"))
    if run_vrad and is_hdr_build(vrad_args) and "env_tonemap_controller" not in classes:
        add.append(("env_tonemap_controller", (("targetname", TONEMAP_NAME), ("origin", _origin(sun, 64))), ()))
        add.append(("logic_auto", (("origin", _origin(sun, 96)), ("spawnflags", "1")), tuple(
            Output("OnMapSpawn", TONEMAP_NAME, name, value) for name, value in TONEMAP_INPUTS)))
        notes.append(tr("env_tonemap_controller ergänzt: ruhige HDR-Belichtung (0,8 bis 1,2, Bloom 0,2)"))
    if not add:
        return doc, []
    out = doc.snapshot()
    out.extra = dict(doc.extra)
    out.editor = doc.editor
    out._insert([Entity(id=out.new_id(), classname=cls, keyvalues=kvs, outputs=outputs)
                 for cls, kvs, outputs in add])
    return out, notes


__all__ = ["build_extras", "is_hdr_build", "shadow_angles"]
