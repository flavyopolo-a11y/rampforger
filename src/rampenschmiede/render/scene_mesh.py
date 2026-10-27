"""Baut aus dem Dokument Vertex-Arrays für alle Ansichten (ohne OpenGL).

Pro Objekt werden die Arrays einmal berechnet und zwischengespeichert. Ein ChangeSet
verwirft nur die betroffenen Einträge. Die Arrays aller Objekte werden zu einem Puffer
zusammengefügt, ausgewählte Objekte zuletzt, damit sie in 2D obenauf liegen.

Zell-Batching (nur betroffene Raumzellen neu hochladen) folgt in der Komfort-Etappe.
"""
from __future__ import annotations

import colorsys
import itertools
import math
import zlib
from dataclasses import dataclass

import numpy as np

from ..core.blocks import is_block_root
from ..core.model import (
    ChangeSet,
    Entity,
    Face,
    MapDocument,
    MapObject,
    Solid,
    object_bbox,
    owner_id,
)
from .textures import TextureAtlas

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
    tris: np.ndarray   # (n, 12): Position, Normale, Farbe, UV, Textur-Ebene (0 = keine)
    lines: np.ndarray  # (m, 3): Kanten als Linienpaare
    color2d: tuple[float, float, float]
    #: Kanten für die 3D-Ansicht (ohne Knicke in fast ebenen Flächen), (k, 3); None = wie `lines`
    edges3d: np.ndarray | None = None
    _variants: dict | None = None

    def edges_3d(self) -> np.ndarray:
        """Kanten für die 3D-Ansicht mit Platzhalter-Farbe (der Shader färbt sie dunkel)."""
        if self._variants is None:
            self._variants = {}
        hit = self._variants.get("edges3d")
        if hit is None:
            edges = self.lines if self.edges3d is None else self.edges3d
            hit = np.hstack([edges, np.zeros((len(edges), 3), dtype=np.float32)])
            self._variants["edges3d"] = hit
        return hit

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


def _uv(face: Face, p, size: tuple[int, int]) -> tuple[float, float]:
    """Texturkoordinate wie in Source: (Punkt · Achse / Skalierung + Verschiebung) / Texturgröße."""
    u, v = face.uaxis, face.vaxis
    su = u.scale or 1.0
    sv = v.scale or 1.0
    tu = (p[0] * u.x + p[1] * u.y + p[2] * u.z) / su + u.offset
    tv = (p[0] * v.x + p[1] * v.y + p[2] * v.z) / sv + v.offset
    return tu / size[0], tv / size[1]


def _polygons_to_arrays(polys: list[tuple[tuple[float, float, float], list]], colors: list,
                        textures: list | None = None) -> tuple[np.ndarray, np.ndarray]:
    """textures: je Polygon (Face, Ebene, (Breite, Höhe)) oder None."""
    tris: list[list[float]] = []
    lines: list[tuple[float, float, float]] = []
    for k, ((normal, poly), color) in enumerate(zip(polys, colors)):
        tex = textures[k] if textures else None
        for i in range(1, len(poly) - 1):
            for p in (poly[0], poly[i], poly[i + 1]):
                if tex is None:
                    tris.append([*p, *normal, *color, 0.0, 0.0, 0.0])
                else:
                    face, layer, size = tex
                    tris.append([*p, *normal, *color, *_uv(face, p, size), float(layer)])
        for i in range(len(poly)):
            lines.append(poly[i])
            lines.append(poly[(i + 1) % len(poly)])
    return (
        np.asarray(tris, dtype=np.float32).reshape(-1, 12),
        np.asarray(lines, dtype=np.float32).reshape(-1, 3),
    )


#: Kanten zwischen Seiten, die weniger als so viel Grad abknicken, zeichnet die 3D-Ansicht nicht
SOFT_EDGE_DEG = 12.0
_SOFT_COS = math.cos(math.radians(SOFT_EDGE_DEG))
NODRAW = "TOOLS/TOOLSNODRAW"


