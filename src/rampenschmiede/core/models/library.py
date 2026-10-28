"""Modelle aus dem Spiel: Index aller MDL-Dateien und geladene Modelle für Vorschau und Ansichten.

Die Bibliothek nutzt dasselbe Dateisystem wie die Material-Bibliothek (VPKs und Ordner
des Spielprofils, eigene Ordner davor). Namen werden wie im Keyvalue `model` geführt:
`models/props/foo.mdl`, klein geschrieben, mit Schrägstrichen.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import numpy as np

from ...i18n import tr
from ..materials import MaterialLibrary, normalize
from .mdl import (
    VTX_SUFFIXES,
    ModelError,
    ModelGeometry,
    StudioHeader,
    build_geometry,
    feature_edges,
    read_header,
)

Bounds = tuple[tuple[float, float, float], tuple[float, float, float]]


def normalize_model(name: str) -> str:
    """'Models\\Props\\Foo.MDL' → 'models/props/foo.mdl'."""
    n = name.replace("\\", "/").strip().strip("/").lower()
    if n and not n.startswith("models/"):
        n = "models/" + n
    if n and not n.endswith(".mdl"):
        n += ".mdl"
    return n


@dataclass
class LoadedModel:
    name: str
    header: StudioHeader
    geometry: ModelGeometry | None
    has_physics: bool
    #: Je Skin die Materialnamen je Material-Spalte ("" wenn das Material fehlt)
    skin_materials: list[list[str]]
    #: Grund, warum die Geometrie fehlt (dann zeigen die Ansichten nur einen Kasten)
    problem: str = ""
    _edges: np.ndarray | None = field(default=None, repr=False)

    def edges(self) -> np.ndarray:
        """Umriss- und Knickkanten im Modell-Koordinatensystem (einmal berechnet)."""
        if self._edges is None:
            self._edges = (feature_edges(self.geometry) if self.geometry is not None
                           else np.zeros((0, 3), dtype=np.float32))
        return self._edges

    @property
    def static_prop(self) -> bool:
        return self.header.static_prop

    @property
    def skin_count(self) -> int:
        return max(1, len(self.skin_materials))

    def materials(self, skin: int = 0) -> list[str]:
        if not self.skin_materials:
            return []
        return self.skin_materials[skin if 0 <= skin < len(self.skin_materials) else 0]

    def bounds(self) -> Bounds:
        """Ausdehnung im Modell-Koordinatensystem: aus den Dreiecken, sonst aus dem MDL-Kopf."""
        if self.geometry is not None:
            b = self.geometry.bounds()
            if b is not None:
                return b
        h = self.header
        for lo, hi in ((h.view_min, h.view_max), (h.hull_min, h.hull_max)):
            if any(hi[i] > lo[i] for i in range(3)):
                return lo, hi
        return (-8.0, -8.0, -8.0), (8.0, 8.0, 8.0)

    @property
    def triangle_count(self) -> int:
        return self.geometry.triangle_count if self.geometry is not None else 0


class ModelLibrary:
    def __init__(self, materials: MaterialLibrary) -> None:
        self.materials = materials
        self._lock = threading.RLock()
        self._names: list[str] | None = None
        self._models: dict[str, LoadedModel | None] = {}

    @property
    def fsys(self):
        return self.materials.fsys

    def names(self) -> list[str]:
        """Alle Modelle, sortiert. Beim ersten Aufruf werden alle VPKs durchsucht."""
        with self._lock:
            if self._names is None:
                found: set[str] = set()
                for f in self.fsys.walk_folder("models"):
                    if f.path.lower().endswith(".mdl"):
                        found.add(normalize_model(f.path))
                self._names = sorted(found)
            return self._names

    def _read(self, path: str) -> bytes | None:
        try:
            f = self.fsys[path]
        except (FileNotFoundError, KeyError):
            return None
        try:
            with f.open_bin() as stream:
                return stream.read()
        except OSError:
            return None

    def exists(self, name: str) -> bool:
        try:
            self.fsys[normalize_model(name)]
        except (FileNotFoundError, KeyError):
            return False
        return True

    def load(self, name: str) -> LoadedModel | None:
        """Modell laden (zwischengespeichert, threadsicher). None, wenn es fehlt oder unlesbar ist."""
        key = normalize_model(name)
        if not key:
            return None
        with self._lock:
            if key in self._models:
                return self._models[key]
        model = self._load(key)
        with self._lock:
            self._models.setdefault(key, model)
            return self._models[key]

    def _load(self, key: str) -> LoadedModel | None:
        data = self._read(key)
        if data is None:
            return None
        try:
            header = read_header(data)
        except ModelError:
            return None
        stem = str(PurePosixPath(key).with_suffix(""))
        geometry = None
        problem = ""
        vvd = self._read(stem + ".vvd")
        vtx = next((d for d in (self._read(stem + s) for s in VTX_SUFFIXES) if d is not None), None)
        if vvd is None or vtx is None:
            problem = tr("VVD/VTX fehlt")
        else:
            try:
                geometry = build_geometry(header, vvd, vtx)
            except (ModelError, ValueError, IndexError) as exc:
                problem = str(exc)
        has_physics = self._read(stem + ".phy") is not None
        skins = [[self._find_material(header, header.textures[i]) if i < len(header.textures) else ""
                  for i in row] for row in header.skins]
        return LoadedModel(key, header, geometry, has_physics, skins, problem)

    def _find_material(self, header: StudioHeader, texture: str) -> str:
        """Material eines Modells suchen: wie die Engine in jedem $cdmaterials-Ordner."""
        folders = list(header.cdmaterials)
        if "/" in texture:
            folders.append("")
        for folder in folders or [""]:
            name = normalize(folder + texture)
            if self.materials.exists(name):
                return name
        return ""

    def forget(self) -> None:
        with self._lock:
            self._names = None
            self._models.clear()


__all__ = ["Bounds", "LoadedModel", "ModelLibrary", "normalize_model"]
