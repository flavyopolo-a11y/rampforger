"""Baut aus dem Dokument Vertex-Arrays für alle Ansichten (ohne OpenGL).

Pro Objekt werden die Arrays einmal berechnet und zwischengespeichert. Ein ChangeSet
verwirft nur die betroffenen Einträge. Die Arrays aller Objekte werden zu einem Puffer
zusammengefügt, ausgewählte Objekte zuletzt, damit sie in 2D obenauf liegen.

Zell-Batching (nur betroffene Raumzellen neu hochladen) folgt in der Komfort-Etappe.
"""
from __future__ import annotations

import colorsys
import itertools
import zlib
from dataclasses import dataclass

import numpy as np

from ..core.model import ChangeSet, Entity, MapDocument, MapObject, Solid, object_bbox, owner_id

# Werkzeug-Texturen bekommen feste, aus Hammer bekannte Farben.
TOOL_COLORS = {
    "TOOLS/TOOLSNODRAW": (0.86, 0.80, 0.30),
    "TOOLS/TOOLSPLAYERCLIP": (0.75, 0.35, 0.85),
    "TOOLS/TOOLSCLIP": (0.65, 0.45, 0.85),
    "TOOLS/TOOLSTRIGGER": (0.95, 0.55, 0.15),
    "TOOLS/TOOLSSKYBOX": (0.45, 0.75, 0.95),
    "TOOLS/TOOLSSKIP": (0.70, 0.70, 0.70),
    "TOOLS/TOOLSHINT": (0.70, 0.70, 0.70),
    "TOOLS/TOOLSBLACK": (0.08, 0.08, 0.08),
    "DEV/DEV_MEASUREGENERIC01B": (0.72, 0.72, 0.70),
}

ENTITY_COLORS = {
    "info_player_counterterrorist": (0.35, 0.55, 1.0),
    "info_player_terrorist": (1.0, 0.45, 0.30),
    "info_player_start": (0.35, 1.0, 0.45),
    "light": (1.0, 0.92, 0.45),
    "light_spot": (1.0, 0.85, 0.35),
    "light_environment": (1.0, 0.75, 0.25),
}


# Versionen sind über alle SceneMesh-Instanzen eindeutig. Sonst hielte ein Renderer nach
# dem Laden einer Datei (neue Szene, wieder Version 0) seine alten Puffer für aktuell.
_versions = itertools.count(1)

SELECT_COLOR_2D = (1.0, 0.15, 0.15)
SELECT_COLOR_3D = (1.0, 0.85, 0.1)


def material_color(material: str) -> tuple[float, float, float]:
    key = material.upper()
    if key in TOOL_COLORS:
        return TOOL_COLORS[key]
    h = (zlib.crc32(key.encode()) % 360) / 360.0
    return colorsys.hls_to_rgb(h, 0.62, 0.35)


def entity_color(classname: str) -> tuple[float, float, float]:
    return ENTITY_COLORS.get(classname, (0.85, 0.25, 0.85))


@dataclass
class ObjectMesh:
    tris: np.ndarray   # (n, 9): Position, Normale, Farbe
    lines: np.ndarray  # (m, 3): Kanten als Linienpaare
    color2d: tuple[float, float, float]
    _variants: dict | None = None

    def variant(self, selected: bool) -> tuple[np.ndarray, np.ndarray]:
        """Fertige GPU-Zeilen (Dreiecke mit Auswahl-Flag, farbige Linien), je Zustand einmal berechnet."""
        if self._variants is None:
            self._variants = {}
        hit = self._variants.get(selected)
        if hit is None:
            flag = np.full((len(self.tris), 1), 1.0 if selected else 0.0, dtype=np.float32)
            color = np.asarray(SELECT_COLOR_2D if selected else self.color2d, dtype=np.float32)
            hit = (
                np.hstack([self.tris, flag]),
                np.hstack([self.lines, np.tile(color, (len(self.lines), 1))]),
            )
            self._variants[selected] = hit
        return hit

    def selected_3d_lines(self) -> np.ndarray:
        if self._variants is None:
            self._variants = {}
        hit = self._variants.get("sel3d")
        if hit is None:
            color = np.asarray(SELECT_COLOR_3D, dtype=np.float32)
            hit = np.hstack([self.lines, np.tile(color, (len(self.lines), 1))])
            self._variants["sel3d"] = hit
        return hit


_BOX_FACES = [
    ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
    ((0, 0, -1), [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)]),
    ((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
    ((-1, 0, 0), [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)]),
    ((0, 1, 0), [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)]),
    ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
]


