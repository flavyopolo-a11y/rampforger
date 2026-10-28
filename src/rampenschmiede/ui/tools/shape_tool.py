"""Formen-Werkzeug: Block, Keil, Zylinder, Bogen, Treppe.

In einer 2D-Ansicht einen Rahmen aufziehen, in einer zweiten die Höhe anpassen,
dann Enter drücken. Die Tiefe übernimmt der Rahmen von der letzten Form (wie Hammer).
In der 3D-Ansicht setzt ein Klick auf eine Fläche den Rahmen direkt darauf.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen

from ...core.commands import AddObjects, solids_from_faces
from ...core.geometry import primitives
from ...core.mathutil import BBox
from ...core.model import Solid
from ...i18n import N_, tr
from .base import Tool, box_lines, pick_3d

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

SHAPES = {
    "block": N_("Block"),
    "wedge": N_("Keil"),
    "cylinder": N_("Zylinder"),
    "arch": N_("Bogen"),
    "stairs": N_("Treppe"),
    "spike": N_("Spitze"),
    "sphere": N_("Kugel"),
    "torus": N_("Torus"),
}

DRAFT_COLOR = (1.0, 1.0, 1.0)
SHAPE_HINTS = {
    "block": tr("Quader. Der Grundbaustein für Böden, Wände und Plattformen."),
    "wedge": tr("Keil mit schräger Oberseite, z. B. für Rampen zum Hochlaufen."),
    "cylinder": tr("Säule mit einstellbarer Seitenzahl."),
    "arch": tr("Bogen oder Ring aus Segmenten, mit Wandstärke."),
    "stairs": tr("Treppe mit einstellbarer Stufenzahl."),
    "spike": tr("Kegel oder Pyramide (3 bis 64 Seiten), Spitze oben."),
    "sphere": tr("Kugel aus einem Brush. Mehr Seiten = runder (höchstens 12, mehr erlaubt vbsp nicht)."),
    "torus": tr("Ring mit rundem Querschnitt; Wandstärke = Dicke des Rings."),
}


class _ShapeSignals(QObject):
    shape_changed = Signal(str)


@dataclass
class ShapeOptions:
    shape: str = "block"
    sides: int = 8
    wall: int = 16
    arc: float = 180.0
    start_angle: float = 0.0
    steps: int = 8
    stairs_direction: str = "+y"
    wedge_high: str = "-y"  # Seite, zu der die Schräge ansteigt
    extra: dict = field(default_factory=dict)


class ShapeTool(Tool):
    name = "shape"
    label = "Formen"
    shortcut = "Shift+B"
    hint = "Rahmen in einer 2D-Ansicht aufziehen oder in 3D auf eine Fläche klicken, dann Enter"

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.options = ShapeOptions()
        self.signals = _ShapeSignals()
        self.draft: BBox | None = None
        self.last_box = BBox((0, 0, 0), (64, 64, 64))
        self._drag_start: tuple[float, float] | None = None
        self._drag_mode: str | None = None  # new | move

    def set_shape(self, shape: str) -> None:
        if shape in SHAPES and shape != self.options.shape:
            self.options.shape = shape
            self.signals.shape_changed.emit(shape)
            self.editor.redraw_requested.emit()

    def create_at(self, point: tuple[float, float, float]) -> bool:
        """Form mit der zuletzt benutzten Größe an einem Punkt erstellen (Bibliothek, Ziehen)."""
        size = self.last_box.size
        snap = self.editor.snap
        mins = (snap(point[0] - size[0] / 2), snap(point[1] - size[1] / 2), snap(point[2]))
        self.draft = BBox(mins, tuple(m + d for m, d in zip(mins, size)))  # type: ignore[arg-type]
        return self.create()

    # ---- 2D ---------------------------------------------------------------------
    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        world = vp.to_world(e.position())
        if self.draft is not None and self._draft_rect(vp).adjusted(-3, -3, 3, 3).contains(e.position()):
            self._drag_mode = "move"
        else:
            self._drag_mode = "new"
        self._drag_start = world
        self._drag_box = self.draft or self.last_box

    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if self._drag_start is None:
            return
        cur = vp.to_world(e.position())
        h, v, depth = vp.axes()
        base = self._drag_box
        mins, maxs = list(base.mins), list(base.maxs)
        snap = self.editor.snap
        if self._drag_mode == "move":
            dh = snap(base.mins[h] + cur[0] - self._drag_start[0]) - base.mins[h]
            dv = snap(base.mins[v] + cur[1] - self._drag_start[1]) - base.mins[v]
            mins[h] += dh
            maxs[h] += dh
            mins[v] += dv
            maxs[v] += dv
        else:
            a = (snap(self._drag_start[0]), snap(self._drag_start[1]))
            b = (snap(cur[0]), snap(cur[1]))
            mins[h], maxs[h] = min(a[0], b[0]), max(a[0], b[0])
            mins[v], maxs[v] = min(a[1], b[1]), max(a[1], b[1])
            if maxs[h] == mins[h] or maxs[v] == mins[v]:
                return
        self.draft = BBox(tuple(mins), tuple(maxs))  # type: ignore[arg-type]
        self.editor.redraw_requested.emit()

    def release_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        self._drag_start = None
        self._drag_mode = None
        if self.draft is not None:
            self.editor.status_message.emit(tr("Enter erstellt die Form, Esc verwirft den Rahmen"))

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        if self.draft is not None and self._draft_rect(vp).contains(pos):
            return Qt.SizeAllCursor
        return Qt.CrossCursor

    def _draft_rect(self, vp: "Viewport") -> QRectF:
        if self.draft is None:
            return QRectF()
        h, v, _ = vp.axes()
        return QRectF(vp.to_screen(self.draft.mins[h], self.draft.mins[v]),
                      vp.to_screen(self.draft.maxs[h], self.draft.maxs[v])).normalized()

    # ---- 3D: auf Fläche setzen -------------------------------------------------------
    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        origin, direction = vp.ray(e.position())
        hit = pick_3d(self.editor, origin, direction, roots=False)
        normal = np.array([0.0, 0.0, 1.0])
        if hit is None:
            # Kein Treffer: auf die Ebene z = 0 setzen, falls der Strahl sie trifft
            if abs(direction[2]) < 1e-6 or (t := -origin[2] / direction[2]) < 0:
                return
            point = origin + direction * t
        else:
            point = origin + direction * hit[1]
            if isinstance(hit[0], Solid):
                face = min(hit[0].faces, key=lambda f: abs(f.plane.distance(tuple(point))))
                normal = np.array(face.plane.normal)
        size = np.array(self.last_box.size, dtype=float)
        # Rahmen so legen, dass er auf der getroffenen Fläche aufliegt statt in ihr zu stecken
        center = point + normal * size / 2
        snap = self.editor.snap
        mins = [snap(center[i] - size[i] / 2) for i in range(3)]
        main = int(np.argmax(np.abs(normal)))
        if normal[main] > 0:
            mins[main] = int(np.ceil(point[main] - 1e-6))
        else:
            mins[main] = int(np.floor(point[main] + 1e-6)) - int(size[main])
        self.draft = BBox(tuple(mins), tuple(m + s for m, s in zip(mins, size)))  # type: ignore[arg-type]
        self.editor.status_message.emit(tr("Enter erstellt die Form, Esc verwirft den Rahmen"))
        self.editor.redraw_requested.emit()

    # ---- Erstellen ----------------------------------------------------------------------
    def build(self, box: BBox) -> list[tuple]:
        o = self.options
        mat = self.editor.current_material
        if o.shape == "wedge":
            return primitives.wedge(box.mins, box.maxs, mat, o.wedge_high)  # type: ignore[arg-type]
        if o.shape == "cylinder":
            return primitives.cylinder(box.mins, box.maxs, o.sides, material=mat)
        if o.shape == "arch":
            return primitives.arch(box.mins, box.maxs, o.sides, o.wall, o.arc, o.start_angle, material=mat)
        if o.shape == "spike":
            return primitives.spike(box.mins, box.maxs, o.sides, material=mat)
        if o.shape == "sphere":
            return primitives.sphere(box.mins, box.maxs, o.sides, material=mat)
        if o.shape == "torus":
            return primitives.torus(box.mins, box.maxs, o.sides, o.wall, material=mat)
        if o.shape == "stairs":
            return primitives.stairs(box.mins, box.maxs, o.steps, o.stairs_direction, material=mat)  # type: ignore[arg-type]
        return primitives.block(box.mins, box.maxs, mat)

    def create(self) -> bool:
        if self.draft is None:
            return False
        parts = self.build(self.draft)
        if not parts:
            self.editor.status_message.emit(tr("Mit diesen Maßen lässt sich keine gültige Form bauen"))
            return False
        solids = solids_from_faces(self.editor.doc, parts)
        self.editor.run(AddObjects(solids, SHAPES[self.options.shape] + " erstellen"))
        self.editor.set_selection(s.id for s in solids)
        self.last_box = self.draft
        self.draft = None
        self.editor.redraw_requested.emit()
        return True

    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            return self.create()
        if e.key() == Qt.Key_Escape and self.draft is not None:
            self.draft = None
            self.editor.redraw_requested.emit()
            return True
        return False

    def deactivate(self) -> None:
        self.draft = None

    # ---- Zeichnen -------------------------------------------------------------------------
    def lines_2d(self, vp: "Viewport") -> np.ndarray | None:
        return box_lines(self.draft, DRAFT_COLOR) if self.draft else None

    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        return box_lines(self.draft, DRAFT_COLOR) if self.draft else None

    def paint_2d(self, vp: "Viewport", p: QPainter) -> None:
        if self.draft is None:
            return
        rect = self._draft_rect(vp)
        p.setPen(QPen(QColor(255, 255, 255), 1, Qt.DotLine))
        h, v, _ = vp.axes()
        size = self.draft.size
        fm = p.fontMetrics()
        w_txt, h_txt = f"{size[h]:g}", f"{size[v]:g}"
        p.setPen(QColor(255, 255, 255))
        p.drawText(QPointF(rect.center().x() - fm.horizontalAdvance(w_txt) / 2, rect.top() - 6), w_txt)
        p.drawText(QPointF(rect.right() + 6, rect.center().y() + fm.ascent() / 2), h_txt)
