"""Ecken-Werkzeug: Ecken und Kanten der ausgewählten Brushes ziehen (wie Hammers Vertex-Werkzeug).

Weiße Quadrate sind Ecken, gelbe die Mitten der Kanten (ziehen bewegt beide Enden). Klick wählt,
Strg+Klick ergänzt, Ziehen auf freier Fläche zieht einen Rahmen. In 2D trifft ein Klick alle
Ecken, die in der Ansicht übereinander liegen. In 3D verschiebt Ziehen waagrecht, mit Shift
senkrecht. Pfeiltasten (2D) schieben um eine Rasterweite. Ein Zug ist ein Undo-Schritt; was den
Brush hohl machen würde, wird nicht übernommen.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QKeyEvent, QMouseEvent, QPainter, QPen

from ...core.blocks import is_block_root
from ...core.commands import ReplaceObjects
from ...core.geometry.displacement import is_displacement_solid
from ...core.geometry.vertex_edit import (
    IPoint,
    VertexError,
    edges,
    midpoint,
    move_selected,
    vertices,
)
from ...core.model import Entity, Solid
from .base import Tool, pick_2d, pick_3d

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

HANDLE = 7
EDGE_HANDLE = 5
PICK_PX = 7
_moves = itertools.count(1)


@dataclass
class _Drag:
    kind: str                      # "move" oder "box"
    start: tuple[float, float]     # Bildschirm (Rahmen) bzw. Welt (Verschieben, 2D)
    current: tuple[float, float]
    originals: dict[int, Solid] = field(default_factory=dict)
    picked: dict[int, set[IPoint]] = field(default_factory=dict)
    delta: tuple[int, int, int] = (0, 0, 0)
    key: object = None
    anchor: np.ndarray | None = None   # 3D: Startpunkt im Raum
    vertical: bool = False


class VertexTool(Tool):
    name = "vertex"
    label = "Ecken"
    shortcut = "Shift+V"
    hint = ("Brush auswählen, dann Ecken (weiß) oder Kanten-Mitten (gelb) ziehen. Strg ergänzt, "
            "Rahmen ziehen wählt mehrere, in 3D mit Shift senkrecht")

    def __init__(self, editor) -> None:
        super().__init__(editor)
        #: Gewählte Ecken je Brush
        self.picked: dict[int, set[IPoint]] = {}
        self._drag: _Drag | None = None

    def activate(self) -> None:
        super().activate()
        self.picked = {}
        self._drag = None
        self._warn_unsupported()

    def deactivate(self) -> None:
        self.picked = {}
        self._drag = None

    # ---- Ziele ------------------------------------------------------------------------------
    def targets(self) -> list[Solid]:
        """Bearbeitbare Brushes der Auswahl (Brush-Entities: ihre Brushes)."""
        doc = self.editor.doc
        out: list[Solid] = []
        for obj in self.editor.selected_objects():
            if isinstance(obj, Solid):
                out.append(obj)
            elif isinstance(obj, Entity) and not is_block_root(obj):
                out += [s for s in doc.children(obj.id) if isinstance(s, Solid)]
        return [s for s in out if not is_displacement_solid(s)
                and not (s.parent_id is not None and is_block_root(doc.get(s.parent_id)))]

    def _warn_unsupported(self) -> None:
        objs = self.editor.selected_objects()
        if any(is_block_root(o) for o in objs):
            self.editor.status_message.emit("Rampen-Bausteine erst lösen (Bibliothek: „Baustein lösen“), "
                                            "dann lassen sich ihre Ecken ziehen")
        elif any(isinstance(o, Solid) and is_displacement_solid(o) for o in objs):
            self.editor.status_message.emit("Gelände formt man mit dem Gelände-Werkzeug (Shift+G)")

    def handles(self) -> list[tuple[int, tuple[float, float, float], tuple[IPoint, ...], bool]]:
        """(Brush-ID, Lage, Ecken, ist_Kante) für alle Griffe."""
        out = []
        for s in self.targets():
            for v in vertices(s):
                out.append((s.id, (float(v[0]), float(v[1]), float(v[2])), (v,), False))
            for e in edges(s):
                out.append((s.id, midpoint(e), e, True))
        return out

    def picked_count(self) -> int:
        return sum(len(v) for v in self.picked.values())

    # ---- Verschieben --------------------------------------------------------------------------
    def apply(self, originals: dict[int, Solid], picked: dict[int, set[IPoint]], delta, key=None) -> bool:
        """Gewählte Ecken der Original-Brushes um `delta` verschieben. False, wenn ungültig."""
        new = []
        try:
            for sid, verts in picked.items():
                if verts and sid in originals:
                    new.append(move_selected(originals[sid], verts, delta))
        except VertexError as exc:
            self.editor.status_message.emit(str(exc))
            return False
        if new:
            self.editor.run(ReplaceObjects(new, "Ecken verschieben", key))
        return True

    def nudge(self, delta: tuple[int, int, int]) -> bool:
        originals = {sid: s for sid in self.picked if isinstance(s := self.editor.doc.get(sid), Solid)}
        if not originals or not self.apply(originals, self.picked, delta):
            return False
        self.editor.stack.end_merge()
        self._shift_picked(delta)
        return True

    def _shift_picked(self, delta) -> None:
        self.picked = {sid: {(v[0] + delta[0], v[1] + delta[1], v[2] + delta[2]) for v in verts}
                       for sid, verts in self.picked.items()}
        # Verschmolzene Ecken fallen weg
        for sid in list(self.picked):
            s = self.editor.doc.get(sid)
            if isinstance(s, Solid):
                self.picked[sid] &= set(vertices(s))

    # ---- Picking ------------------------------------------------------------------------------
    def _hits(self, screen_of, pos: QPointF) -> list[tuple[int, tuple[IPoint, ...], float]]:
        hits = []
        for sid, p, verts, is_edge in self.handles():
            sp = screen_of(p)
            if sp is None:
                continue
            d = ((sp.x() - pos.x()) ** 2 + (sp.y() - pos.y()) ** 2) ** 0.5
            if d <= PICK_PX:
                hits.append((sid, verts, d + (0.5 if is_edge else 0.0)))
        return hits

    def _select_hits(self, hits, add: bool, all_hits: bool) -> None:
        if not hits:
            return
        chosen = hits if all_hits else [min(hits, key=lambda h: h[2])]
        if not add:
            already = all(v in self.picked.get(sid, set()) for sid, verts, _ in chosen for v in verts)
            if not already:
                self.picked = {}
        for sid, verts, _ in chosen:
            self.picked.setdefault(sid, set()).update(verts)

    def _start_move(self, start, anchor=None, vertical=False) -> None:
        doc = self.editor.doc
        originals = {sid: s for sid in self.picked if isinstance(s := doc.get(sid), Solid)}
        self._drag = _Drag("move", start, start, originals, {k: set(v) for k, v in self.picked.items()},
                           key=("vertex", next(_moves)), anchor=anchor, vertical=vertical)

    def _finish_move(self) -> None:
        d = self._drag
        self._drag = None
        if d is None:
            return
        if d.delta != (0, 0, 0):
            self.picked = d.picked
            self._shift_picked(d.delta)
            self.editor.stack.end_merge()

    def _move_to(self, delta) -> None:
        d = self._drag
        if d is None or delta == d.delta:
            return
        if self.apply(d.originals, d.picked, delta, d.key):
            d.delta = delta

    # ---- 2D ---------------------------------------------------------------------------------------
    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        h, v, _ = vp.axes()
        pos = e.position()
        hits = self._hits(lambda p: vp.to_screen(p[h], p[v]), pos)
        add = bool(e.modifiers() & Qt.ControlModifier)
        if hits:
            # In 2D liegen Ecken übereinander: alle an dieser Stelle (nur Ecken oder nur Kanten)
            best = min(hits, key=lambda x: x[2])
            same = [x for x in hits if abs(x[2] - best[2]) < 1.0]
            self._select_hits(same, add, all_hits=True)
            self._start_move(vp.to_world(pos))
        else:
            obj = pick_2d(self.editor, vp, pos)
            if obj is not None and obj.id not in self.editor.selection and not add:
                self.editor.set_selection({obj.id})
                self.picked = {}
                self._warn_unsupported()
            else:
                if not add:
                    self.picked = {}
                self._drag = _Drag("box", (pos.x(), pos.y()), (pos.x(), pos.y()))
        self.editor.redraw_requested.emit()

    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        d = self._drag
        if d is None:
            return
        pos = e.position()
        if d.kind == "box":
            d.current = (pos.x(), pos.y())
        else:
            h, v, _ = vp.axes()
            wh, wv = vp.to_world(pos)
            snap = self.editor.snap
            delta = [0, 0, 0]
            delta[h] = snap(wh - d.start[0])
            delta[v] = snap(wv - d.start[1])
            self._move_to((delta[0], delta[1], delta[2]))
        self.editor.redraw_requested.emit()

    def release_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        d = self._drag
        if d is not None and d.kind == "box":
            h, v, _ = vp.axes()
            rect = QRectF(QPointF(*d.start), QPointF(*d.current)).normalized()
            self._drag = None
            for sid, p, verts, is_edge in self.handles():
                if not is_edge and rect.contains(vp.to_screen(p[h], p[v])):
                    self.picked.setdefault(sid, set()).update(verts)
        else:
            self._finish_move()
        self.editor.redraw_requested.emit()

    # ---- 3D ---------------------------------------------------------------------------------------
    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        hits = self._hits(vp.project, pos)
        add = bool(e.modifiers() & Qt.ControlModifier)
        if hits:
            self._select_hits(hits, add, all_hits=False)
            sid, verts, _ = min(hits, key=lambda x: x[2])
            anchor = np.asarray(verts[0], dtype=np.float64)
            self._start_move((pos.x(), pos.y()), anchor, bool(e.modifiers() & Qt.ShiftModifier))
        else:
            origin, direction = vp.ray(pos)
            hit = pick_3d(self.editor, origin, direction)
            if hit is not None and not add:
                self.editor.set_selection({hit[0].id})
                self._warn_unsupported()
            self.picked = {} if not add else self.picked
        self.editor.redraw_requested.emit()

    def move_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        d = self._drag
        if d is None or d.anchor is None:
            return
        origin, direction = vp.ray(e.position())
        a = d.anchor
        snap = self.editor.snap
        if d.vertical:
            # Ebene senkrecht, zur Kamera gedreht
            n = np.array([direction[0], direction[1], 0.0])
            if np.linalg.norm(n) < 1e-6:
                return
            n /= np.linalg.norm(n)
            denom = direction @ n
            if abs(denom) < 1e-6:
                return
            t = ((a - origin) @ n) / denom
            p = origin + direction * t
            delta = (0, 0, snap(p[2] - a[2]))
        else:
            if abs(direction[2]) < 1e-6:
                return
            t = (a[2] - origin[2]) / direction[2]
            if t < 0:
                return
            p = origin + direction * t
            delta = (snap(p[0] - a[0]), snap(p[1] - a[1]), 0)
        self._move_to(delta)
        self.editor.redraw_requested.emit()

    def release_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self._finish_move()
            self.editor.redraw_requested.emit()

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        h, v, _ = vp.axes()
        return Qt.SizeAllCursor if self._hits(lambda p: vp.to_screen(p[h], p[v]), pos) else Qt.CrossCursor

    def cursor_3d(self, vp: "Viewport", pos) -> Qt.CursorShape:
        return Qt.SizeAllCursor if self._hits(vp.project, pos) else Qt.ArrowCursor

    # ---- Tasten ---------------------------------------------------------------------------------
    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        key = e.key()
        if key == Qt.Key_Escape:
            if self.picked:
                self.picked = {}
            else:
                self.editor.set_tool("select")
            self.editor.redraw_requested.emit()
            return True
        arrows = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, 1), Qt.Key_Down: (0, -1)}
        if key in arrows and not vp.is_3d and self.picked:
            h, v, _ = vp.axes()
            dh, dv = arrows[key]
            delta = [0, 0, 0]
            delta[h] = dh * self.editor.grid
            delta[v] = dv * self.editor.grid
            self.nudge((delta[0], delta[1], delta[2]))
            self.editor.redraw_requested.emit()
            return True
        return False

    # ---- Zeichnen ---------------------------------------------------------------------------------
    def _paint(self, p: QPainter, screen_of) -> None:
        p.setRenderHint(QPainter.Antialiasing, False)
        for sid, pt, verts, is_edge in self.handles():
            sp = screen_of(pt)
            if sp is None:
                continue
            picked = all(v in self.picked.get(sid, set()) for v in verts)
            size = EDGE_HANDLE if is_edge else HANDLE
            fill = QColor(255, 60, 60) if picked else (QColor(255, 210, 60) if is_edge else QColor(245, 245, 245))
            p.setPen(QPen(QColor(20, 20, 20), 1))
            p.setBrush(QBrush(fill))
            p.drawRect(QRectF(sp.x() - size / 2, sp.y() - size / 2, size, size))
        d = self._drag
        if d is not None and d.kind == "box":
            p.setPen(QPen(QColor(255, 255, 255), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(QPointF(*d.start), QPointF(*d.current)).normalized())

    def paint_2d(self, vp: "Viewport", p: QPainter) -> None:
        h, v, _ = vp.axes()
        self._paint(p, lambda pt: vp.to_screen(pt[h], pt[v]))

    def paint_3d(self, vp: "Viewport", p: QPainter) -> None:
        self._paint(p, vp.project)


__all__ = ["VertexTool"]