def feature_edges(faces: list[Face], polys: list, hide_nodraw: bool = False) -> np.ndarray:
    """Kanten, die in 3D gezeichnet werden: nur echte Knicke. Wo das Runden auf ganze Units
    eine Fläche leicht knickt (Kurven), entsteht sonst ein Gewirr dunkler Linien.
    `hide_nodraw`: Kanten zu unsichtbaren Seiten weglassen (Nähte zwischen Rampen-Segmenten)."""
    owners: dict[tuple, list[int]] = {}
    ends: dict[tuple, tuple] = {}
    for k, poly in enumerate(polys):
        if not poly:
            continue
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            ka = tuple(round(c, 2) for c in a)
            kb = tuple(round(c, 2) for c in b)
            key = (ka, kb) if ka <= kb else (kb, ka)
            owners.setdefault(key, []).append(k)
            ends.setdefault(key, (a, b))
    out: list = []
    for key, ks in owners.items():
        if len(ks) == 2:
            fa, fb = faces[ks[0]], faces[ks[1]]
            na, nb = fa.plane.normal, fb.plane.normal
            if na[0] * nb[0] + na[1] * nb[1] + na[2] * nb[2] > _SOFT_COS:
                continue
            if hide_nodraw and NODRAW in (fa.material.upper(), fb.material.upper()):
                continue
        out += ends[key]
    return np.asarray(out, dtype=np.float32).reshape(-1, 3)


def build_object_mesh(obj: MapObject, atlas: TextureAtlas | None = None, block_part: bool = False) -> ObjectMesh | None:
    if isinstance(obj, Solid):
        polys, colors, textures = [], [], []
        all_polys = obj.polygons()
        for face, poly in zip(obj.faces, all_polys):
            # Unsichtbare Seiten von Rampen liegen fast alle innen (Nähte zwischen Segmenten) und
            # blitzen sonst an den Kanten gelb durch
            if poly and not (block_part and face.material.upper() == NODRAW):
                polys.append((face.plane.normal, poly))
                colors.append(material_color(face.material))
                slot = atlas.slot(face.material) if atlas is not None else None
                textures.append((face, slot.layer, (slot.width, slot.height)) if slot else None)
        tris, lines = _polygons_to_arrays(polys, colors, textures)
        c = obj.editor.color
        edges = feature_edges(list(obj.faces), all_polys, hide_nodraw=block_part)
        return ObjectMesh(tris, lines, (c[0] / 255, c[1] / 255, c[2] / 255), edges)
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

    faces: np.ndarray       # (n, 13): Position, Normale, Farbe, UV, Textur-Ebene, ausgewählt (0/1)
    lines2d: np.ndarray     # (m, 6): Position, Farbe
    lines_sel: np.ndarray   # (k, 6): Kanten der Auswahl für die 3D-Ansicht
    lines3d: np.ndarray     # (j, 6): Kanten für die 3D-Ansicht (ohne weiche Knicke)
    version: int


class SceneMesh:
    def __init__(self, doc: MapDocument, atlas: TextureAtlas | None = None) -> None:
        self.doc = doc
        self.atlas = atlas
        self._atlas_generation = atlas.generation if atlas else 0
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

    def textures_changed(self) -> None:
        """Nach einem Wechsel der Material-Bibliothek alle Meshes neu bauen."""
        self._cache.clear()
        self.version = next(_versions)

    def _mesh(self, obj: MapObject) -> ObjectMesh | None:
        hit = self._cache.get(obj.id)
        if hit is not None and hit[0] is obj:
            return hit[1]
        parent_id = getattr(obj, "parent_id", None)
        parent = self.doc.get(parent_id) if parent_id is not None else None
        mesh = build_object_mesh(obj, self.atlas, block_part=is_block_root(parent))
        self._cache[obj.id] = (obj, mesh)
        return mesh

    def arrays(self) -> SceneArrays:
        if self.atlas is not None and self.atlas.generation != self._atlas_generation:
            self._atlas_generation = self.atlas.generation
            self.textures_changed()
        if self._arrays is not None and self._arrays.version == self.version:
            return self._arrays
        faces_unsel, faces_sel, lines_unsel, lines_sel2d, lines_sel3d, edges3d = [], [], [], [], [], []
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
            edges3d.append(mesh.edges_3d())
            if selected:
                lines_sel3d.append(mesh.selected_3d_lines())

        def cat(parts: list[np.ndarray], width: int) -> np.ndarray:
            return np.concatenate(parts).astype(np.float32) if parts else np.zeros((0, width), dtype=np.float32)

        self._arrays = SceneArrays(
            faces=cat(faces_unsel + faces_sel, 13),
            lines2d=cat(lines_unsel + lines_sel2d, 6),
            lines_sel=cat(lines_sel3d, 6),
            lines3d=cat(edges3d, 6),
            version=self.version,
        )
        return self._arrays
