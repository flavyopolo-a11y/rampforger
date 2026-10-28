"""Basisklasse für Werkzeuge und gemeinsame Hilfen (Picking, Box-Linien)."""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QPainter

from ...core.geometry.brush import ray_intersect_solid
from ...core.geometry.displacement import is_displacement_solid, solid_ray_face, surfaces
from ...core.mathutil import BBox
from ...core.model import Entity, MapObject, Solid, object_bbox, owner_id

if TYPE_CHECKING:
    from ..editor import EditorContext
    from ..viewports.viewport import Viewport


class Tool:
    name = "tool"
    label = "Werkzeug"
    shortcut = ""
    hint = ""

    def __init__(self, editor: "EditorContext") -> None:
        self.editor = editor

    def activate(self) -> None:
        if self.hint:
            self.editor.status_message.emit(self.hint)

    def deactivate(self) -> None:
        pass

    # Maus
    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None: ...
    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None: ...
    def release_2d(self, vp: "Viewport", e: QMouseEvent) -> None: ...
    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None: ...
    def move_3d(self, vp: "Viewport", e: QMouseEvent) -> None: ...
    def release_3d(self, vp: "Viewport", e: QMouseEvent) -> None: ...

    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        return False

    def wants_key(self, key: int) -> bool:
        return False

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        return Qt.ArrowCursor

    def cursor_3d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        return Qt.ArrowCursor

    # Zeichnen
    def lines_2d(self, vp: "Viewport") -> np.ndarray | None:
        return None

    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        return None

    def paint_2d(self, vp: "Viewport", p: QPainter) -> None: ...
    def paint_3d(self, vp: "Viewport", p: QPainter) -> None: ...


# ---- Hilfen ------------------------------------------------------------------------

def selection_root(editor: "EditorContext", obj: MapObject) -> MapObject:
    """Ein Brush einer Brush-Entity oder eines Bausteins wird als das Ganze ausgewählt."""
    owner = owner_id(obj)
    if owner is not None:
        parent = editor.doc.get(owner)
        if parent is not None:
            return parent
    return obj


def _visible(editor: "EditorContext", obj: MapObject) -> bool:
    if not editor.selectable(obj):
        return False
    owner = owner_id(obj)
    if owner is not None:
        parent = editor.doc.get(owner)
        return parent is None or editor.selectable(parent)
    return True


def _brush_entity_ids(editor: "EditorContext") -> set[int]:
    return {o for s in editor.doc.solids() if (o := owner_id(s)) is not None}


def pick_2d(editor: "EditorContext", vp: "Viewport", pos: QPointF) -> MapObject | None:
    """Objekt unter dem Mauszeiger in einer 2D-Ansicht: das kleinste, dessen Umriss den
    Punkt enthält. Eine Toleranz von 4 Pixeln erleichtert das Treffen dünner Brushes."""
    h_axis, v_axis, _ = vp.axes()
    wh, wv = vp.to_world(pos)
    tol = 4 / vp.cam2d.zoom
    best: tuple[float, MapObject] | None = None
    brush_entities = _brush_entity_ids(editor)
    for obj in editor.doc.objects():
        if not _visible(editor, obj):
            continue
        if isinstance(obj, Entity) and obj.id in brush_entities:
            continue  # Brush-Entities werden über ihre Brushes getroffen
        bb = object_bbox(obj)
        if bb is None:
            continue
        if bb.mins[h_axis] - tol <= wh <= bb.maxs[h_axis] + tol and bb.mins[v_axis] - tol <= wv <= bb.maxs[v_axis] + tol:
            area = (bb.maxs[h_axis] - bb.mins[h_axis] + 1) * (bb.maxs[v_axis] - bb.mins[v_axis] + 1)
            if best is None or area < best[0]:
                best = (area, obj)
    return selection_root(editor, best[1]) if best else None


def _ray_box(origin: np.ndarray, direction: np.ndarray, bb: BBox) -> float | None:
    t0, t1 = -1e30, 1e30
    for i in range(3):
        if abs(direction[i]) < 1e-12:
            if origin[i] < bb.mins[i] or origin[i] > bb.maxs[i]:
                return None
            continue
        a = (bb.mins[i] - origin[i]) / direction[i]
        b = (bb.maxs[i] - origin[i]) / direction[i]
        if a > b:
            a, b = b, a
        t0, t1 = max(t0, a), min(t1, b)
        if t0 > t1:
            return None
    if t1 < 0:
        return None
    return max(t0, 0.0)


def hit_solid_face(solid: Solid, origin, direction) -> tuple[float, int | None] | None:
    """(Abstand, Seite) bis zum Brush. Gelände-Brushes trifft man nur auf ihrer sichtbaren
    Displacement-Fläche (die übrigen Seiten gibt es im Spiel nicht); die Seite ist dann bekannt."""
    if is_displacement_solid(solid) and surfaces(solid):
        return solid_ray_face(solid, origin, direction)
    t = ray_intersect_solid(solid, origin, direction)
    return (t, None) if t is not None else None


def hit_solid(solid: Solid, origin, direction) -> float | None:
    hit = hit_solid_face(solid, origin, direction)
    return hit[0] if hit is not None else None


def pick_3d(editor: "EditorContext", origin: np.ndarray, direction: np.ndarray,
            roots: bool = True) -> tuple[MapObject, float] | None:
    best: tuple[MapObject, float] | None = None
    o = (float(origin[0]), float(origin[1]), float(origin[2]))
    d = (float(direction[0]), float(direction[1]), float(direction[2]))
    brush_entities = _brush_entity_ids(editor)
    for obj in editor.doc.objects():
        if not _visible(editor, obj):
            continue
        bb = object_bbox(obj)
        if bb is None:
            continue
        t = _ray_box(origin, direction, bb)
        if t is None or (best is not None and t >= best[1]):
            continue
        if isinstance(obj, Solid):
            t = hit_solid(obj, o, d)
            if t is None:
                continue
        elif obj.id in brush_entities:
            continue
        if best is None or t < best[1]:
            best = (obj, t)
    if best is None:
        return None
    return (selection_root(editor, best[0]) if roots else best[0]), best[1]


BOX_EDGES = [
    (0, 1), (1, 3), (3, 2), (2, 0),
    (4, 5), (5, 7), (7, 6), (6, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
]


def box_lines(bb: BBox, color: tuple[float, float, float]) -> np.ndarray:
    corners = [
        (bb.mins[0] if i & 1 == 0 else bb.maxs[0],
         bb.mins[1] if i & 2 == 0 else bb.maxs[1],
         bb.mins[2] if i & 4 == 0 else bb.maxs[2])
        for i in range(8)
    ]
    out = []
    for a, b in BOX_EDGES:
        out.append([*corners[a], *color])
        out.append([*corners[b], *color])
    return np.asarray(out, dtype=np.float32)
