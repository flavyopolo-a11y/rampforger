"""Instanzen (func_instance wie in Hammer): eine andere Map-Datei (.vmf oder .rsmap), die an
Ursprung und Drehung der Entity eingesetzt wird. Ändert man die Datei, ändern sich alle
Instanzen. Im Editor wird der Inhalt angezeigt; beim Kompilieren wird er eingesetzt
(„collapse“ wie vbsp), mit Namens-Präfix und Ersetzungen `$variable` aus `replace01` ….

Eingesetzte Namen: Hat die Instanz einen Namen, bekommen alle Namen aus der Datei und die
Verweise darauf `<Instanz>-` vorne (`fixup_style` 0), `-<Instanz>` hinten (1) oder nichts (2).
Namen mit `@` oder `!` am Anfang bleiben wie sie sind (global)."""
from __future__ import annotations

import dataclasses
import math
import os
from pathlib import Path
from typing import Callable

from .geometry.transform import TransformError, _transform_solid, mat_mul_vec
from .mathutil import BBox, Point
from .model import Entity, MapDocument, MapObject, Solid, TexAxis
from .models.props import Matrix3, angle_matrix, entity_angles

INSTANCE = "func_instance"
PARMS = "func_instance_parms"
SUFFIXES = (".vmf", ".rsmap")
MAX_DEPTH = 8


# ---- Dateien ---------------------------------------------------------------------------
def resolve(file: str, base_dir: Path | None) -> Path | None:
    """Datei einer Instanz: absolut, neben der Map, im Ordner `instances` neben der Map
    oder (wie Hammer) relativ zum Ordner `maps` darüber."""
    if not file:
        return None
    raw = Path(file.replace("\\", "/"))
    candidates = [raw] if raw.is_absolute() else []
    if base_dir is not None and not raw.is_absolute():
        candidates += [base_dir / raw, base_dir / "instances" / raw]
        for parent in base_dir.parents:
            if parent.name.lower() == "maps":
                candidates.append(parent / raw)
                break
    for c in candidates:
        if c.is_file():
            return c
        for suffix in SUFFIXES:
            if not c.suffix and c.with_suffix(suffix).is_file():
                return c.with_suffix(suffix)
    return None


def load_map(path: Path) -> MapDocument:
    if path.suffix.lower() == ".rsmap":
        from .io.rsmap import load

        return load(path)
    from .io.vmf import load_vmf

    return load_vmf(path)[0]


class InstanceCache:
    """Geladene Instanz-Dateien, neu gelesen, wenn sich die Datei ändert."""

    def __init__(self) -> None:
        self._docs: dict[Path, tuple[float, MapDocument | None]] = {}

    def get(self, path: Path) -> MapDocument | None:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        hit = self._docs.get(path)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        try:
            doc: MapDocument | None = load_map(path)
        except Exception:  # noqa: BLE001 - kaputte Datei: Instanz bleibt leer, Prüfung meldet es
            doc = None
        self._docs[path] = (mtime, doc)
        return doc

    def stale(self) -> bool:
        """Hat sich eine geladene Datei seitdem geändert (oder ist verschwunden)?"""
        for path, (mtime, _doc) in self._docs.items():
            try:
                if os.path.getmtime(path) != mtime:
                    return True
            except OSError:
                return True
        return False

    def forget(self) -> None:
        self._docs.clear()


# ---- Lage ------------------------------------------------------------------------------
def matrix_angles(m: Matrix3) -> tuple[float, float, float]:
    """Umkehrung von `angle_matrix` (MatrixAngles der Engine): Nick, Gier, Roll in Grad."""
    fx, fy, fz = m[0][0], m[1][0], m[2][0]
    xy = math.hypot(fx, fy)
    if xy > 1e-3:
        yaw = math.degrees(math.atan2(fy, fx))
        pitch = math.degrees(math.atan2(-fz, xy))
        roll = math.degrees(math.atan2(m[2][1], m[2][2]))
    else:
        yaw = math.degrees(math.atan2(-m[0][1], m[1][1]))
        pitch = math.degrees(math.atan2(-fz, xy))
        roll = 0.0
    return _norm(pitch), _norm(yaw), _norm(roll)


