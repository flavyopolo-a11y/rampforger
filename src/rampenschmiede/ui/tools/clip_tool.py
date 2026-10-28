"""Schneide-Werkzeuge wie in Hammer.

Schneiden (Shift+X): Brushes auswählen, in einer 2D-Ansicht eine Linie ziehen. Die Schnittebene
steht senkrecht zur Ansicht. Tab wechselt, was übrig bleibt (beide Teile, nur der eine, nur
der andere), Enter schneidet. Weiß = bleibt, Rot = fällt weg.

Loch (Shift+L): Brushes auswählen, in einer 2D-Ansicht ein Rechteck aufziehen, Enter. Das
Rechteck geht als Loch oder Fenster ganz durch die Auswahl, in Blickrichtung der Ansicht.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen

from ...core.cutting import Keep, clip, cuttable, hole
from ...core.geometry.csg import split
from ...core.mathutil import BBox
from ...core.model import Solid
from ...i18n import tr
from .base import Tool, box_lines

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

LINE_COLOR = (1.0, 0.85, 0.2)
KEEP_COLOR = (1.0, 1.0, 1.0)
DROP_COLOR = (1.0, 0.25, 0.25)
KEEP_MODES: tuple[Keep, ...] = ("both", "back", "front")
KEEP_LABELS = {"both": tr("Beide Teile behalten"), "back": tr("Nur Seite 1 behalten"), "front": tr("Nur Seite 2 behalten")}


class _Signals(QObject):
    changed = Signal()


def _selected_solids(editor) -> list[Solid]:
    out: list[Solid] = []
    for i in editor.selection:
        obj = editor.doc.get(i)
        if isinstance(obj, Solid):
            if cuttable(editor.doc, obj):
                out.append(obj)
        elif obj is not None:
            out += [c for c in editor.doc.children(obj.id) if cuttable(editor.doc, c)]
    return out


def _outline(faces, color) -> list[list[float]]:
    rows: list[list[float]] = []
    for poly in Solid(id=0, faces=faces).polygons():
        if not poly:
            continue
        for k in range(len(poly)):
            rows.append([*poly[k], *color])
            rows.append([*poly[(k + 1) % len(poly)], *color])
    return rows


class ClipTool(Tool):
    name = "clip"
    label = "Schneiden"
    shortcut = "Shift+X"
    hint = "Brushes auswählen, in einer 2D-Ansicht eine Linie ziehen. Tab: was bleibt, Enter: schneiden"

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.signals = _Signals()
        self.keep: Keep = "both"
        self.start: tuple[int, int] | None = None
        self.end: tuple[int, int] | None = None
        self.axes: tuple[int, int, int] | None = None
        self._dragging = False

    # ---- Zustand ------------------------------------------------------------------------
    def clear(self) -> None:
        self.start = self.end = self.axes = None
        self.signals.changed.emit()
        self.editor.redraw_requested.emit()

    def deactivate(self) -> None:
        self.start = self.end = self.axes = None

    def set_keep(self, keep: Keep) -> None:
        self.keep = keep
        self.signals.changed.emit()
        self.editor.redraw_requested.emit()

    def cycle_keep(self) -> None:
        self.set_keep(KEEP_MODES[(KEEP_MODES.index(self.keep) + 1) % len(KEEP_MODES)])
        self.editor.status_message.emit(KEEP_LABELS[self.keep])

    def set_line(self, axes: tuple[int, int, int], start: tuple[int, int], end: tuple[int, int]) -> None:
        self.axes, self.start, self.end = axes, start, end
        self.signals.changed.emit()
        self.editor.redraw_requested.emit()

    def points(self) -> tuple[tuple[int, int, int], ...] | None:
        """Drei ganzzahlige Punkte der Schnittebene."""
        if self.axes is None or self.start is None or self.end is None or self.start == self.end:
            return None
        h, v, d = self.axes
        p1, p2, p3 = [0, 0, 0], [0, 0, 0], [0, 0, 0]
        p1[h], p1[v] = self.start
        p2[h], p2[v] = self.end
        p3[h], p3[v] = self.start
        p3[d] = 64
        return (tuple(p1), tuple(p2), tuple(p3))  # type: ignore[return-value]

    def apply(self) -> bool:
        pts = self.points()
        if pts is None:
            self.editor.status_message.emit(tr("Erst eine Schnittlinie in einer 2D-Ansicht ziehen"))
            return False
        if not _selected_solids(self.editor):
            self.editor.status_message.emit(tr("Erst Brushes auswählen. Bausteine vorher lösen."))
            return False
        cmd, ids = clip(self.editor.doc, self.editor.selection, pts, self.keep)  # type: ignore[arg-type]
        if cmd is None:
            self.editor.status_message.emit(tr("Die Linie geht durch keinen der ausgewählten Brushes"))
            return False
        self.editor.run(cmd)
        self.editor.set_selection(ids)
        self.clear()
        return True

    # ---- Maus ---------------------------------------------------------------------------
    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        w = vp.to_world(e.position())
        snap = self.editor.snap
        self.set_line(vp.axes(), (snap(w[0]), snap(w[1])), (snap(w[0]), snap(w[1])))
        self._dragging = True

    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if not self._dragging or self.axes != vp.axes():
            return
        w = vp.to_world(e.position())
        snap = self.editor.snap
        self.end = (snap(w[0]), snap(w[1]))
        self.signals.changed.emit()
        self.editor.redraw_requested.emit()

    def release_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        self._dragging = False
        if self.points() is not None:
            self.editor.status_message.emit("Tab: was bleibt · Enter: schneiden · Esc: verwerfen")

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        return Qt.CrossCursor

    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            return self.apply()
        if e.key() == Qt.Key_Tab:
            self.cycle_keep()
            return True
        if e.key() == Qt.Key_Escape and self.start is not None:
            self.clear()
            return True
        return False

    def wants_key(self, key: int) -> bool:
        return key == Qt.Key_Tab

    # ---- Zeichnen -----------------------------------------------------------------------
    def _preview(self) -> np.ndarray | None:
        pts = self.points()
        if pts is None:
            return None
        rows: list[list[float]] = []
        solids = _selected_solids(self.editor)
        for s in solids:
            back, front = split(s.faces, pts)
            if back is None or front is None:
                rows += _outline(s.faces, KEEP_COLOR)
                continue
            rows += _outline(back, KEEP_COLOR if self.keep in ("both", "back") else DROP_COLOR)
            rows += _outline(front, KEEP_COLOR if self.keep in ("both", "front") else DROP_COLOR)
        # Die Linie selbst, über die ganze Auswahl verlängert
        h, v, d = self.axes  # type: ignore[misc]
        a, b = np.array(self.start, float), np.array(self.end, float)
        direction = (b - a) / max(1e-9, float(np.linalg.norm(b - a)))
        bb = BBox.union(s.bbox() for s in solids)
        reach = 4096.0 if bb is None else float(max(bb.size)) * 1.5 + 256
        depth = 0.0 if bb is None else (bb.mins[d] + bb.maxs[d]) / 2
        for p in (a - direction * reach, b + direction * reach):
            q = [0.0, 0.0, 0.0]
            q[h], q[v], q[d] = p[0], p[1], depth
            rows.append([*q, *LINE_COLOR])
        return np.asarray(rows, dtype=np.float32)

    def lines_2d(self, vp: "Viewport") -> np.ndarray | None:
        return self._preview()

    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        return self._preview()

    def paint_2d(self, vp: "Viewport", p: QPainter) -> None:
        if self.axes != vp.axes() or self.start is None or self.end is None:
            return
        p.setPen(QPen(QColor(255, 216, 50), 2))
        for pt in (self.start, self.end):
            s = vp.to_screen(*pt)
            p.drawRect(int(s.x()) - 3, int(s.y()) - 3, 6, 6)


class HoleTool(Tool):
    name = "hole"
    label = "Loch"
    shortcut = "Shift+L"
    hint = "Brushes auswählen, in einer 2D-Ansicht ein Rechteck aufziehen, Enter schneidet ein Loch durch"

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.rect: tuple[int, int, int, int] | None = None
        self.axes: tuple[int, int, int] | None = None
        self._start: tuple[int, int] | None = None

    def clear(self) -> None:
        self.rect = self.axes = None
        self.editor.redraw_requested.emit()

    def deactivate(self) -> None:
        self.rect = self.axes = None

    def set_rect(self, axes: tuple[int, int, int], rect: tuple[int, int, int, int]) -> None:
        self.axes, self.rect = axes, rect
        self.editor.redraw_requested.emit()

    def cutter_box(self) -> BBox | None:
        if self.rect is None or self.axes is None:
            return None
        solids = _selected_solids(self.editor)
        bb = BBox.union(s.bbox() for s in solids)
        h, v, d = self.axes
        mins, maxs = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
        mins[h], mins[v], maxs[h], maxs[v] = self.rect
        mins[d], maxs[d] = (bb.mins[d], bb.maxs[d]) if bb else (-64, 64)
        return BBox(tuple(mins), tuple(maxs))  # type: ignore[arg-type]

    def apply(self) -> bool:
        if self.rect is None or self.axes is None:
            self.editor.status_message.emit(tr("Erst ein Rechteck in einer 2D-Ansicht aufziehen"))
            return False
        if not _selected_solids(self.editor):
            self.editor.status_message.emit(tr("Erst Brushes auswählen. Bausteine vorher lösen."))
            return False
        cmd, ids = hole(self.editor.doc, self.editor.selection, self.axes, self.rect)
        if cmd is None:
            self.editor.status_message.emit(tr("Das Rechteck trifft keinen der ausgewählten Brushes"))
            return False
        self.editor.run(cmd)
        self.editor.set_selection(ids)
        self.clear()
        self.editor.status_message.emit(tr("Loch geschnitten"))
        return True

    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        w = vp.to_world(e.position())
        self._start = (self.editor.snap(w[0]), self.editor.snap(w[1]))
        self.axes = vp.axes()
        self.rect = None

    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if self._start is None:
            return
        w = vp.to_world(e.position())
        b = (self.editor.snap(w[0]), self.editor.snap(w[1]))
        a = self._start
        if a[0] != b[0] and a[1] != b[1]:
            self.set_rect(vp.axes(), (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))

    def release_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        self._start = None
        if self.rect is not None:
            self.editor.status_message.emit(tr("Enter schneidet das Loch, Esc verwirft das Rechteck"))

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        return Qt.CrossCursor

    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            return self.apply()
        if e.key() == Qt.Key_Escape and self.rect is not None:
            self.clear()
            return True
        return False

    def lines_2d(self, vp: "Viewport") -> np.ndarray | None:
        box = self.cutter_box()
        return box_lines(box, DROP_COLOR) if box else None

    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        return self.lines_2d(vp)


__all__ = ["KEEP_LABELS", "KEEP_MODES", "ClipTool", "HoleTool"]
