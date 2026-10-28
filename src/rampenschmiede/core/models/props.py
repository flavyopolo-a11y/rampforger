"""Props: Modell-Entities (prop_static, prop_dynamic, prop_physics) und was zu ihnen passt.

Nicht jedes Modell funktioniert mit jeder Klasse:
- prop_static braucht ein Modell mit `$staticprop`. Sonst löscht vbsp den Prop beim
  Kompilieren ("prop_static using model ... which must be used on a dynamic entity").
- prop_physics braucht ein Kollisionsmodell (.phy), sonst erscheint es im Spiel nicht.
- prop_dynamic geht mit jedem Modell.
"""
from __future__ import annotations

import math

from ..mathutil import BBox, Point
from ..model import Entity
from .library import Bounds, LoadedModel, ModelLibrary, normalize_model

PROP_CLASSES = ("prop_static", "prop_dynamic", "prop_physics")
#: Weitere Klassen, die ein Modell zeigen (Keyvalue `model`)
MODEL_CLASSES = frozenset(PROP_CLASSES) | {
    "prop_dynamic_override", "prop_physics_override", "prop_physics_multiplayer", "prop_ragdoll",
    "prop_detail", "prop_door_rotating", "cycler",
}
PROP_LABELS = {
    "prop_static": "Statisch",
    "prop_dynamic": "Dynamisch",
    "prop_physics": "Physik",
}
PROP_HELP = {
    "prop_static": "Fest in die Map gebacken, wirft Schatten, kostet im Spiel am wenigsten.",
    "prop_dynamic": "Kann sich bewegen, animieren oder ausgeblendet werden.",
    "prop_physics": "Fällt, rollt und lässt sich anschießen.",
}

Matrix3 = tuple[Point, Point, Point]


def angle_matrix(pitch: float, yaw: float, roll: float) -> Matrix3:
    """Drehmatrix (Zeilen) für Source-Winkel: Welt = M · Modell. Positiver Nick neigt die
    Nase (+X des Modells) nach unten, wie AngleMatrix in der Engine."""
    sp, cp = math.sin(math.radians(pitch)), math.cos(math.radians(pitch))
    sy, cy = math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    sr, cr = math.sin(math.radians(roll)), math.cos(math.radians(roll))
    return (
        (cp * cy, sr * sp * cy - cr * sy, cr * sp * cy + sr * sy),
        (cp * sy, sr * sp * sy + cr * cy, cr * sp * sy - sr * cy),
        (-sp, sr * cp, cr * cp),
    )


def entity_angles(ent: Entity) -> tuple[float, float, float]:
    parts = ent.get("angles", "0 0 0").split()
    try:
        values = [float(p) for p in parts[:3]]
    except ValueError:
        values = []
    while len(values) < 3:
        values.append(0.0)
    return values[0], values[1], values[2]


def is_model_entity(ent: Entity) -> bool:
    model = ent.get("model", "")
    return model.lower().endswith(".mdl") or (ent.classname.lower() in MODEL_CLASSES and bool(model))


def entity_model(ent: Entity) -> str:
    return normalize_model(ent.get("model", "")) if ent.get("model", "") else ""


def entity_skin(ent: Entity) -> int:
    try:
        return int(float(ent.get("skin", "0") or 0))
    except ValueError:
        return 0


def placed_bbox(bounds: Bounds, origin: Point, angles: tuple[float, float, float]) -> BBox:
    """Achsenparallele Hülle der gedrehten Modell-Ausdehnung an der Entity-Position."""
    lo, hi = bounds
    m = angle_matrix(*angles)
    xs, ys, zs = [], [], []
    for i in range(8):
        c = (lo[0] if i & 1 == 0 else hi[0], lo[1] if i & 2 == 0 else hi[1], lo[2] if i & 4 == 0 else hi[2])
        xs.append(origin[0] + m[0][0] * c[0] + m[0][1] * c[1] + m[0][2] * c[2])
        ys.append(origin[1] + m[1][0] * c[0] + m[1][1] * c[1] + m[1][2] * c[2])
        zs.append(origin[2] + m[2][0] * c[0] + m[2][1] * c[1] + m[2][2] * c[2])
    return BBox((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))


