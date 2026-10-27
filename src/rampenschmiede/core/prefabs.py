"""Eigene Prefabs: eine Auswahl als Datei speichern und beliebig oft wieder einsetzen.

Ein Prefab ist JSON im selben Objektformat wie `.rsmap`. Die Objekte werden so verschoben,
dass ihr Ankerpunkt (Mitte unten) im Nullpunkt liegt. Beim Einsetzen bekommen sie neue IDs,
Bausteine bleiben Bausteine.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from .blocks import clone_objects
from .geometry import transform
from .io.rsmap import ProjectFormatError, object_from_dict, object_to_dict
from .mathutil import BBox, Point
from .model import MapDocument, MapObject, object_bbox

FORMAT_NAME = "rampenschmiede-prefab"
SCHEMA_VERSION = 1
FILE_SUFFIX = ".json"


def make_prefab(doc: MapDocument, ids: Iterable[int], name: str) -> dict[str, Any]:
    ids = [i for i in ids if i in doc]
    objs: list[MapObject] = [o for i in ids if (o := doc.get(i)) is not None] + doc.attached(ids)
    if not objs:
        raise ValueError("Nichts ausgewählt")
    bounds = BBox.union(object_bbox(o) for o in objs)
    assert bounds is not None
    anchor = (round(bounds.center[0]), round(bounds.center[1]), round(bounds.mins[2]))
    back = (-anchor[0], -anchor[1], -anchor[2])
    return {
        "format": FORMAT_NAME,
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "size": [round(c) for c in bounds.size],
        "objects": [object_to_dict(transform.translate(o, back, True)) for o in objs],
    }


def place_prefab(doc: MapDocument, data: dict[str, Any], at: Point) -> tuple[list[MapObject], list[int]]:
    """Objekte des Prefabs mit neuen IDs, Anker an `at`. Liefert Objekte und oberste IDs."""
    if data.get("format") != FORMAT_NAME:
        raise ProjectFormatError("Keine Prefab-Datei")
    objs = [object_from_dict(o) for o in data.get("objects", [])]
    clones, roots = clone_objects(doc, objs)
    delta = (round(at[0]), round(at[1]), round(at[2]))
    return [transform.translate(o, delta, True) for o in clones], roots


def file_name(name: str) -> str:
    safe = re.sub(r"[^\w\- ]+", "_", name, flags=re.UNICODE).strip() or "prefab"
    return safe + FILE_SUFFIX


def save_prefab(data: dict[str, Any], folder: str | os.PathLike[str]) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file_name(data["name"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_prefab(path: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectFormatError(f"Prefab nicht lesbar: {exc}") from exc
    if data.get("format") != FORMAT_NAME:
        raise ProjectFormatError("Keine Prefab-Datei")
    return data


def list_prefabs(folder: str | os.PathLike[str]) -> list[tuple[str, Path]]:
    """(Name, Pfad) aller lesbaren Prefabs, nach Name sortiert."""
    folder = Path(folder)
    out = []
    for p in sorted(folder.glob("*" + FILE_SUFFIX)) if folder.is_dir() else []:
        try:
            out.append((str(load_prefab(p).get("name") or p.stem), p))
        except ProjectFormatError:
            continue
    return sorted(out, key=lambda t: t[0].lower())
