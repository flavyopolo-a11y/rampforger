"""Wände malen (Shift+K): Linienzug klicken, daraus werden verbundene Wände.

In der Ansicht „Oben“ oder in 3D auf den Boden klicken setzt Punkte (am Raster). Ein Klick auf
den ersten Punkt schließt den Raum, ein zweiter Klick auf den letzten Punkt oder Enter beendet
den Zug, Rücktaste nimmt den letzten Punkt zurück, Esc verwirft. In 3D bestimmt der erste
Klick die Unterkante. Die Wände werden eine Gruppe: ein Klick wählt alle.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter

from ...core.commands import AddObjects, solids_from_faces
from ...core.geometry.walls import wall_faces, wall_outlines
from ...core.organize import new_group_id
from .base import Tool, pick_3d

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

P2 = tuple[float, float]
PREVIEW = (1.0, 0.6, 0.15)
CLOSE_PX = 10


@dataclass
class WallOptions:
    height: int = 256
    thickness: int = 16
    bottom: int = 0
    group: bool = True


class WallTool(Tool):
    name = "wall"
    label = "Wände"
    shortcut = "Shift+K"
    hint = ("Wände: in „Oben“ oder 3D Punkte klicken. Klick auf den ersten Punkt schließt den Raum, "
            "Enter oder ein zweiter Klick auf den letzten Punkt beendet, Rücktaste nimmt zurück")

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.options = WallOptions()
        self.points: list[P2] = []
        self.hover: P2 | None = None

    def activate(self) -> None:
        super().activate()
        self.points = []
        self.hover = None

    def deactivate(self) -> None:
        self.points = []
        self.hover = None

    # ---- Bauen ------------------------------------------------------------------------------
    def _faces(self, points: list[P2], closed: bool):
        o = self.options
        return wall_faces(points, o.thickness, o.bottom, o.height, closed, self.editor.current_material)

    def finish(self, closed: bool = False) -> list[int]:
        """Wände aus den gesetzten Punkten bauen; liefert die neuen IDs."""
        pts, self.points, self.hover = self.points, [], None
        if len(pts) < 2 or (closed and len(pts) < 3):
            self.editor.redraw_requested.emit()
            return []
        ed = self.editor
        solids = solids_from_faces(ed.doc, self._faces(pts, closed))
        if not solids:
            return []
        if self.options.group and len(solids) > 1:
            gid = new_group_id(ed.doc)
            solids = [s.replace(editor=dataclasses.replace(s.editor, group_id=gid)) for s in solids]
        ed.run(AddObjects(solids, "Wände malen"))
        ed.set_selection([s.id for s in solids])
        ed.status_message.emit(f"{len(solids)} Wände gebaut" + (" (Raum geschlossen)" if closed else ""))
        ed.redraw_requested.emit()
        return [s.id for s in solids]

    def add_point(self, p: P2, close_px: float | None = None) -> None:
        """Punkt anfügen; auf dem ersten Punkt schließt, auf dem letzten beendet."""
        if self.points and len(self.points) >= 3 and close_px is not None and close_px <= CLOSE_PX:
            self.finish(closed=True)
            return
        if self.points and p == self.points[-1]:
            self.finish()
            return
        self.points.append(p)
        self.editor.redraw_requested.emit()

    def _snap(self, x: float, y: float) -> P2:
        return float(self.editor.snap(x)), float(self.editor.snap(y))

    # ---- 2D ---------------------------------------------------------------------------------
    @staticmethod
    def _top(vp: "Viewport") -> bool:
        return vp.axes()[:2] == (0, 1)

    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        if not self._top(vp):
            self.editor.status_message.emit("Wände in der Ansicht „Oben“ oder in 3D zeichnen")
            return
        x, y = vp.to_world(e.position())
        first = vp.to_screen(*self.points[0]) if self.points else None
        dist = math.hypot(first.x() - e.position().x(), first.y() - e.position().y()) if first else None
        self.add_point(self._snap(x, y), dist)

    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if self._top(vp):
            self.hover = self._snap(*vp.to_world(e.position()))
            if self.points:
                self.editor.redraw_requested.emit()

    # ---- 3D ---------------------------------------------------------------------------------
    def _hit(self, vp: "Viewport", e: QMouseEvent) -> tuple[float, float, float] | None:
        origin, direction = vp.ray(e.position())
        hit = pick_3d(self.editor, origin, direction, roots=False)
        if hit is not None:
            p = np.asarray(origin) + np.asarray(direction) * hit[1]
        elif direction[2] < -1e-6:
            # Kein Brush getroffen: Ebene der Unterkante
            t = (self.options.bottom - origin[2]) / direction[2]
            p = np.asarray(origin) + np.asarray(direction) * t
        else:
            return None
        return float(p[0]), float(p[1]), float(p[2])

    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        p = self._hit(vp, e)
        if p is None:
            return
        if not self.points:
            self.options.bottom = int(round(p[2]))
        first = vp.project((*self.points[0], self.options.bottom)) if self.points else None
        dist = math.hypot(first.x() - e.position().x(), first.y() - e.position().y()) if first else None
        self.add_point(self._snap(p[0], p[1]), dist)

    def move_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if not self.points:
            return
        p = self._hit(vp, e)
        if p is not None:
            self.hover = self._snap(p[0], p[1])
            self.editor.redraw_requested.emit()

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        return Qt.CrossCursor if self._top(vp) else Qt.ForbiddenCursor

    def cursor_3d(self, vp: "Viewport", pos) -> Qt.CursorShape:
        return Qt.CrossCursor

    # ---- Tasten -----------------------------------------------------------------------------
    def wants_key(self, key: int) -> bool:
        return bool(self.points) and key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Backspace, Qt.Key_Escape)

    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        key = e.key()
        if key in (Qt.Key_Return, Qt.Key_Enter) and self.points:
            self.finish()
            return True
        if key == Qt.Key_Backspace and self.points:
            self.points.pop()
            self.editor.redraw_requested.emit()
            return True
        if key == Qt.Key_Escape:
            if self.points:
                self.points = []
                self.editor.redraw_requested.emit()
            else:
                self.editor.set_tool("select")
            return True
        return False

    # ---- Zeichnen ---------------------------------------------------------------------------
    def _planned(self) -> list[P2]:
        pts = list(self.points)
        if self.hover is not None and pts and self.hover != pts[-1]:
            pts.append(self.hover)
        return pts

    def lines_2d(self, vp: "Viewport") -> np.ndarray | None:
        return self._lines(three_d=False)

    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        return self._lines(three_d=True)

    def _lines(self, three_d: bool) -> np.ndarray | None:
        pts = self._planned()
        if len(pts) < 2:
            return None
        o = self.options
        z0, z1 = o.bottom, o.bottom + o.height
        out = []
        for quad in wall_outlines(pts, o.thickness):
            for z in ((z0, z1) if three_d else (z1,)):
                for i in range(4):
                    a, b = quad[i], quad[(i + 1) % 4]
                    out += [[a[0], a[1], z, *PREVIEW], [b[0], b[1], z, *PREVIEW]]
            if three_d:
                for a in quad:
                    out += [[a[0], a[1], z0, *PREVIEW], [a[0], a[1], z1, *PREVIEW]]
        return np.asarray(out, dtype=np.float32)

    def _paint_points(self, p: QPainter, screen_of) -> None:
        for i, pt in enumerate(self.points):
            s = screen_of(pt)
            if s is None:
                continue
            p.setPen(QColor(20, 20, 20))
            p.setBrush(QColor(255, 140, 25) if i == 0 else QColor(245, 245, 245))
            r = 5 if i == 0 else 3.5
            p.drawEllipse(s, r, r)
        pts = self._planned()
        if len(pts) >= 2:
            a, b = pts[-2], pts[-1]
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            s = screen_of(b)
            if s is not None:
                p.setPen(QColor(255, 200, 120))
                p.drawText(s + QPointF(10, -8), f"{length:.0f}")

    def paint_2d(self, vp: "Viewport", p: QPainter) -> None:
        if self._top(vp):
            self._paint_points(p, lambda pt: vp.to_screen(pt[0], pt[1]))

    def paint_3d(self, vp: "Viewport", p: QPainter) -> None:
        self._paint_points(p, lambda pt: vp.project((pt[0], pt[1], self.options.bottom)))


__all__ = ["WallOptions", "WallTool"]