def _polygons_to_arrays(polys: list[tuple[tuple[float, float, float], list]], colors: list) -> tuple[np.ndarray, np.ndarray]:
    tris: list[list[float]] = []
    lines: list[tuple[float, float, float]] = []
    for (normal, poly), color in zip(polys, colors):
        for i in range(1, len(poly) - 1):
            for p in (poly[0], poly[i], poly[i + 1]):
                tris.append([*p, *normal, *color])
        for i in range(len(poly)):
            lines.append(poly[i])
            lines.append(poly[(i + 1) % len(poly)])
    return (
        np.asarray(tris, dtype=np.float32).reshape(-1, 9),
        np.asarray(lines, dtype=np.float32).reshape(-1, 3),
    )


def build_object_mesh(obj: MapObject) -> ObjectMesh | None:
    if isinstance(obj, Solid):
        polys, colors = [], []
        for face, poly in zip(obj.faces, obj.polygons()):
            if poly:
                polys.append((face.plane.normal, poly))
                colors.append(material_color(face.material))
        tris, lines = _polygons_to_arrays(polys, colors)
        c = obj.editor.color
        return ObjectMesh(tris, lines, (c[0] / 255, c[1] / 255, c[2] / 255))
    bbox = object_bbox(obj)
    if bbox is None:
        return None
    color = entity_color(obj.classname)
    lo, hi = bbox.mins, bbox.maxs
    polys = []
    for normal, corners in _BOX_FACES:
        polys.append((normal, [tuple(lo[i] if c[i] == 0 else hi[i] for i in range(3)) for c in corners]))
    tris, lines = _polygons_to_arrays(polys, [color] * len(polys))
    return ObjectMesh(tris, lines, color)


@dataclass
class SceneArrays:
    """Zusammengefügte Arrays für die GPU."""

    faces: np.ndarray       # (n, 10): Position, Normale, Farbe, ausgewählt (0/1)
    lines2d: np.ndarray     # (m, 6): Position, Farbe
    lines_sel: np.ndarray   # (k, 6): Kanten der Auswahl für die 3D-Ansicht
    version: int


class SceneMesh:
    def __init__(self, doc: MapDocument) -> None:
        self.doc = doc
        self._cache: dict[int, tuple[MapObject, ObjectMesh | None]] = {}
        self._selection: frozenset[int] = frozenset()
        self.version = next(_versions)
        self._arrays: SceneArrays | None = None
        doc.subscribe(self._on_change)

    def detach(self) -> None:
        self.doc.unsubscribe(self._on_change)

    def _on_change(self, cs: ChangeSet) -> None:
        for oid in cs.modified | cs.removed:
            self._cache.pop(oid, None)
        self.version = next(_versions)

    def set_selection(self, ids: frozenset[int]) -> None:
        if ids != self._selection:
            self._selection = ids
            self.version = next(_versions)

    def _mesh(self, obj: MapObject) -> ObjectMesh | None:
        hit = self._cache.get(obj.id)
        if hit is not None and hit[0] is obj:
            return hit[1]
        mesh = build_object_mesh(obj)
        self._cache[obj.id] = (obj, mesh)
        return mesh

    def arrays(self) -> SceneArrays:
        if self._arrays is not None and self._arrays.version == self.version:
            return self._arrays
        faces_unsel, faces_sel, lines_unsel, lines_sel2d, lines_sel3d = [], [], [], [], []
        for obj in self.doc.objects():
            if obj.editor.hidden:
                continue
            owner = owner_id(obj)
            if owner is not None:
                if isinstance(obj, Solid) and obj.parent_id is None:
                    continue  # Kollisions-Brush eines Bausteins: deckungsgleich mit dem sichtbaren Teil
                parent = self.doc.get(owner)
                if isinstance(parent, Entity) and parent.editor.hidden:
                    continue
            mesh = self._mesh(obj)
            if mesh is None:
                continue
            selected = obj.id in self._selection or (owner is not None and owner in self._selection)
            tris, lines = mesh.variant(selected)
            (faces_sel if selected else faces_unsel).append(tris)
            (lines_sel2d if selected else lines_unsel).append(lines)
            if selected:
                lines_sel3d.append(mesh.selected_3d_lines())

        def cat(parts: list[np.ndarray], width: int) -> np.ndarray:
            return np.concatenate(parts).astype(np.float32) if parts else np.zeros((0, width), dtype=np.float32)

        self._arrays = SceneArrays(
            faces=cat(faces_unsel + faces_sel, 10),
            lines2d=cat(lines_unsel + lines_sel2d, 6),
            lines_sel=cat(lines_sel3d, 6),
            version=self.version,
        )
        return self._arrays
