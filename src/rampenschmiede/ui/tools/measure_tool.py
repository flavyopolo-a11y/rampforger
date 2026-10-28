"""Messen (Shift+M): Abstand, Versatz je Achse und Steigung zwischen zwei Punkten.

2D: von A nach B ziehen (am Raster). 3D: erster Klick auf eine Fläche setzt A, B folgt der
Maus, zweiter Klick hält B fest. Die Messung bleibt stehen, bis neu gemessen wird oder Esc.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter

from .base import Tool, pick_3d

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

Point = tuple[float, float, float]
COLOR = (1.0, 0.55, 0.1)


def _num(v: float) -> str:
    return (f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}").replace(".", ",")


def describe(a: Point, b: Point) -> str:
    """„256 Units · ΔX 256 ΔY 0 ΔZ 64 · Steigung 14,0°“"""
    d = [b[i] - a[i] for i in range(3)]
    length = math.sqrt(sum(c * c for c in d))
    flat = math.hypot(d[0], d[1])
    text = f"{_num(length)} Units · ΔX {_num(d[0])} ΔY {_num(d[1])} ΔZ {_num(d[2])}"
    if flat > 1e-6 and abs(d[2]) > 1e-6:
        text += f" · Steigung {_num(math.degrees(math.atan2(abs(d[2]), flat)))}°"
    return text


class MeasureTool(Tool):
    name = "measure"
    label = "Messen"
    shortcut = "Shift+M"
    hint = "Messen: in 2D von A nach B ziehen, in 3D zwei Flächenpunkte anklicken. Esc löscht die Messung"

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.a: Point | None = None
        self.b: Point | None = None
        self._dragging = False
        self._placing_3d = False

    def deactivate(self) -> None:
        self._dragging = self._placing_3d = False

    def text(self) -> str:
        return describe(self.a, self.b) if self.a is not None and self.b is not None else ""

    def _changed(self) -> None:
        if self.text():
            self.editor.status_message.emit(self.text())
        self.editor.redraw_requested.emit()

    # ---- 2D ---------------------------------------------------------------------------------
    def _point_2d(self, vp: "Viewport", e: QMouseEvent, depth: float = 0.0) -> Point:
        h, v, d = vp.axes()
        wh, wv = vp.to_world(e.position())
        p = [0.0, 0.0, 0.0]
        p[h], p[v], p[d] = float(self.editor.snap(wh)), float(self.editor.snap(wv)), depth
        return (p[0], p[1], p[2])

    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        self.a = self.b = self._point_2d(vp, e)
        self._dragging = True
        self._placing_3d = False
        self._changed()

    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if self._dragging and self.a is not None:
            self.b = self._point_2d(vp, e, self.a[vp.axes()[2]])
            self._changed()

    def release_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton and self._dragging:
            self.move_2d(vp, e)
            self._dragging = False

    # ---- 3D ---------------------------------------------------------------------------------
    def _point_3d(self, vp: "Viewport", e: QMouseEvent) -> Point | None:
        origin, direction = vp.ray(e.position())
        hit = pick_3d(self.editor, origin, direction, roots=False)
        if hit is None:
            return None
        p = np.asarray(origin) + np.asarray(direction) * hit[1]
        return (float(round(p[0], 1)), float(round(p[1], 1)), float(round(p[2], 1)))

    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        p = self._point_3d(vp, e)
        if p is None:
            return
        if self._placing_3d:
            self.b = p
            self._placing_3d = False
        else:
            self.a = self.b = p
            self._placing_3d = True
        self._changed()

    def move_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if self._placing_3d:
            p = self._point_3d(vp, e)
            if p is not None:
                self.b = p
                self._changed()

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        return Qt.CrossCursor

    def cursor_3d(self, vp: "Viewport", pos) -> Qt.CursorShape:
        return Qt.CrossCursor

    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        if e.key() == Qt.Key_Escape:
            if self.a is not None:
                self.a = self.b = None
                self._placing_3d = self._dragging = False
                self.editor.redraw_requested.emit()
            else:
                self.editor.set_tool("select")
            return True
        return False

    # ---- Zeichnen ---------------------------------------------------------------------------
    def _lines(self) -> np.ndarray | None:
        if self.a is None or self.b is None or self.a == self.b:
            return None
        return np.asarray([[*self.a, *COLOR], [*self.b, *COLOR]], dtype=np.float32)

    def lines_2d(self, vp: "Viewport") -> np.ndarray | None:
        return self._lines()

    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        return self._lines()

    def _label(self, p: QPainter, sa: QPointF | None, sb: QPointF | None) -> None:
        if sa is None or sb is None or not self.text():
            return
        for s in (sa, sb):
            p.setPen(QColor(255, 140, 25))
            p.setBrush(QColor(255, 140, 25))
            p.drawEllipse(s, 3, 3)
        mid = (sa + sb) / 2
        text = self.text()
        rect = p.fontMetrics().boundingRect(text).adjusted(-5, -3, 5, 3)
        rect.moveCenter(mid.toPoint() + QPointF(0, -16).toPoint())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 20, 24, 210))
        p.drawRoundedRect(QRectF(rect), 4, 4)
        p.setPen(QColor(255, 200, 120))
        p.drawText(rect, Qt.AlignCenter, text)

    def paint_2d(self, vp: "Viewport", p: QPainter) -> None:
        if self.a is None or self.b is None:
            return
        h, v, _ = vp.axes()
        self._label(p, vp.to_screen(self.a[h], self.a[v]), vp.to_screen(self.b[h], self.b[v]))

    def paint_3d(self, vp: "Viewport", p: QPainter) -> None:
        if self.a is None or self.b is None:
            return
        self._label(p, vp.project(self.a), vp.project(self.b))


__all__ = ["MeasureTool", "describe"]