def _norm(a: float) -> float:
    a = round(a, 4) % 360.0
    return 0.0 if a >= 359.9999 else a


def _matmul(a: Matrix3, b: Matrix3) -> Matrix3:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))  # type: ignore[return-value]


def _clean(m: Matrix3) -> Matrix3:
    """Fast ganze Werte (90°-Drehungen) glätten, damit Brushes auf ganzen Units bleiben."""
    return tuple(tuple(float(round(v)) if abs(v - round(v)) < 1e-9 else v for v in row) for row in m)  # type: ignore[return-value]


def placement(ent: Entity) -> tuple[Matrix3, Point]:
    return _clean(angle_matrix(*entity_angles(ent))), ent.origin or (0.0, 0.0, 0.0)


def _place_point(m: Matrix3, o: Point, p: Point) -> Point:
    q = mat_mul_vec(m, p)
    return q[0] + o[0], q[1] + o[1], q[2] + o[2]


def _place_axis(m: Matrix3, o: Point, ax: TexAxis) -> TexAxis:
    v = mat_mul_vec(m, ax.vec)
    off = ax.offset - (v[0] * o[0] + v[1] * o[1] + v[2] * o[2]) / ax.scale if ax.scale else ax.offset
    return TexAxis(v[0], v[1], v[2], off, ax.scale)


IDENTITY: Matrix3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def _place_entity(m: Matrix3, o: Point, ent: Entity, point: bool) -> Entity:
    """Ursprung mitnehmen; Punkt-Entities drehen sich mit (Brush-Entities nicht: ihre Brushes
    sind schon gedreht, `angles` würde sie im Spiel ein zweites Mal drehen)."""
    if ent.origin is None:
        return ent
    x, y, z = _place_point(m, o, ent.origin)
    ent = ent.with_keyvalue("origin", f"{round(x, 3):g} {round(y, 3):g} {round(z, 3):g}")
    if point and m != IDENTITY:
        a = matrix_angles(_matmul(m, angle_matrix(*entity_angles(ent))))
        ent = ent.with_keyvalue("angles", " ".join(f"{v:g}" for v in a))
    return ent


# ---- Namen und Variablen ---------------------------------------------------------------
def _replacements(inst: Entity) -> list[tuple[str, str]]:
    out = []
    for k, v in inst.keyvalues:
        if k.lower().startswith("replace") and v.strip().startswith("$"):
            var, _, value = v.strip().partition(" ")
            out.append((var, value))
    # Längere Variablen zuerst, damit `$ab` nicht in `$abc` ersetzt wird
    return sorted(out, key=lambda kv: -len(kv[0]))


def _fixer(inst: Entity, names: set[str]) -> Callable[[str], str]:
    prefix = inst.get("targetname")
    style = inst.get("fixup_style", "0").strip() or "0"
    reps = _replacements(inst)

    def fix(value: str) -> str:
        for var, rep in reps:
            value = value.replace(var, rep)
        if not prefix or style == "2" or not value or value[0] in "@!" or value.lower() not in names:
            return value
        return f"{prefix}-{value}" if style == "0" else f"{value}-{prefix}"
    return fix


