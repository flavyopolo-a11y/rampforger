"""Auswahl-Werkzeug: auswählen, verschieben, skalieren, drehen.

Bedienung wie in Hammer:
- Klick wählt aus, Strg+Klick schaltet um, Ziehen auf leerer Fläche zieht einen Rahmen auf
- Ziehen der Auswahl verschiebt sie (am Raster), Shift beim Ziehen erzeugt eine Kopie
- Erneuter Klick auf die Auswahl wechselt zwischen Skalier- und Drehgriffen
- Drehen rastet in 15°-Schritten ein, mit Shift frei
- Pfeiltasten verschieben um eine Rasterweite
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QKeyEvent, QMouseEvent, QPainter, QPen

from ...core.commands import ReplaceObjects
from ...core.geometry import transform
from ...core.geometry.transform import TransformError
from ...core.mathutil import BBox
from ...core.model import Entity, MapObject, object_bbox
from .base import Tool, pick_2d, pick_3d

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

HANDLE_PX = 7
DRAG_THRESHOLD_PX = 3
ROTATE_SNAP_DEG = 15.0
HANDLES = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]


@dataclass
class _Drag:
    kind: str  # pending | move | scale | rotate | marquee
    press_pos: QPointF
    start: tuple[float, float]
    current: tuple[float, float]
    originals: list[MapObject] = field(default_factory=list)
    bbox: BBox | None = None
    handle: tuple[int, int] | None = None
    clone: bool = False
    toggle_on_click: bool = False
    ctrl: bool = False
    merge_key: object = field(default_factory=object)


class SelectTool(Tool):
    name = "select"
    label = "Auswahl"
    shortcut = "Shift+S"
    hint = "Klicken zum Auswählen, Ziehen zum Verschieben, erneut klicken für Drehgriffe"

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.handle_mode = "scale"
        self._drag: _Drag | None = None
        editor.selection_changed.connect(self._on_selection_changed)

    def _on_selection_changed(self) -> None:
        if not self.editor.selection:
            self.handle_mode = "scale"

    # ---- Hilfen -----------------------------------------------------------------
    def _targets(self) -> list[MapObject]:
        """Ausgewählte Objekte samt Brushes ausgewählter Brush-Entities."""
        out: list[MapObject] = []
        for o in self.editor.selected_objects():
            out.append(o)
            if isinstance(o, Entity):
                out += self.editor.doc.children(o.id)
        return out

    def _sel_rect(self, vp: "Viewport", bb: BBox | None = None) -> QRectF | None:
        bb = bb or self.editor.selection_bbox()
        if bb is None:
            return None
        h, v, _ = vp.axes()
        a = vp.to_screen(bb.mins[h], bb.mins[v])
        b = vp.to_screen(bb.maxs[h], bb.maxs[v])
        return QRectF(a, b).normalized()

    def _handle_points(self, rect: QRectF) -> list[tuple[tuple[int, int], QPointF]]:
        out = []
        for sh, sv in HANDLES:
            if self.handle_mode == "rotate" and (sh == 0 or sv == 0):
                continue
            x = {-1: rect.left(), 0: rect.center().x(), 1: rect.right()}[sh]
            # Bildschirm-y wächst nach unten, Welt-v nach oben
            y = {-1: rect.bottom(), 0: rect.center().y(), 1: rect.top()}[sv]
            off = HANDLE_PX
            out.append(((sh, sv), QPointF(x + sh * off, y - sv * off)))
        return out

    def _hit_handle(self, vp: "Viewport", pos: QPointF) -> tuple[int, int] | None:
        rect = self._sel_rect(vp)
        if rect is None:
            return None
        for hid, pt in self._handle_points(rect):
            if abs(pt.x() - pos.x()) <= HANDLE_PX and abs(pt.y() - pos.y()) <= HANDLE_PX:
                return hid
        return None

    def _in_selection(self, vp: "Viewport", pos: QPointF) -> bool:
        rect = self._sel_rect(vp)
        return rect is not None and rect.adjusted(-2, -2, 2, 2).contains(pos)

    # ---- 2D-Maus ------------------------------------------------------------------
    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        pos = e.position()
        world = vp.to_world(pos)
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        handle = None if ctrl else self._hit_handle(vp, pos)
        if handle is not None:
            kind = "rotate" if self.handle_mode == "rotate" else "scale"
            self._drag = _Drag(kind, pos, world, world, self._targets(), self.editor.selection_bbox(), handle)
            return
        hit = pick_2d(self.editor, vp, pos)
        if ctrl:
            if hit is not None:
                self.editor.set_selection(self.editor.selection ^ {hit.id})
            else:
                self._drag = _Drag("marquee", pos, world, world, ctrl=True)
            return
        if hit is not None and hit.id in self.editor.selection or (hit is None and self._in_selection(vp, pos)):
            self._drag = _Drag("pending", pos, world, world, toggle_on_click=hit is not None)
            return
        if hit is not None:
            self.editor.set_selection({hit.id})
            self.handle_mode = "scale"
            self._drag = _Drag("pending", pos, world, world)
            return
        self._drag = _Drag("marquee", pos, world, world)

    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        d = self._drag
        if d is None:
            return
        d.current = vp.to_world(e.position())
        if d.kind == "pending":
            moved = e.position() - d.press_pos
            if abs(moved.x()) + abs(moved.y()) < DRAG_THRESHOLD_PX:
                return
            d.kind = "move"
            d.clone = bool(e.modifiers() & Qt.ShiftModifier)
            if d.clone:
                self.editor.duplicate(self.editor.selected_objects(), (0, 0, 0))
            d.originals = self._targets()
            d.bbox = self.editor.selection_bbox()
        if d.kind == "move":
            self._apply_move(vp, d)
        elif d.kind == "scale":
            self._apply_scale(vp, d)
        elif d.kind == "rotate":
            self._apply_rotate(vp, d, free=bool(e.modifiers() & Qt.ShiftModifier))
        vp.update()

    def release_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        d = self._drag
        self._drag = None
        if d is None:
            return
        if d.kind == "pending" and d.toggle_on_click:
            self.handle_mode = "rotate" if self.handle_mode == "scale" else "scale"
        elif d.kind == "marquee":
            self._finish_marquee(vp, d)
        self.editor.stack.end_merge()
        self.editor.redraw_requested.emit()

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        if self._drag is not None:
            return Qt.SizeAllCursor if self._drag.kind == "move" else Qt.ArrowCursor
        h = self._hit_handle(vp, pos)
        if h is not None:
            if self.handle_mode == "rotate":
                return Qt.CrossCursor
            if h[0] == 0:
                return Qt.SizeVerCursor
            if h[1] == 0:
                return Qt.SizeHorCursor
            return Qt.SizeBDiagCursor if h[0] == h[1] else Qt.SizeFDiagCursor
        if self._in_selection(vp, pos):
            return Qt.SizeAllCursor
        return Qt.ArrowCursor

    # ---- Anwenden -------------------------------------------------------------------
    def _replace(self, new: list[MapObject], description: str, merge_key: object) -> None:
        self.editor.run(ReplaceObjects(new, description, merge_key=merge_key))

    def _apply_move(self, vp: "Viewport", d: _Drag) -> None:
        if d.bbox is None:
            return
        h, v, _ = vp.axes()
        delta = [0, 0, 0]
        delta[h] = self.editor.snap(d.bbox.mins[h] + d.current[0] - d.start[0]) - d.bbox.mins[h]
        delta[v] = self.editor.snap(d.bbox.mins[v] + d.current[1] - d.start[1]) - d.bbox.mins[v]
        lock = self.editor.texture_lock
        new = [transform.translate(o, tuple(delta), lock) for o in d.originals]  # type: ignore[arg-type]
        self._replace(new, "Kopieren und verschieben" if d.clone else "Verschieben", d.merge_key)

    def _apply_scale(self, vp: "Viewport", d: _Drag) -> None:
        bb, handle = d.bbox, d.handle
        if bb is None or handle is None:
            return
        h, v, _ = vp.axes()
        g = self.editor.grid
        factors = [1.0, 1.0, 1.0]
        pivot = list(bb.mins)
        for axis, side, cur, start in ((h, handle[0], d.current[0], d.start[0]), (v, handle[1], d.current[1], d.start[1])):
            if side == 0:
                continue
            lo, hi = bb.mins[axis], bb.maxs[axis]
            size = hi - lo
            if size <= 0:
                continue
            if side > 0:
                new_hi = max(lo + g, self.editor.snap(hi + cur - start))
                factors[axis] = (new_hi - lo) / size
                pivot[axis] = lo
            else:
                new_lo = min(hi - g, self.editor.snap(lo + cur - start))
                factors[axis] = (hi - new_lo) / size
                pivot[axis] = hi
        try:
            new = [transform.scale_obj(o, tuple(pivot), tuple(factors), self.editor.texture_lock)  # type: ignore[arg-type]
                   for o in d.originals]
        except TransformError:
            return
        self._replace(new, "Skalieren", d.merge_key)

    def _rotation_angle(self, vp: "Viewport", d: _Drag, free: bool) -> float:
        bb = d.bbox
        if bb is None:
            return 0.0
        h, v, _ = vp.axes()
        ch, cv = bb.center[h], bb.center[v]
        a0 = math.atan2(d.start[1] - cv, d.start[0] - ch)
        a1 = math.atan2(d.current[1] - cv, d.current[0] - ch)
        deg = math.degrees(a1 - a0)
        if not free:
            deg = round(deg / ROTATE_SNAP_DEG) * ROTATE_SNAP_DEG
        return deg

    def _apply_rotate(self, vp: "Viewport", d: _Drag, free: bool) -> None:
        bb = d.bbox
        if bb is None:
            return
        _, _, depth = vp.axes()
        deg = self._rotation_angle(vp, d, free)
        if vp.view == "side":
            deg = -deg  # (X, Z) ist um Y gesehen linkshändig
        pivot = tuple(math.floor(c + 0.5) for c in bb.center)
        try:
            new = [transform.rotate(o, pivot, depth, deg, self.editor.texture_lock) for o in d.originals]  # type: ignore[arg-type]
        except TransformError:
            return
        self._replace(new, "Drehen", d.merge_key)
        self.editor.status_message.emit(f"Drehung {deg:+.0f}°")

    def _finish_marquee(self, vp: "Viewport", d: _Drag) -> None:
        h, v, _ = vp.axes()
        h0, h1 = sorted((d.start[0], d.current[0]))
        v0, v1 = sorted((d.start[1], d.current[1]))
        if (h1 - h0) * vp.cam2d.zoom < DRAG_THRESHOLD_PX and (v1 - v0) * vp.cam2d.zoom < DRAG_THRESHOLD_PX:
            if not d.ctrl:
                self.editor.set_selection(())
            return
        from .base import _brush_entity_ids, selection_root

        found: set[int] = set()
        brush_entities = _brush_entity_ids(self.editor)
        for obj in self.editor.doc.objects():
            if not self.editor.selectable(obj) or (isinstance(obj, Entity) and obj.id in brush_entities):
                continue
            bb = object_bbox(obj)
            if bb and h0 <= bb.mins[h] and bb.maxs[h] <= h1 and v0 <= bb.mins[v] and bb.maxs[v] <= v1:
                found.add(selection_root(self.editor, obj).id)
        self.editor.set_selection((self.editor.selection | found) if d.ctrl else found)

    # ---- 3D ---------------------------------------------------------------------------
    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        origin, direction = vp.ray(e.position())
        hit = pick_3d(self.editor, origin, direction)
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        if hit is None:
            if not ctrl:
                self.editor.set_selection(())
            return
        obj = hit[0]
        if ctrl:
            self.editor.set_selection(self.editor.selection ^ {obj.id})
        else:
            self.editor.set_selection({obj.id})

    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        return None

    # ---- Tastatur --------------------------------------------------------------------
    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        key = e.key()
        if key == Qt.Key_Escape:
            self.editor.set_selection(())
            return True
        if vp.is_3d or not self.editor.selection:
            return False
        arrows = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, 1), Qt.Key_Down: (0, -1)}
        if key in arrows:
            h, v, _ = vp.axes()
            dh, dv = arrows[key]
            delta = [0, 0, 0]
            delta[h] = dh * self.editor.grid
            delta[v] = dv * self.editor.grid
            self.editor.move_selection(tuple(delta))  # type: ignore[arg-type]
            self.editor.stack.end_merge()
            return True
        return False

    # ---- Zeichnen ----------------------------------------------------------------------
    def paint_2d(self, vp: "Viewport", p: QPainter) -> None:
        d = self._drag
        if d is not None and d.kind == "marquee":
            a = vp.to_screen(*d.start)
            b = vp.to_screen(*d.current)
            p.setPen(QPen(QColor(255, 255, 255), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(a, b).normalized())
        rect = self._sel_rect(vp)
        if rect is None:
            return
        p.setPen(QPen(QColor(255, 220, 0), 1, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect)
        p.setPen(QPen(QColor(0, 0, 0), 1))
        p.setBrush(QBrush(QColor(255, 255, 255)))
        for _, pt in self._handle_points(rect):
            if self.handle_mode == "rotate":
                p.drawEllipse(pt, HANDLE_PX / 2 + 1, HANDLE_PX / 2 + 1)
            else:
                p.drawRect(QRectF(pt.x() - HANDLE_PX / 2, pt.y() - HANDLE_PX / 2, HANDLE_PX, HANDLE_PX))
        bb = self.editor.selection_bbox()
        if bb is not None:
            h, v, _ = vp.axes()
            p.setPen(QColor(255, 220, 0))
            w_txt = f"{bb.size[h]:g}"
            h_txt = f"{bb.size[v]:g}"
            fm = p.fontMetrics()
            p.drawText(QPointF(rect.center().x() - fm.horizontalAdvance(w_txt) / 2, rect.top() - 12), w_txt)
            p.drawText(QPointF(rect.right() + 14, rect.center().y() + fm.ascent() / 2), h_txt)
        if d is not None and d.kind == "rotate":
            p.setPen(QColor(255, 220, 0))
            p.drawText(QPointF(rect.center().x() + 6, rect.center().y() - 6),
                       f"{self._rotation_angle(vp, d, False):+.0f}°")
