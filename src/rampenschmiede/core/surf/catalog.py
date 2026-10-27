"""Rampen-Katalog: jede Rampenart als Vorlage mit Reglern.

Eine Vorlage beschreibt ihre Regler (`Param`) und baut daraus Formen (Querschnitte, die
entlang eines Weges gezogen werden, oder einzelne Hüllen). `generate` macht daraus fertige
Brush-Seiten mit Materialien: Surf-Flächen, Seiten und unsichtbare Flächen (Nodraw).

Alle Rampen werden direkt an ihrer Endposition berechnet und erst dann gerundet, damit
auch gedrehte Rampen ganzzahlige Ecken und exakte Nähte haben.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..model.objects import Face
from .hull import IPoint, hull_faces
from .sweep import (
    Joint,
    Materials,
    Profile,
    Sweep,
    SweepPiece,
    arc_joints,
    concat,
    face_material,
    straight_joints,
    turn_after,
)

#: Ab diesem Winkel (zur Waagrechten) rutscht man, darunter kann man stehen
SURF_MIN_ANGLE = 45.0
#: Ab hier wird es unangenehm steil
SURF_STEEP_ANGLE = 65.0


# ---- Regler ------------------------------------------------------------------------

@dataclass(frozen=True)
class Param:
    key: str
    label: str
    default: Any
    minimum: float = 0
    maximum: float = 0
    step: float = 1
    unit: str = ""
    #: Auswahl: (Wert, Anzeigename)
    choices: tuple[tuple[str, str], ...] = ()
    hint: str = ""
    #: Nur zeigen, wenn ein anderer Regler diesen Wert hat: (Schlüssel, Wert)
    only_if: tuple[str, str] | None = None

    def applies(self, values: dict) -> bool:
        return self.only_if is None or values.get(self.only_if[0]) == self.only_if[1]

    @property
    def kind(self) -> str:
        if isinstance(self.default, bool):
            return "bool"
        if self.choices:
            return "choice"
        if isinstance(self.default, str):
            return "text"
        if isinstance(self.default, int) and float(self.step).is_integer():
            return "int"
        return "float"

    def clean(self, value: Any) -> Any:
        """Wert in den erlaubten Bereich bringen; Unsinn wird zum Standardwert."""
        kind = self.kind
        if kind == "bool":
            return bool(value)
        if kind == "choice":
            return value if value in {c for c, _ in self.choices} else self.default
        if kind == "text":
            text = str(value).strip() if value is not None else ""
            return text or self.default
        try:
            v = float(value)
        except (TypeError, ValueError):
            return self.default
        if math.isnan(v):
            return self.default
        v = min(max(v, self.minimum), self.maximum)
        return int(round(v)) if kind == "int" else v


@dataclass(frozen=True)
class Placement:
    """Ankerpunkt (Anfang der Rampe, Mitte unten) und Richtung in Grad."""

    x: float = 0
    y: float = 0
    z: float = 0
    yaw: float = 0


class Shape(Protocol):
    def build(self) -> list[SweepPiece]: ...


@dataclass
class HullShape:
    """Eine einzelne konvexe Form aus Punkten (z. B. Pyramide)."""

    points: list[IPoint]
    materials: Materials = field(default_factory=Materials)

    def build(self) -> list[SweepPiece]:
        faces = hull_faces(self.points, lambda n, _loop: face_material(n, self.materials))
        return [SweepPiece(faces, 0, 0)] if faces else []


Builder = Callable[[dict, Placement, Materials], list[Shape]]


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    category: str
    description: str
    params: tuple[Param, ...]
    builder: Builder
    #: Abweichende Standardwerte, damit eine Vorlage eine Variante einer anderen sein kann
    overrides: tuple[tuple[str, Any], ...] = ()
    #: Surf-Winkel prüfen (bei Rinnen und Rohren ist der flache Boden gewollt)
    check_angles: bool = True
    #: Eigene Wurzel-Entity statt func_brush/func_detail: (Werte, Platzierung) -> (Klasse, Keyvalues).
    #: Solche Bausteine haben keine Playerclip-Kollision (Trigger, Bhop-Blöcke).
    entity: Callable[[dict, Placement], tuple[str, tuple[tuple[str, str], ...]]] | None = None

    def param(self, key: str) -> Param | None:
        return next((p for p in self.params if p.key == key), None)

    def values(self, given: dict | None = None) -> dict:
        given = given or {}
        base = dict(self.overrides)
        out = {}
        for p in self.params:
            out[p.key] = p.clean(given.get(p.key, base.get(p.key, p.default)))
        return out


# ---- Querschnitte ------------------------------------------------------------------

PROFILE_CHOICES = (("voll", "Voll (beidseitig)"), ("halb", "Halb (eine Seite)"),
                   ("invertiert", "Invertiert (Unterseite)"), ("trapez", "Trapez (flache Kante)"))

PROFILE_PARAMS = (
    Param("profil", "Querschnitt", "voll", choices=PROFILE_CHOICES),
    Param("breite", "Breite", 640, 64, 8192, 16, "u"),
    Param("winkel", "Surf-Winkel", 50.0, 20, 80, 0.5, "°", hint="Ab 45° surfbar, über 65° sehr steil"),
    Param("lippe", "Lippe", 16, 0, 512, 8, "u", hint="Senkrechter Rand unten an der Rampe"),
    Param("oben", "Obere Breite", 256, 16, 4096, 16, "u", only_if=("profil", "trapez")),
    Param("spiegeln", "Seite tauschen", False, only_if=("profil", "halb")),
)

SURF_MATERIAL = Param("mat_surf", "Material Surf-Fläche", "DEV/DEV_MEASUREGENERIC01B",
                      hint="Material der surfbaren Flächen")
SIDE_MATERIAL = Param("mat_seite", "Material Seiten", "DEV/DEV_MEASUREGENERIC01",
                      hint="Material von Lippe, Enden und flachen Kanten")

MATERIAL_PARAMS = (
    SURF_MATERIAL,
    SIDE_MATERIAL,
    Param("unterseite_nodraw", "Unterseite unsichtbar (Nodraw)", True),
    Param("kollision", "Kollision", "clip", choices=(
        ("clip", "Playerclip + func_detail (empfohlen)"), ("detail", "Nur func_detail"))),
    Param("textur", "Textur", "einpassen", choices=(
        ("einpassen", "Quer über die Rampe einpassen"), ("raster", "Welt-Raster (wie Hammer)")),
          hint="Einpassen: Die Textur geht quer genau einmal über die Surf-Fläche und läuft längs weiter"),
    Param("textur_groesse", "Textur-Größe", 100, 10, 1000, 5, "%", only_if=("textur", "einpassen"),
          hint="100 % = quer genau einmal. In der 3D-Ansicht: Seiten-Werkzeug, Alt+Ziehen"),
    Param("textur_laengs", "Textur längs", 0, -8192, 8192, 8, "u", only_if=("textur", "einpassen"),
          hint="Verschiebt die Textur entlang der Rampe. In der 3D-Ansicht: Seiten-Werkzeug, Ziehen"),
    Param("textur_quer", "Textur quer", 0, -8192, 8192, 8, "u", only_if=("textur", "einpassen"),
          hint="Verschiebt die Textur quer zur Rampe"),
)


def ramp_height(v: dict) -> float:
    """Höhe des Querschnitts aus Breite, Winkel und Lippe."""
    t = math.tan(math.radians(v["winkel"]))
    w = v["breite"]
    kind = v["profil"]
    if kind == "halb":
        run = w
    elif kind == "trapez":
        run = max(0.0, (w - min(v["oben"], w - 16)) / 2)
    else:
        run = w / 2
    return v["lippe"] + t * run


def profile_from(v: dict) -> Profile:
    w = v["breite"] / 2
    lip = v["lippe"]
    h = ramp_height(v)
    kind = v["profil"]
    if kind == "halb":
        pts = [(-w, 0), (w, 0), (w, h), (-w, lip)]
        if v["spiegeln"]:
            pts = [(-o, z) for o, z in pts]
    elif kind == "invertiert":
        pts = [(-w, h), (w, h), (w, h - lip), (0, 0), (-w, h - lip)]
    elif kind == "trapez":
        top = min(v["oben"], v["breite"] - 16) / 2
        pts = [(-w, 0), (w, 0), (w, lip), (top, h), (-top, h), (-w, lip)]
    else:
        pts = [(-w, 0), (w, 0), (w, lip), (0, h), (-w, lip)]
    return [pts]


def materials_from(v: dict) -> Materials:
    return Materials(surf=str(v.get("mat_surf", SURF_MATERIAL.default)).upper(),
                     side=str(v.get("mat_seite", SIDE_MATERIAL.default)).upper(),
                     hide_bottom=bool(v.get("unterseite_nodraw", True)),
                     fit_surf=v.get("textur", "einpassen") == "einpassen",
                     tex_size=float(v.get("textur_groesse", 100)) / 100,
                     tex_shift=(float(v.get("textur_laengs", 0)), float(v.get("textur_quer", 0))))


# ---- Wege ---------------------------------------------------------------------------

def _sweep(joints: list[Joint], v: dict, m: Materials, profile: Profile | None = None, **kw: Any) -> Sweep:
    return Sweep(joints, profile or profile_from(v), m, **kw)


def _arc(v: dict, at: Placement, angle: float, dz: float = 0.0) -> list[Joint]:
    return arc_joints(v["radius"], angle, segment_length=1e9, max_step=v["schritt"],
                      x=at.x, y=at.y, z=at.z, yaw=at.yaw, dz=dz)


def _sign(v: dict) -> int:
    return 1 if v.get("richtung", "links") == "links" else -1


def build_straight(v: dict, at: Placement, m: Materials) -> list[Shape]:
    joints = straight_joints(v["laenge"], v.get("segmente", 1), at.x, at.y, at.z, at.yaw, v["gefaelle"])
    return [_sweep(joints, v, m, lattice=True)]


def build_curve(v: dict, at: Placement, m: Materials) -> list[Shape]:
    return [_sweep(_arc(v, at, _sign(v) * v["bogen"], v["gefaelle"]), v, m)]


def build_s_curve(v: dict, at: Placement, m: Materials) -> list[Shape]:
    total = v["gefaelle"]
    first = _arc(v, at, _sign(v) * v["bogen"], total / 2)
    x, y, z, yaw = turn_after(first)
    parts = [first]
    if v["mitte"] > 0:
        mid = straight_joints(v["mitte"], 1, x, y, z, yaw)
        parts.append(mid)
        x, y, z, yaw = turn_after(mid)
    second = _arc(v, Placement(x, y, z, yaw), -_sign(v) * v["bogen"], total / 2)
    parts.append(second)
    return [_sweep(concat(*parts), v, m)]


def build_banana(v: dict, at: Placement, m: Materials) -> list[Shape]:
    """Gerade Rampe, deren Höhe in einem Bogen verläuft (positiv = Buckel, negativ = Mulde)."""
    joints = straight_joints(v["laenge"], v["segmente"], at.x, at.y, at.z, at.yaw, v["gefaelle"])
    n = len(joints) - 1
    for i, j in enumerate(joints):
        t = i / n
        j.z += v["bogenhoehe"] * 4 * t * (1 - t)
    return [_sweep(joints, v, m, lattice=True)]


def build_wave(v: dict, at: Placement, m: Materials) -> list[Shape]:
    segments = max(2, int(v["wellen"] * v["segmente"]))
    joints = straight_joints(v["laenge"], segments, at.x, at.y, at.z, at.yaw, v["gefaelle"])
    for i, j in enumerate(joints):
        j.z += v["amplitude"] * math.sin(2 * math.pi * v["wellen"] * i / segments)
    return [_sweep(joints, v, m, lattice=True)]


def pipe_profile(v: dict) -> Profile:
    """Halfpipe bzw. Rohr: Ring aus konvexen Vierecken um die Mitte (0, r + dicke)."""
    r, t = v["radius"], v["dicke"]
    arc = v["bogen"]
    parts = v["teile"]
    cz = r + t
    start = 270 - arc / 2  # unten in der Mitte beginnt die Rinne
    out: Profile = []
    for i in range(parts):
        a0 = math.radians(start + arc * i / parts)
        a1 = math.radians(start + arc * (i + 1) / parts)
        out.append([
            (r * math.cos(a0), cz + r * math.sin(a0)), ((r + t) * math.cos(a0), cz + (r + t) * math.sin(a0)),
            ((r + t) * math.cos(a1), cz + (r + t) * math.sin(a1)), (r * math.cos(a1), cz + r * math.sin(a1)),
        ])
    return out


def build_pipe(v: dict, at: Placement, m: Materials) -> list[Shape]:
    joints = straight_joints(v["laenge"], 1, at.x, at.y, at.z, at.yaw, v["gefaelle"])
    return [Sweep(joints, pipe_profile(v), m, lattice=True)]


def build_slide(v: dict, at: Placement, m: Materials) -> list[Shape]:
    """V-Rinne: zwei Keile, deren Schrägen zur Mitte hin abfallen."""
    w = v["breite"] / 2
    g = min(v["boden"], v["breite"] - 32) / 2
    h = v["lippe"] + math.tan(math.radians(v["winkel"])) * (w - g)
    lip = v["lippe"]
    profile: Profile = [[(-w, 0), (-g, 0), (-g, lip), (-w, h)], [(g, 0), (w, 0), (w, h), (g, lip)]]
    if g > 0:
        profile.append([(-g, 0), (g, 0), (g, lip), (-g, lip)])
    joints = straight_joints(v["laenge"], 1, at.x, at.y, at.z, at.yaw, v["gefaelle"])
    return [Sweep(joints, profile, m, lattice=True)]


def build_pyramid(v: dict, at: Placement, m: Materials) -> list[Shape]:
    n = v["seiten"]
    apothem = v["breite"] / 2
    radius = apothem / math.cos(math.pi / n)
    h = v["lippe"] + math.tan(math.radians(v["winkel"])) * apothem
    pts: list[IPoint] = []
    for k in range(n):
        a = math.radians(at.yaw) + math.pi / n + 2 * math.pi * k / n
        px, py = at.x + radius * math.cos(a), at.y + radius * math.sin(a)
        for z in ({0, v["lippe"]}):
            pts.append((_r(px), _r(py), _r(at.z + z)))
    pts.append((_r(at.x), _r(at.y), _r(at.z + h)))
    return [HullShape(pts, m)]


def build_fork(v: dict, at: Placement, m: Materials) -> list[Shape]:
    trunk = straight_joints(v["laenge"], 1, at.x, at.y, at.z, at.yaw)
    x, y, z, yaw = turn_after(trunk)
    branch_at = Placement(x, y, z, yaw)
    left = _arc(v, branch_at, v["bogen"], v["gefaelle"])
    right = _arc(v, branch_at, -v["bogen"], v["gefaelle"])
    return [_sweep(trunk, v, m, open_end=False), _sweep(left, v, m, open_start=False),
            _sweep(right, v, m, open_start=False)]


def build_transfer(v: dict, at: Placement, m: Materials) -> list[Shape]:
    """Zwei parallele Rampen nebeneinander, die zweite versetzt und tiefer."""
    a = math.radians(at.yaw)
    side = v["breite"] + v["abstand"]
    sign = _sign(v)
    fx, fy = math.cos(a), math.sin(a)
    lx, ly = -fy * sign, fx * sign
    first = straight_joints(v["laenge"], 1, at.x, at.y, at.z, at.yaw, v["gefaelle"])
    ox = at.x + lx * side + fx * v["versatz"]
    oy = at.y + ly * side + fy * v["versatz"]
    second = straight_joints(v["laenge"], 1, ox, oy, at.z - v["hoehe"], at.yaw, v["gefaelle"])
    return [_sweep(first, v, m, lattice=True), _sweep(second, v, m, lattice=True)]


def _r(v: float) -> int:
    return int(math.floor(v + 0.5))


# ---- Katalog ------------------------------------------------------------------------

LENGTH = Param("laenge", "Länge", 1024, 64, 32768, 16, "u")
DROP = Param("gefaelle", "Höhenänderung", 0, -16384, 16384, 16, "u", hint="Negativ = abwärts")
RADIUS = Param("radius", "Radius (Mitte)", 1024, 128, 16384, 16, "u")
BEND = Param("bogen", "Bogenwinkel", 90.0, 5, 1080, 5, "°")
STEP = Param("schritt", "Grad pro Segment", 2.5, 1, 5, 0.5, "°",
             hint="Kleiner = glatter. Mehr als 5° pro Segment führt zu spürbaren Kanten")
DIRECTION = Param("richtung", "Richtung", "links", choices=(("links", "Links"), ("rechts", "Rechts")))

CATALOG: dict[str, Template] = {}


def _add(t: Template) -> None:
    CATALOG[t.key] = t


_add(Template("gerade", "Gerade Rampe", "Rampen", "Klassische Surf-Rampe, beidseitig surfbar.",
              (LENGTH, DROP, *PROFILE_PARAMS, *MATERIAL_PARAMS), build_straight))
_add(Template("halb", "Halbe Rampe", "Rampen", "Eine Surf-Seite, Rückwand senkrecht. Gut an Wänden.",
              (LENGTH, DROP, *PROFILE_PARAMS, *MATERIAL_PARAMS), build_straight, (("profil", "halb"), ("breite", 320))))
_add(Template("invertiert", "Invertierte Rampe", "Rampen", "Kopfüber: Surf-Flächen zeigen nach unten.",
              (LENGTH, DROP, *PROFILE_PARAMS, *MATERIAL_PARAMS), build_straight, (("profil", "invertiert"),)))
_add(Template("trapez", "Trapez-Rampe", "Rampen", "Rampe mit flacher Oberkante zum Landen.",
              (LENGTH, DROP, *PROFILE_PARAMS, *MATERIAL_PARAMS), build_straight, (("profil", "trapez"),)))
_add(Template("ski", "Ski-Rampe", "Rampen", "Lange Rampe mit Gefälle für Tempo.",
              (LENGTH, DROP, *PROFILE_PARAMS, *MATERIAL_PARAMS), build_straight,
              (("laenge", 4096), ("gefaelle", -1024))))
_add(Template("pyramide", "Pyramide", "Rampen", "Surf-Flächen in alle Richtungen.",
              (Param("seiten", "Seiten", 4, 3, 8), Param("breite", "Breite", 640, 64, 8192, 16, "u"),
               Param("winkel", "Surf-Winkel", 50.0, 20, 80, 0.5, "°"), Param("lippe", "Lippe", 32, 0, 512, 8, "u"),
               *MATERIAL_PARAMS), build_pyramid))
_add(Template("kurve", "Kurve", "Kurven", "Gebogene Rampe mit gleichmäßigen Segmenten.",
              (RADIUS, BEND, DIRECTION, STEP, DROP, *PROFILE_PARAMS, *MATERIAL_PARAMS), build_curve))
_add(Template("kurve_halb", "Halbe Kurve", "Kurven", "Gebogene Rampe mit einer Surf-Seite.",
              (RADIUS, BEND, DIRECTION, STEP, DROP, *PROFILE_PARAMS, *MATERIAL_PARAMS), build_curve,
              (("profil", "halb"), ("breite", 320))))
_add(Template("spirale", "Spirale", "Kurven", "Kurve über mehrere Umdrehungen mit Gefälle.",
              (RADIUS, BEND, DIRECTION, STEP, DROP, *PROFILE_PARAMS, *MATERIAL_PARAMS), build_curve,
              (("bogen", 360.0), ("gefaelle", -1024), ("radius", 1280))))
_add(Template("s_kurve", "S-Kurve", "Kurven", "Zwei Bögen in entgegengesetzte Richtungen.",
              (RADIUS, BEND, DIRECTION, STEP, Param("mitte", "Gerades Mittelstück", 0, 0, 8192, 16, "u"),
               DROP, *PROFILE_PARAMS, *MATERIAL_PARAMS), build_s_curve, (("bogen", 45.0),)))
_add(Template("banane", "Banane", "Kurven", "Gerade Rampe, deren Höhe sich wölbt.",
              (LENGTH, Param("bogenhoehe", "Wölbung", -256, -4096, 4096, 16, "u", hint="Negativ = Mulde"),
               Param("segmente", "Segmente", 16, 2, 96), DROP, *PROFILE_PARAMS, *MATERIAL_PARAMS), build_banana,
              (("laenge", 2048),)))
_add(Template("welle", "Welle", "Kurven", "Rampe, die auf und ab läuft.",
              (LENGTH, Param("amplitude", "Wellenhöhe", 128, 0, 2048, 16, "u"), Param("wellen", "Wellen", 2, 1, 16),
               Param("segmente", "Segmente pro Welle", 12, 4, 48), DROP, *PROFILE_PARAMS, *MATERIAL_PARAMS),
              build_wave, (("laenge", 3072),)))
_add(Template("halfpipe", "Halfpipe", "Spezial", "Halbrunde Rinne aus Segmenten.",
              (LENGTH, Param("radius", "Innenradius", 512, 64, 8192, 16, "u"), Param("dicke", "Wandstärke", 32, 8, 256, 8, "u"),
               Param("bogen", "Bogen", 180.0, 60, 330, 5, "°"), Param("teile", "Teile", 12, 3, 48), DROP,
               *MATERIAL_PARAMS), build_pipe, check_angles=False))
_add(Template("rohr", "Rohr", "Spezial", "Fast geschlossene Röhre mit Spalt oben.",
              (LENGTH, Param("radius", "Innenradius", 512, 64, 8192, 16, "u"), Param("dicke", "Wandstärke", 32, 8, 256, 8, "u"),
               Param("bogen", "Bogen", 300.0, 60, 330, 5, "°"), Param("teile", "Teile", 20, 3, 48), DROP,
               *MATERIAL_PARAMS), build_pipe, check_angles=False))
_add(Template("slide", "Slide", "Spezial", "V-Rinne, deren Flächen zur Mitte hin abfallen.",
              (LENGTH, Param("breite", "Breite", 768, 64, 8192, 16, "u"), Param("winkel", "Surf-Winkel", 50.0, 20, 80, 0.5, "°"),
               Param("boden", "Flacher Boden", 0, 0, 4096, 16, "u"), Param("lippe", "Lippe", 16, 0, 512, 8, "u"), DROP,
               *MATERIAL_PARAMS), build_slide, (("gefaelle", -256),)))
_add(Template("gabelung", "Gabelung", "Spezial", "Gerades Stück, das sich in zwei Kurven teilt.",
              (LENGTH, RADIUS, BEND, STEP, DROP, *PROFILE_PARAMS, *MATERIAL_PARAMS), build_fork,
              (("laenge", 512), ("bogen", 45.0))))
_add(Template("transfer", "Transfer", "Spezial", "Zwei Rampen nebeneinander zum Hinüberspringen.",
              (LENGTH, Param("abstand", "Lücke", 256, 0, 8192, 16, "u"), Param("hoehe", "Zweite tiefer um", 128, -4096, 4096, 16, "u"),
               Param("versatz", "Zweite nach vorne", 256, -16384, 16384, 16, "u"), DIRECTION, DROP,
               *PROFILE_PARAMS, *MATERIAL_PARAMS), build_transfer))


# ---- Bhop und Spielelemente ----------------------------------------------------------

TRIGGER = "TOOLS/TOOLSTRIGGER"


def _box_points(cx: float, cy: float, z0: float, length: float, width: float, height: float,
                yaw: float) -> list[IPoint]:
    """Quader um (cx, cy) ab Höhe z0, entlang `yaw` ausgerichtet. Die Ecken werden gerundet;
    weil Ober- und Unterseite waagrecht bleiben, ist das Ergebnis immer ein exaktes Prisma."""
    a = math.radians(yaw)
    fx, fy = math.cos(a), math.sin(a)
    lx, ly = -fy, fx
    pts: list[IPoint] = []
    for sf, sl in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        x = cx + fx * length / 2 * sf + lx * width / 2 * sl
        y = cy + fy * length / 2 * sf + ly * width / 2 * sl
        for z in (z0, z0 + height):
            pts.append((_r(x), _r(y), _r(z)))
    return pts


def build_bhop(v: dict, at: Placement, m: Materials) -> list[Shape]:
    """Reihe von Plattformen, optional im Zickzack und mit Stufen."""
    a = math.radians(at.yaw)
    fx, fy = math.cos(a), math.sin(a)
    lx, ly = -fy, fx
    size = v["groesse"]
    shapes: list[Shape] = []
    for i in range(v["anzahl"]):
        forward = i * (size + v["abstand"]) + size / 2
        side = v["zickzack"] * (1 if i % 2 else -1) / 2 if v["zickzack"] else 0
        cx = at.x + fx * forward + lx * side
        cy = at.y + fy * forward + ly * side
        pts = _box_points(cx, cy, at.z + i * v["stufe"], size, size, v["dicke"], at.yaw)
        shapes.append(HullShape(pts, m))
    return shapes


def bhop_entity(v: dict, at: Placement) -> tuple[str, tuple[tuple[str, str], ...]]:
    return "func_detail", ()


def build_trigger_box(v: dict, at: Placement, m: Materials) -> list[Shape]:
    a = math.radians(at.yaw)
    cx = at.x + math.cos(a) * v["laenge"] / 2
    cy = at.y + math.sin(a) * v["laenge"] / 2
    pts = _box_points(cx, cy, at.z, v["laenge"], v["breite"], v["hoehe"], at.yaw)
    return [HullShape(pts, Materials(TRIGGER, TRIGGER, TRIGGER, hide_bottom=True))]


def booster_entity(v: dict, at: Placement) -> tuple[str, tuple[tuple[str, str], ...]]:
    yaw = (at.yaw + v["schub_richtung"]) % 360
    return "trigger_push", (
        ("spawnflags", "1"), ("pushdir", f"{-v['schub_neigung']:g} {yaw:g} 0"), ("speed", f"{v['tempo']:g}"),
        ("StartDisabled", "0"),
    )


def teleport_entity(v: dict, at: Placement) -> tuple[str, tuple[tuple[str, str], ...]]:
    return "trigger_teleport", (("spawnflags", "1"), ("target", v["ziel"]), ("StartDisabled", "0"))


BOX_PARAMS = (
    Param("laenge", "Länge", 256, 16, 16384, 16, "u"),
    Param("breite", "Breite", 256, 16, 16384, 16, "u"),
    Param("hoehe", "Höhe", 128, 16, 16384, 16, "u"),
)

_add(Template("bhop", "Bhop-Blöcke", "Bhop", "Reihe von Plattformen zum Springen.",
              (Param("anzahl", "Anzahl", 6, 1, 64), Param("groesse", "Größe", 64, 16, 1024, 16, "u"),
               Param("abstand", "Abstand", 192, 0, 2048, 16, "u"), Param("dicke", "Dicke", 16, 8, 512, 8, "u"),
               Param("zickzack", "Zickzack seitlich", 0, 0, 2048, 16, "u"),
               Param("stufe", "Stufe pro Block", 0, -512, 512, 8, "u", hint="Positiv = jeder Block höher"),
               dataclasses.replace(SIDE_MATERIAL, label="Material", hint=""),
               Param("unterseite_nodraw", "Unterseite unsichtbar (Nodraw)", False)),
              build_bhop, check_angles=False, entity=bhop_entity))
_add(Template("booster", "Booster", "Bhop", "Trigger, der den Spieler in eine Richtung schiebt (trigger_push).",
              (*BOX_PARAMS, Param("tempo", "Tempo", 800, 0, 10000, 50, "u/s"),
               Param("schub_neigung", "Neigung nach oben", 0.0, -90, 90, 5, "°"),
               Param("schub_richtung", "Richtung (relativ)", 0.0, -180, 180, 15, "°", hint="0° = entlang des Bausteins")),
              build_trigger_box, check_angles=False, entity=booster_entity))
_add(Template("teleporter", "Teleporter", "Bhop", "Trigger, der zum Ziel teleportiert (trigger_teleport). "
              "Das Ziel wird mit eingefügt und lässt sich frei verschieben.",
              (*BOX_PARAMS, Param("ziel", "Zielname", "ziel", hint="targetname des info_teleport_destination")),
              build_trigger_box, check_angles=False, entity=teleport_entity))


# ---- Zeitnahme-Zonen ------------------------------------------------------------------
#
# Zonen sind trigger_multiple mit Namen nach dem „mod_zone“-Standard, den bhoptimer und
# andere CS:S-Timer automatisch erkennen. Für Momentum wird daraus beim Kompilieren eine
# Zonendatei erzeugt (siehe core/zones.py).

ZONE_PARAMS = (
    Param("laenge", "Länge", 384, 32, 16384, 16, "u"),
    Param("breite", "Breite", 384, 32, 16384, 16, "u"),
    Param("hoehe", "Höhe", 128, 16, 4096, 16, "u"),
)
BONUS = Param("bonus", "Bonus-Nummer", 0, 0, 9, hint="0 = Hauptstrecke, 1–9 = Bonus")


def zone_name(kind: str, bonus: int = 0, number: int = 0) -> str:
    """targetname nach dem mod_zone-Standard (bhoptimer, Fly)."""
    track = f"bonus_{bonus}_" if bonus else ""
    if kind == "stage":
        return f"mod_zone_{track}checkpoint_{number}"
    return f"mod_zone_{track}{kind}"


def _zone_entity(kind: str) -> Callable[[dict, Placement], tuple[str, tuple[tuple[str, str], ...]]]:
    def entity(v: dict, at: Placement) -> tuple[str, tuple[tuple[str, str], ...]]:
        name = zone_name(kind, v.get("bonus", 0), v.get("nummer", 0))
        return "trigger_multiple", (("targetname", name), ("spawnflags", "1"), ("wait", "0"),
                                    ("StartDisabled", "0"))
    return entity


_add(Template("zone_start", "Startzone", "Zonen", "Hier startet die Zeit, sobald man die Zone verlässt. "
              "CS:S-Timer erkennen sie am Namen, für Momentum wird eine Zonendatei erzeugt.",
              (*ZONE_PARAMS, BONUS), build_trigger_box, check_angles=False, entity=_zone_entity("start")))
_add(Template("zone_ende", "Zielzone", "Zonen", "Hier stoppt die Zeit.",
              (*ZONE_PARAMS, BONUS), build_trigger_box, check_angles=False, entity=_zone_entity("end")))
_add(Template("zone_stage", "Stage-Zone", "Zonen", "Beginn einer Stage auf der Hauptstrecke. "
              "Stage 1 ist die Startzone, die erste Stage-Zone ist also Stage 2.",
              (*ZONE_PARAMS, Param("nummer", "Stage", 2, 2, 99)),
              build_trigger_box, check_angles=False, entity=_zone_entity("stage")))


# ---- Erzeugen ------------------------------------------------------------------------

@dataclass
class Generated:
    face_sets: list[tuple[Face, ...]]
    #: Winkel der flachsten und steilsten Surf-Fläche zur Waagrechten
    angle_range: tuple[float, float] | None
    warnings: list[str]


def _plane_key(face: Face) -> tuple:
    pl = face.plane
    return (round(pl.normal[0], 5), round(pl.normal[1], 5), round(pl.normal[2], 5), round(pl.dist, 2))


def hide_touching(face_sets: list[tuple[Face, ...]], hidden: str) -> list[tuple[Face, ...]]:
    """Seiten, die flach an einem anderen Teil desselben Bausteins anliegen, unsichtbar machen."""
    owners: dict[tuple, set[int]] = {}
    for i, faces in enumerate(face_sets):
        for f in faces:
            owners.setdefault(_plane_key(f), set()).add(i)
    out = []
    for i, faces in enumerate(face_sets):
        new = []
        for f in faces:
            nx, ny, nz, d = _plane_key(f)
            opposite = owners.get((-nx + 0.0, -ny + 0.0, -nz + 0.0, -d + 0.0), set()) - {i}
            new.append(dataclasses.replace(f, material=hidden) if opposite else f)
        out.append(tuple(new))
    return out


def surf_angles(face_sets: list[tuple[Face, ...]], surf_material: str) -> tuple[float, float] | None:
    angles = []
    for faces in face_sets:
        for f in faces:
            if f.material != surf_material:
                continue
            nz = abs(f.plane.normal[2])
            if nz > 1e-9:
                angles.append(math.degrees(math.acos(min(1.0, nz))))
    if not angles:
        return None
    return min(angles), max(angles)


def angle_warnings(angle_range: tuple[float, float] | None) -> list[str]:
    if angle_range is None:
        return []
    lo, hi = angle_range
    out = []
    if lo < SURF_MIN_ANGLE:
        out.append(f"Zu flach: {lo:.1f}° (unter {SURF_MIN_ANGLE:.0f}° kann man stehen statt surfen)")
    if hi > SURF_STEEP_ANGLE:
        out.append(f"Sehr steil: {hi:.1f}° (über {SURF_STEEP_ANGLE:.0f}° kaum noch kontrollierbar)")
    return out


ORIGIN = Placement()


def generate(template: Template | str, values: dict | None = None, at: Placement = ORIGIN) -> Generated:
    t = CATALOG[template] if isinstance(template, str) else template
    v = t.values(values)
    m = materials_from(v)
    pieces: list[SweepPiece] = []
    for shape in t.builder(v, at, m):
        pieces += shape.build()
    face_sets = hide_touching([p.faces for p in pieces], m.hidden)
    angles = surf_angles(face_sets, m.surf)
    return Generated(face_sets, angles, angle_warnings(angles) if t.check_angles else [])