# ---- Einsetzen -------------------------------------------------------------------------
def placed_objects(inst: Entity, content: MapDocument, new_id: Callable[[], int],
                   fixup: bool = True) -> list[MapObject]:
    """Objekte der Instanz-Datei an Lage und Drehung der Entity, mit neuen IDs. `fixup`:
    Namen und Variablen anpassen (fürs Kompilieren); für die Anzeige reicht die Lage."""
    m, o = placement(inst)
    names = {e.get("targetname").lower() for e in content.entities() if e.get("targetname")}
    fix = _fixer(inst, names) if fixup else (lambda v: v)
    parents = {s.parent_id for s in content.solids() if s.parent_id is not None}
    ids: dict[int, int] = {}
    for obj in content.objects():
        ids[obj.id] = new_id()
    out: list[MapObject] = []
    for obj in content.objects():
        if isinstance(obj, Solid):
            try:
                s = _transform_solid(obj, lambda p: _place_point(m, o, p), lambda ax: _place_axis(m, o, ax))
            except TransformError:
                continue
            parent = ids.get(obj.parent_id) if obj.parent_id is not None else None
            out.append(dataclasses.replace(s, id=ids[obj.id], parent_id=parent, vmf_id=None))
        else:
            if obj.classname.lower() == PARMS:
                continue
            ent = _place_entity(m, o, obj, obj.id not in parents)
            if fixup:
                ent = ent.replace(
                    keyvalues=tuple((k, fix(v)) if k.lower() not in ("origin", "angles", "classname") else (k, v)
                                    for k, v in ent.keyvalues),
                    outputs=tuple(dataclasses.replace(op, target=fix(op.target), parameter=fix(op.parameter))
                                  for op in ent.outputs))
            out.append(dataclasses.replace(ent, id=ids[obj.id], vmf_id=None, extra={}))
    return out


def instance_bbox(inst: Entity, content: MapDocument | None) -> BBox | None:
    if content is None:
        return None
    m, o = placement(inst)
    pts = []
    for obj in content.objects():
        bb = obj.bbox() if isinstance(obj, Solid) else None
        if bb is None and isinstance(obj, Entity) and obj.origin is not None:
            bb = BBox(obj.origin, obj.origin)
        if bb is None:
            continue
        for i in range(8):
            c = (bb.mins[0] if i & 1 == 0 else bb.maxs[0], bb.mins[1] if i & 2 == 0 else bb.maxs[1],
                 bb.mins[2] if i & 4 == 0 else bb.maxs[2])
            pts.append(_place_point(m, o, c))
    if not pts:
        return None
    return BBox(tuple(min(p[i] for p in pts) for i in range(3)), tuple(max(p[i] for p in pts) for i in range(3)))  # type: ignore[arg-type]


def collapse_instances(doc: MapDocument, base_dir: Path | None,
                       cache: InstanceCache | None = None) -> tuple[MapDocument, list[str]]:
    """Kopie der Map mit eingesetzten Instanzen (auch verschachtelten). Ohne Instanzen kommt
    `doc` selbst zurück. Zweiter Wert: Meldungen zu fehlenden oder kaputten Dateien."""
    if not any(e.classname.lower() == INSTANCE for e in doc.entities()):
        return doc, []
    cache = cache or InstanceCache()
    out = doc.snapshot()
    out.extra = dict(doc.extra)
    problems: list[str] = []

    def expand(inst: Entity, base: Path | None, depth: int) -> list[MapObject]:
        path = resolve(inst.get("file"), base)
        content = cache.get(path) if path is not None else None
        if content is None:
            name = inst.get("targetname") or f"#{inst.id}"
            problems.append(f"Instanz {name}: Datei „{inst.get('file')}“ nicht gefunden oder nicht lesbar")
            return []
        placed = placed_objects(inst, content, out.new_id)
        result: list[MapObject] = []
        for obj in placed:
            if isinstance(obj, Entity) and obj.classname.lower() == INSTANCE:
                if depth >= MAX_DEPTH:
                    problems.append(f"Instanzen tiefer als {MAX_DEPTH} Ebenen verschachtelt: {path}")
                    continue
                result += expand(obj, path.parent, depth + 1)  # type: ignore[union-attr]
            else:
                result.append(obj)
        return result

    for inst in [e for e in doc.entities() if e.classname.lower() == INSTANCE]:
        del out._objects[inst.id]
        for obj in expand(inst, base_dir, 1):
            out._objects[obj.id] = obj
    return out, problems


__all__ = ["INSTANCE", "InstanceCache", "collapse_instances", "instance_bbox", "load_map", "matrix_angles",
           "placed_objects", "placement", "resolve"]
