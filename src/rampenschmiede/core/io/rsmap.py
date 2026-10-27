"""Projektformat .rsmap: JSON mit versioniertem Schema.

Speichern läuft atomar: erst in eine temporäre Datei im selben Ordner, dann ersetzen.
Ein Absturz beim Speichern kann die alte Datei also nicht beschädigen.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..model import EditorInfo, EditorState, Entity, Face, MapDocument, MapObject, Output, Solid, TexAxis

FORMAT_NAME = "rampenschmiede-map"
SCHEMA_VERSION = 1
FILE_SUFFIX = ".rsmap"


class ProjectFormatError(ValueError):
    pass


# ---- Schreiben ----------------------------------------------------------

def _num(v: float) -> float | int:
    """Ganze Zahlen ohne .0 schreiben, das hält die Datei lesbar."""
    return int(v) if float(v).is_integer() else v


def _axis(a: TexAxis) -> list[float | int]:
    return [_num(a.x), _num(a.y), _num(a.z), _num(a.offset), _num(a.scale)]


def _editor(e: EditorInfo) -> dict[str, Any]:
    d: dict[str, Any] = {"color": list(e.color)}
    if e.group_id is not None:
        d["group"] = e.group_id
    if e.visgroup_ids:
        d["visgroups"] = list(e.visgroup_ids)
    if e.hidden:
        d["hidden"] = True
    if e.locked:
        d["locked"] = True
    return d


def _face(f: Face) -> dict[str, Any]:
    d: dict[str, Any] = {
        "points": [[_num(c) for c in p] for p in f.points],
        "material": f.material,
        "uaxis": _axis(f.uaxis),
        "vaxis": _axis(f.vaxis),
    }
    if f.rotation:
        d["rotation"] = _num(f.rotation)
    if f.lightmapscale != 16:
        d["lightmapscale"] = f.lightmapscale
    if f.smoothing_groups:
        d["smoothing_groups"] = f.smoothing_groups
    if f.vmf_id is not None:
        d["vmf_id"] = f.vmf_id
    if f.extra:
        d["extra"] = f.extra
    return d


def _object(o: MapObject) -> dict[str, Any]:
    if isinstance(o, Solid):
        d: dict[str, Any] = {"type": "solid", "id": o.id, "faces": [_face(f) for f in o.faces]}
        if o.parent_id is not None:
            d["parent"] = o.parent_id
    else:
        d = {"type": "entity", "id": o.id, "classname": o.classname, "keyvalues": [list(kv) for kv in o.keyvalues]}
        if o.outputs:
            d["outputs"] = [
                {"output": x.output, "target": x.target, "input": x.input, "parameter": x.parameter,
                 "delay": _num(x.delay), "times": x.times}
                for x in o.outputs
            ]
    d["editor"] = _editor(o.editor)
    if o.vmf_id is not None:
        d["vmf_id"] = o.vmf_id
    if o.extra:
        d["extra"] = o.extra
    return d


def to_dict(doc: MapDocument) -> dict[str, Any]:
    from ... import __version__

    e = doc.editor
    return {
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "app_version": __version__,
        "world": {"keyvalues": [list(kv) for kv in doc.world_keyvalues]},
        "editor": {
            "grid_size": e.grid_size,
            "camera_position": [_num(c) for c in e.camera_position],
            "camera_angles": [_num(c) for c in e.camera_angles],
            "expert_mode": e.expert_mode,
        },
        "objects": [_object(o) for o in sorted(doc.objects(), key=lambda o: o.id)],
    }


def save(doc: MapDocument, path: str | os.PathLike[str]) -> None:
    path = Path(path)
    data = json.dumps(to_dict(doc), ensure_ascii=False, indent=1)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---- Lesen ---------------------------------------------------------------

def _read_axis(raw: list[float]) -> TexAxis:
    x, y, z, off, sc = (float(v) for v in raw)
    return TexAxis(x, y, z, off, sc)


def _read_editor(raw: dict[str, Any] | None, default: EditorInfo) -> EditorInfo:
    if not raw:
        return default
    return EditorInfo(
        color=tuple(int(c) for c in raw.get("color", default.color)),  # type: ignore[arg-type]
        group_id=raw.get("group"),
        visgroup_ids=tuple(raw.get("visgroups", ())),
        hidden=bool(raw.get("hidden", False)),
        locked=bool(raw.get("locked", False)),
    )


def _read_face(raw: dict[str, Any]) -> Face:
    pts = tuple(tuple(float(c) for c in p) for p in raw["points"])
    if len(pts) != 3 or any(len(p) != 3 for p in pts):
        raise ProjectFormatError("Face braucht genau drei Punkte")
    return Face(
        points=pts,  # type: ignore[arg-type]
        material=raw.get("material", "TOOLS/TOOLSNODRAW"),
        uaxis=_read_axis(raw["uaxis"]),
        vaxis=_read_axis(raw["vaxis"]),
        rotation=float(raw.get("rotation", 0.0)),
        lightmapscale=int(raw.get("lightmapscale", 16)),
        smoothing_groups=int(raw.get("smoothing_groups", 0)),
        vmf_id=raw.get("vmf_id"),
        extra=raw.get("extra", {}),
    )


def _read_object(raw: dict[str, Any]) -> MapObject:
    kind = raw.get("type")
    if kind == "solid":
        return Solid(
            id=int(raw["id"]),
            faces=tuple(_read_face(f) for f in raw["faces"]),
            parent_id=raw.get("parent"),
            editor=_read_editor(raw.get("editor"), EditorInfo()),
            vmf_id=raw.get("vmf_id"),
            extra=raw.get("extra", {}),
        )
    if kind == "entity":
        return Entity(
            id=int(raw["id"]),
            classname=raw["classname"],
            keyvalues=tuple((str(k), str(v)) for k, v in raw.get("keyvalues", [])),
            outputs=tuple(
                Output(o["output"], o["target"], o["input"], o.get("parameter", ""),
                       float(o.get("delay", 0.0)), int(o.get("times", -1)))
                for o in raw.get("outputs", [])
            ),
            editor=_read_editor(raw.get("editor"), Entity.__dataclass_fields__["editor"].default),  # type: ignore[arg-type]
            vmf_id=raw.get("vmf_id"),
            extra=raw.get("extra", {}),
        )
    raise ProjectFormatError(f"Unbekannter Objekttyp: {kind!r}")


def from_dict(data: dict[str, Any]) -> MapDocument:
    if data.get("format") != FORMAT_NAME:
        raise ProjectFormatError("Keine Rampenschmiede-Projektdatei")
    version = data.get("schema_version")
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        raise ProjectFormatError(
            f"Projektversion {version} ist neuer als dieses Programm (unterstützt bis {SCHEMA_VERSION})"
        )
    doc = MapDocument()
    doc.world_keyvalues = tuple((str(k), str(v)) for k, v in data.get("world", {}).get("keyvalues", []))
    ed = data.get("editor", {})
    doc.editor = EditorState(
        grid_size=int(ed.get("grid_size", 16)),
        camera_position=tuple(float(c) for c in ed.get("camera_position", EditorState.camera_position)),  # type: ignore[arg-type]
        camera_angles=tuple(float(c) for c in ed.get("camera_angles", EditorState.camera_angles)),  # type: ignore[arg-type]
        expert_mode=bool(ed.get("expert_mode", False)),
    )
    doc._insert(_read_object(o) for o in data.get("objects", []))
    return doc


def load(path: str | os.PathLike[str]) -> MapDocument:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ProjectFormatError(f"Datei ist kein gültiges JSON: {exc}") from exc
    return from_dict(data)