def best_class(model: LoadedModel | None) -> str:
    """Klasse für ein neu gesetztes Modell: statisch, wenn das Modell es erlaubt."""
    if model is None or model.static_prop:
        return "prop_static"
    return "prop_dynamic"


def class_problem(classname: str, model: LoadedModel | None) -> str:
    """Warum die Klasse nicht zum Modell passt ("" wenn alles stimmt)."""
    if model is None:
        return ""
    c = classname.lower()
    if c == "prop_static" and not model.static_prop:
        return ("Das Modell ist kein statisches Modell: vbsp löscht diesen prop_static beim Kompilieren. "
                "Nimm prop_dynamic.")
    if c in ("prop_physics", "prop_physics_multiplayer") and not model.has_physics:
        return "Das Modell hat kein Kollisionsmodell (.phy): Als prop_physics erscheint es im Spiel nicht."
    return ""


def allowed_classes(model: LoadedModel | None) -> dict[str, str]:
    """Je Prop-Klasse "" (passt) oder der Grund, warum nicht."""
    return {c: class_problem(c, model) for c in PROP_CLASSES}


def new_prop(model_name: str, origin: Point, model: LoadedModel | None, yaw: float = 0.0, skin: int = 0) -> Entity:
    """Neuer Prop mit dem Modell an `origin` (ganze Units), Klasse passend zum Modell."""
    classname = best_class(model)
    kvs: list[tuple[str, str]] = [
        ("origin", " ".join(str(round(c)) for c in origin)),
        ("angles", f"0 {yaw:g} 0"),
        ("model", normalize_model(model_name)),
        ("skin", str(skin)),
    ]
    if classname in ("prop_static", "prop_dynamic"):
        kvs.append(("solid", "6"))  # Kollision über das Kollisionsmodell (FGD-Standard)
    return Entity(id=0, classname=classname, keyvalues=tuple(kvs))


def change_class(ent: Entity, classname: str) -> Entity:
    """Prop-Klasse wechseln. Keys, die nur die alte Klasse kennt, bleiben stehen (wie in Hammer)."""
    return ent.replace(classname=classname)


def prop_bbox(ent: Entity, library: ModelLibrary | None) -> BBox | None:
    """Hülle eines Props aus seinem Modell, None wenn es kein (ladbares) Modell hat."""
    if library is None:
        return None
    name = ent.get("model", "")
    if not name.lower().endswith(".mdl"):
        return None
    origin = ent.origin
    model = library.load(name) if origin is not None else None
    if model is None or origin is None:
        return None
    return placed_bbox(model.bounds(), origin, entity_angles(ent))


def prop_problems(doc, library: ModelLibrary | None) -> list[tuple[Entity, str]]:
    """Props, die im Spiel nicht so erscheinen werden wie im Editor: Modell fehlt oder passt
    nicht zur Klasse. Je Modell und Problem nur ein Eintrag, damit das Log lesbar bleibt."""
    if library is None:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[tuple[Entity, str]] = []
    for ent in doc.entities():
        if ent.classname.lower() not in MODEL_CLASSES or not ent.get("model", "").lower().endswith(".mdl"):
            continue
        name = entity_model(ent)
        model = library.load(name)
        problem = "Modell fehlt im Spiel" if model is None else class_problem(ent.classname, model)
        if problem and (name, ent.classname + problem) not in seen:
            seen.add((name, ent.classname + problem))
            out.append((ent, f"{ent.classname} {name}: {problem}"))
    return out


__all__ = ["MODEL_CLASSES", "PROP_CLASSES", "PROP_HELP", "PROP_LABELS", "allowed_classes", "angle_matrix",
           "best_class", "change_class", "class_problem", "entity_angles", "entity_model", "entity_skin",
           "is_model_entity", "new_prop", "placed_bbox", "prop_bbox", "prop_problems"]
