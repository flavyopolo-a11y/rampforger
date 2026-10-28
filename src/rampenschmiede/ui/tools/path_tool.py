"""Pfad (Shift+P): Punkte klicken, daraus wird eine Kette aus path_track (oder path_corner),
die der Reihe nach aufeinander zeigt. Für Züge, bewegliche Plattformen und Kamerafahrten.

In einer 2D-Ansicht setzt der Klick die beiden sichtbaren Achsen (am Raster), die dritte kommt
vom letzten Punkt bzw. aus der Höhe im Panel. In 3D liegt der Punkt um die Höhe über der
getroffenen Fläche. Klick auf den ersten Punkt schließt den Pfad zum Rundkurs, Enter oder ein
zweiter Klick auf den letzten Punkt beendet, Rücktaste nimmt zurück, Esc verwirft.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter

from ...core.commands import AddObjects
from ...core.tracks import PATH_COLOR, path_entities
from ...i18n import tr
from .base import Tool, pick_3d

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

P3 = tuple[float, float, float]
PREVIEW = tuple(c / 255 for c in PATH_COLOR)
CLOSE_PX = 10


@dataclass
class PathOptions:
    classname: str = "path_track"
    #: Höhe über der angeklickten Fläche (3D) bzw. Höhe in der Ansicht „Oben“
    height: int = 64
    #: Geschwindigkeit für Züge (0 = die des Zugs)
    speed: int = 0
    base: str = "pfad"


class PathTool(Tool):
    name = "path"
    label = "Pfad"
    shortcut = "Shift+P"
    hint = ("Pfad: Punkte klicken (2D oder 3D). Klick auf den ersten Punkt macht einen Rundkurs, "
            "Enter beendet, Rücktaste nimmt zurück")

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.options = PathOptions()
        self.points: list[P3] = []
        self.hover: P3 | None = None

    def activate(self) -> None:
        super().activate()
        self.points, self.hover = [], None

    def deactivate(self) -> None:
        self.points, self.hover = [], None

    def finish(self, closed: bool = False) -> list[int]:
        pts, self.points, self.hover = self.points, [], None
        ed = self.editor
        ents = path_entities(ed.doc, pts, self.options.classname, self.options.base or "pfad",
                             closed and len(pts) >= 3, self.options.speed)
        if not ents:
            ed.redraw_requested.emit()
            return []
        ed.run(AddObjects(ents, "Pfad"))
        ed.set_selection([ents[0].id])
        ed.status_message.emit(tr('Pfad mit {0} Punkten').format(len(ents)) + (tr(" (Rundkurs)") if closed else "")
                               + f", Start: {ents[0].get('targetname')}")
        ed.redraw_requested.emit()
        return [e.id for e in ents]

    def add_point(self, p: P3, close_px: float | None = None) -> None:
        if len(self.points) >= 3 and close_px is not None and close_px <= CLOSE_PX:
            self.finish(closed=True)
            return
        if self.points and p == self.points[-1]:
            self.finish()
            return
        self.points.append(p)
        self.editor.redraw_requested.emit()

    def _snap3(self, p) -> P3:
        s = self.editor.snap
        return float(s(p[0])), float(s(p[1])), float(s(p[2]))

    # ---- 2D ---------------------------------------------------------------------------------
    def _point_2d(self, vp: "Viewport", pos: QPointF) -> P3:
        h, v, d = vp.axes()
        wh, wv = vp.to_world(pos)
        p = [0.0, 0.0, 0.0]
        p[h], p[v] = float(self.editor.snap(wh)), float(self.editor.snap(wv))
        if self.points:
            p[d] = self.points[-1][d]
        else:
            p[d] = float(self.options.height) if d == 2 else 0.0
        return p[0], p[1], p[2]

    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        first = self._screen_2d(vp, self.points[0]) if self.points else None
        dist = math.hypot(first.x() - e.position().x(), first.y() - e.position().y()) if first else None
        self.add_point(self._point_2d(vp, e.position()), dist)

    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if self.points:
            self.hover = self._point_2d(vp, e.position())
            self.editor.redraw_requested.emit()

    @staticmethod
    def _screen_2d(vp: "Viewport", p: P3) -> QPointF:
        h, v, _ = vp.axes()
        return vp.to_screen(p[h], p[v])

    # ---- 3D ---------------------------------------------------------------------------------
    def _point_3d(self, vp: "Viewport", pos: QPointF) -> P3 | None:
        origin, direction = vp.ray(pos)
        hit = pick_3d(self.editor, origin, direction, roots=False)
        if hit is not None:
            p = np.asarray(origin) + np.asarray(direction) * hit[1]
        elif direction[2] < -1e-6:
            base = self.points[-1][2] - self.options.height if self.points else 0.0
            p = np.asarray(origin) + np.asarray(direction) * ((base - origin[2]) / direction[2])
        else:
            return None
        return self._snap3((p[0], p[1], p[2] + self.options.height))

    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        p = self._point_3d(vp, e.position())
        if p is None:
            return
        first = vp.project(self.points[0]) if self.points else None
        dist = math.hypot(first.x() - e.position().x(), first.y() - e.position().y()) if first else None
        self.add_point(p, dist)

    def move_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if self.points:
            self.hover = self._point_3d(vp, e.position())
            self.editor.redraw_requested.emit()

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        return Qt.CrossCursor

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
    def _planned(self) -> list[P3]:
        pts = list(self.points)
        if self.hover is not None and pts and self.hover != pts[-1]:
            pts.append(self.hover)
        return pts

    def _lines(self) -> np.ndarray | None:
        pts = self._planned()
        if len(pts) < 2:
            return None
        out = []
        for a, b in zip(pts, pts[1:]):
            out += [[*a, *PREVIEW], [*b, *PREVIEW]]
        return np.asarray(out, dtype=np.float32)

    def lines_2d(self, vp: "Viewport") -> np.ndarray | None:
        return self._lines()

    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        return self._lines()

    def _paint_points(self, p: QPainter, screen_of) -> None:
        for i, pt in enumerate(self.points):
            s = screen_of(pt)
            if s is None:
                continue
            p.setPen(QColor(20, 20, 20))
            p.setBrush(QColor(255, 140, 25) if i == 0 else QColor(*PATH_COLOR))
            r = 5 if i == 0 else 4
            p.drawEllipse(s, r, r)
            p.setPen(QColor(230, 230, 230))
            p.drawText(s + QPointF(7, -6), str(i + 1))

    def paint_2d(self, vp: "Viewport", p: QPainter) -> None:
        self._paint_points(p, lambda pt: self._screen_2d(vp, pt))

    def paint_3d(self, vp: "Viewport", p: QPainter) -> None:
        self._paint_points(p, vp.project)


__all__ = ["PathOptions", "PathTool"]
