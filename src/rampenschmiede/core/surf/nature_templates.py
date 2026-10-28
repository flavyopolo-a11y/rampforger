"""Natur-Vorlagen: Wasser, Lava und Kill-Zonen für Gruben und Abgründe.

Wasser muss in Source ein Welt-Brush sein (in `func_detail` oder Brush-Entities zeigt vbsp es
nicht als Wasser), mit dem Wasser-Material nur oben und Nodraw ringsum. Deshalb sind Wasser und
Lava Welt-Vorlagen wie das Gelände: Regler vor dem Einfügen, danach normale Brushes. Ihr Trigger
(Tod im Wasser, Lava) kommt als eigene Brush-Entity dazu; alles zusammen ist eine Gruppe.

Die Kill-Zone ist ein normaler Baustein (Regler bleiben): ein Trigger, der tötet oder zurück zum
Start teleportiert. Man legt sie unten in Gruben und Abgründe.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .catalog import Param, Placement, Template, _add, _box_points, build_trigger_box
from .hull import IPoint, hull_faces
from .sweep import SweepPiece

GROUP = "Natur"
NODRAW = "TOOLS/TOOLSNODRAW"
#: HL2-Wasser, in CS:S und Momentum vorhanden; fehlt es, sucht der Editor ein anderes Wasser
DEFAULT_WATER = "NATURE/WATER_CANALS_WATER2"
#: Platzhalter: Der Editor erzeugt beim Einfügen eine eigene, leuchtende Lava-Textur
DEFAULT_LAVA = "@lava"
KILL_DAMAGE = "100000"
#: So hoch reicht der Lava-Trigger über die Oberfläche (wer darauf steht, berührt ihn)
LAVA_REACH = 16


@dataclass
class TopShape:
    """Konvexe Form mit eigenem Material oben (waagrechte Oberseite) und einem für den Rest."""

    points: list[IPoint]
    top: str
    rest: str

    def build(self) -> list[SweepPiece]:
        def material(n, _loop) -> str:
            return self.top if n[2] / math.sqrt(n[0] ** 2 + n[1] ** 2 + n[2] ** 2) >= 0.999 else self.rest
        faces = hull_faces(self.points, material)
        return [SweepPiece(faces, 0, 0)] if faces else []


def _box(v: dict, at: Placement, z0: float, height: float) -> list[IPoint]:
    a = math.radians(at.yaw)
    cx = at.x + math.cos(a) * v["laenge"] / 2
    cy = at.y + math.sin(a) * v["laenge"] / 2
    return _box_points(cx, cy, z0, v["laenge"], v["breite"], height, at.yaw)


def _hurt() -> tuple[tuple[str, str], ...]:
    return (("spawnflags", "1"), ("damage", KILL_DAMAGE), ("damagecap", KILL_DAMAGE), ("damagetype", "0"),
            ("StartDisabled", "0"))


def find_water(library) -> str:
    """Wasser-Material: das Standard-Wasser, sonst das erste Material mit Wasser-Shader im Spiel."""
    if library is None or library.exists(DEFAULT_WATER):
        return DEFAULT_WATER
    skip = ("decals/", "overlays/", "models/", "effects/", "particle/", "sprites/")
    candidates = [n for n in library.names() if "water" in n.lower() and not n.lower().startswith(skip)]
    for name in candidates[:200]:
        info = library.material(name)
        if info is not None and info.shader.lower() == "water":
            return name.upper()
    return DEFAULT_WATER


# ---- Wasser ----------------------------------------------------------------------------

def build_water(v: dict, at: Placement, _m) -> list:
    return [TopShape(_box(v, at, at.z, v["tiefe"]), str(v["mat_wasser"]).upper(), NODRAW)]


def water_triggers(v: dict, at: Placement) -> list[tuple[str, tuple[tuple[str, str], ...], list[IPoint]]]:
    if not v["todeswasser"]:
        return []
    return [("trigger_hurt", _hurt(), _box(v, at, at.z, v["tiefe"]))]


_add(Template("wasser", "Wasser", GROUP,
              "Wasserfläche mit echtem Source-Wasser (Spiegelung, Schwimmen). Unterkante auf den Boden legen. "
              "Mit „Tod im Wasser“ wird es zur Todesfalle.",
              (Param("laenge", "Länge", 1024, 32, 16384, 16, "u"), Param("breite", "Breite", 1024, 32, 16384, 16, "u"),
               Param("tiefe", "Tiefe", 128, 16, 4096, 16, "u"),
               Param("mat_wasser", "Wasser-Material", DEFAULT_WATER, hint="Ein Material mit Wasser-Shader"),
               Param("todeswasser", "Tod im Wasser", False, hint="Wer hineinfällt, stirbt (trigger_hurt)")),
              build_water, check_angles=False, world=True, triggers=water_triggers))


# ---- Lava ------------------------------------------------------------------------------

def build_lava(v: dict, at: Placement, _m) -> list:
    mat = str(v["mat_lava"]).upper()
    return [TopShape(_box(v, at, at.z, v["tiefe"]), mat, mat)]


def lava_triggers(v: dict, at: Placement) -> list[tuple[str, tuple[tuple[str, str], ...], list[IPoint]]]:
    return [("trigger_hurt", _hurt(), _box(v, at, at.z + v["tiefe"] - LAVA_REACH, 2 * LAVA_REACH))]


_add(Template("lava", "Lava", GROUP, "Glühender Boden: Wer ihn berührt, stirbt.",
              (Param("laenge", "Länge", 1024, 32, 16384, 16, "u"), Param("breite", "Breite", 1024, 32, 16384, 16, "u"),
               Param("tiefe", "Dicke", 32, 16, 1024, 16, "u"),
               Param("mat_lava", "Material", DEFAULT_LAVA, hint="Standard: eigene leuchtende Lava-Textur")),
              build_lava, check_angles=False, world=True, triggers=lava_triggers))


# ---- Kill-Zone -------------------------------------------------------------------------

KILL_CHOICES = (("tod", "Tod"), ("zurueck", "Zurück zum Start (Teleport)"))


def kill_entity(v: dict, at: Placement) -> tuple[str, tuple[tuple[str, str], ...]]:
    if v["art"] == "zurueck":
        return "trigger_teleport", (("spawnflags", "1"), ("target", v["ziel"]), ("StartDisabled", "0"))
    return "trigger_hurt", _hurt()


_add(Template("killzone", "Kill-Zone (Grube)", GROUP,
              "Unten in Gruben und Abgründe legen: Wer hineinfällt, stirbt oder landet wieder am Start. "
              "Für ein Loch im Boden erst mit dem Werkzeug „Loch“ den Boden öffnen.",
              (Param("laenge", "Länge", 1024, 32, 16384, 16, "u"), Param("breite", "Breite", 1024, 32, 16384, 16, "u"),
               Param("hoehe", "Höhe", 64, 16, 4096, 16, "u"),
               Param("art", "Was passiert", "tod", choices=KILL_CHOICES),
               Param("ziel", "Zielname", "zurueck", only_if=("art", "zurueck"),
                     hint="targetname des info_teleport_destination; wird beim Einfügen am Start angelegt")),
              build_trigger_box, check_angles=False, entity=kill_entity))


__all__ = ["find_water", "DEFAULT_LAVA", "DEFAULT_WATER", "GROUP", "TopShape"]
