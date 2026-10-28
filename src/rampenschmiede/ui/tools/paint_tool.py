"""Rampen malen: Vorlage links in der Bibliothek anklicken, Regler nach Wunsch stellen, dann in
einer Ansicht vom Anfang zum Ende der Rampe ziehen. Die Vorschau hängt am Mauszeiger, beim
Loslassen wird gebaut. Ein einfacher Klick setzt die Vorlage so ab, wie sie ist.

Von oben bestimmt der Strich Länge und Richtung (Kurven: Radius und Richtung). Von vorne oder
von der Seite bestimmt der Anfangspunkt zusätzlich die Höhe. In 3D wird auf der getroffenen
Fläche oder auf dem Boden gemalt.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen

from ...core.model import Solid
from ...core.surf.catalog import Placement, generate
from ...core.surf.paint import MIN_STROKE, fit_stroke
from ...i18n import tr
from .base import Tool, pick_3d

if TYPE_CHECKING:
    from ..panels.library_panel import LibraryPanel
    from ..viewports.viewport import Viewport

GHOST_COLOR = (1.0, 0.62, 0.2)
GHOST_LIGHT = (0.3, 0.5, 0.81)


class PaintTool(Tool):
    name = "paint"
    label = "Malen"
    shortcut = "Shift+R"
    hint = ("Vorlage links wählen, dann vom Anfang zum Ende der Rampe ziehen. Klick setzt sie ab, "
            "Esc beendet das Malen")

    def __init__(self, editor, library: "LibraryPanel") -> None:
        super().__init__(editor)
        self.library = library
        self.hover: tuple[float, float, float] | None = None
        self.start: tuple[float, float, float] | None = None
        self.end: tuple[float, float] | None = None
        self.yaw = 0.0
        self.z = 0.0
        self._cache: tuple[object, np.ndarray | None, np.ndarray | None] | None = None
        # Andere Vorlage oder Regler: Vorschau sofort neu zeichnen
        changed = getattr(library, "template_changed", None)
        if changed is not None:
            changed.connect(editor.redraw_requested.emit)

    def deactivate(self) -> None:
        self.hover = self.start = self.end = None

    # ---- Vorlage und Vorschau ------------------------------------------------------------
    def template(self):
        return self.library.current_template()

    def plan(self) -> tuple[str, dict, Placement] | None:
        """Was beim Loslassen gebaut würde: (Vorlage, Werte, Platzierung)."""
        t = self.template()
        if t is None:
            return None
        values = self.library.insert_values(t)
        snap = self.editor.snap
        if self.start is not None and self.end is not None:
            values, at = fit_stroke(t, values, self.start, self.end, snap=snap)
            if math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1]) < MIN_STROKE:
                at = Placement(at.x, at.y, at.z, self.yaw)
            at = Placement(snap(at.x), snap(at.y), snap(at.z), at.yaw)
            return t.key, values, at
        if self.hover is None:
            return None
        x, y, z = self.hover
        return t.key, values, Placement(snap(x), snap(y), snap(z), self.yaw)

    def _ghost_arrays(self) -> tuple[np.ndarray | None, np.ndarray | None]:
        """(Kanten, Flächen) der Vorschau, solange sich die Vorlage nicht ändert zwischengespeichert."""
        plan = self.plan()
        if plan is None:
            return None, None
        key = (plan[0], tuple(sorted(plan[1].items())), plan[2])
        if self._cache is not None and self._cache[0] == key:
            return self._cache[1], self._cache[2]
        try:
            gen = generate(plan[0], plan[1], plan[2])
        except Exception:  # noqa: BLE001 - ungültige Zwischenwerte beim Ziehen: keine Vorschau
            gen = None
        rows: list[list[float]] = []
        tris: list[list[float]] = []
        for faces in gen.face_sets if gen else []:
            for face, poly in zip(faces, Solid(id=0, faces=tuple(faces)).polygons()):
                if not poly:
                    continue
                for k in range(len(poly)):
                    rows.append([*poly[k], *GHOST_COLOR])
                    rows.append([*poly[(k + 1) % len(poly)], *GHOST_COLOR])
                n = face.plane.normal
                shade = 0.55 + 0.45 * max(0.0, n[0] * GHOST_LIGHT[0] + n[1] * GHOST_LIGHT[1] + n[2] * GHOST_LIGHT[2])
                color = [c * shade for c in GHOST_COLOR]
                for k in range(1, len(poly) - 1):
                    tris += [[*poly[0], *color], [*poly[k], *color], [*poly[k + 1], *color]]
        lines = np.asarray(rows, dtype=np.float32).reshape(-1, 6) if rows else None
        faces_arr = np.asarray(tris, dtype=np.float32).reshape(-1, 6) if tris else None
        self._cache = (key, lines, faces_arr)
        return lines, faces_arr

    def ghost(self) -> np.ndarray | None:
        return self._ghost_arrays()[0]

    def place(self) -> int | None:
        plan = self.plan()
        if plan is None:
            self.editor.status_message.emit(tr("Erst links eine Vorlage anklicken"))
            return None
        key, values, at = plan
        root = self.library.place(key, values, at)
        if root is not None:
            self.yaw, self.z = at.yaw, at.z
            self.editor.status_message.emit(tr("Gebaut. Weiter malen, Regler links ändern oder Esc"))
        return root

    # ---- Punkte aus der Maus -----------------------------------------------------------
    def _point_2d(self, vp: "Viewport", pos: QPointF) -> tuple[float, float, float]:
        h, v, _ = vp.axes()
        wh, wv = vp.to_world(pos)
        base = list(self.start or self.hover or (0.0, 0.0, self.z))
        if (h, v) == (0, 1):
            base[2] = self.z if self.start is None else base[2]
        base[h], base[v] = wh, wv
        return (base[0], base[1], base[2])

    def _point_3d(self, vp: "Viewport", pos: QPointF) -> tuple[float, float, float] | None:
        origin, direction = vp.ray(pos)
        if self.start is not None:
            # beim Ziehen auf der Höhe des Anfangs bleiben
            z = self.start[2]
        else:
            hit = pick_3d(self.editor, origin, direction, roots=False)
            if hit is not None:
                p = origin + direction * hit[1]
                return (float(p[0]), float(p[1]), float(p[2]))
            z = self.z
        if abs(direction[2]) < 1e-6:
            return None
        t = (z - origin[2]) / direction[2]
        if t < 0:
            return None
        p = origin + direction * t
        return (float(p[0]), float(p[1]), z)

    def _press(self, point) -> None:
        if point is None:
            return
        self.start, self.end = point, (point[0], point[1])
        self.editor.redraw_requested.emit()

    def _move(self, point) -> None:
        if point is None:
            return
        if self.start is not None:
            self.end = (point[0], point[1])
        else:
            self.hover = point
        self.editor.redraw_requested.emit()

    def _release(self) -> None:
        if self.start is not None:
            self.place()
        self.hover = (self.start[0], self.start[1], self.start[2]) if self.start else self.hover
        self.start = self.end = None
        self.editor.redraw_requested.emit()

    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._press(self._point_2d(vp, e.position()))

    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        self._move(self._point_2d(vp, e.position()))

    def release_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._release()

    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._press(self._point_3d(vp, e.position()))

    def move_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        self._move(self._point_3d(vp, e.position()))

    def release_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._release()

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        return Qt.CrossCursor

    def cursor_3d(self, vp: "Viewport", pos) -> Qt.CursorShape:
        return Qt.CrossCursor

    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        if e.key() == Qt.Key_Escape:
            if self.start is not None:
                self.start = self.end = None
                self.editor.redraw_requested.emit()
            else:
                self.editor.set_tool("select")
            return True
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.hover is not None:
            return self.place() is not None
        return False

    # ---- Zeichnen -----------------------------------------------------------------------
    def lines_2d(self, vp: "Viewport") -> np.ndarray | None:
        return self.ghost()

    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        # In 3D zeigen die durchscheinenden Flächen die Form; die vielen Kanten einer Kurve
        # würden sie nur zu einem orangen Klumpen machen
        lines, faces = self._ghost_arrays()
        return None if faces is not None else lines

    def tris_3d(self, vp: "Viewport") -> np.ndarray | None:
        return self._ghost_arrays()[1]

    def paint_2d(self, vp: "Viewport", p: QPainter) -> None:
        if self.start is None or self.end is None or vp.axes()[:2] != (0, 1):
            return
        a = vp.to_screen(self.start[0], self.start[1])
        b = vp.to_screen(self.end[0], self.end[1])
        p.setPen(QPen(QColor(255, 160, 50), 1, Qt.DashLine))
        p.drawLine(a, b)
        length = math.hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])
        p.setPen(QColor(255, 200, 120))
        p.drawText(b + QPointF(8, -8), f"{self.editor.snap(length)} u")


__all__ = ["PaintTool"]
