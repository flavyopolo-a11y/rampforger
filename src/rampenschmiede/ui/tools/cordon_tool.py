"""Bereich (Cordon, Shift+O): nur einen Teil der Map bauen.

In einer 2D-Ansicht ein Rechteck ziehen setzt den Bereich (die Tiefe bleibt, ohne Bereich
reicht sie über die ganze Map). Kanten und Ecken ziehen ändert die Größe, innen ziehen
verschiebt ihn. Entf löscht ihn. Beim Kompilieren wird dann nur gebaut, was darin liegt.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from ...core.mathutil import BBox
from ...i18n import tr
from .base import Tool, box_lines

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

EDGE_PX = 6
DRAG_PX = 4
DRAFT_COLOR = (1.0, 0.6, 0.15)
#: Ohne Map und ohne Bereich: so tief reicht ein neuer Bereich
DEFAULT_DEPTH = (-256.0, 1024.0)


class CordonTool(Tool):
    name = "cordon"
    label = "Bereich"
    shortcut = "Shift+O"
    hint = ("Bereich: in einer 2D-Ansicht ein Rechteck ziehen, nur das wird gebaut. Kanten ziehen ändert die "
            "Größe, innen ziehen verschiebt, Entf löscht den Bereich")

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.drag: dict | None = None
        self.draft: BBox | None = None

    def deactivate(self) -> None:
        self.drag = None
        self.draft = None

    # ---- Hilfen -----------------------------------------------------------------------
    def _depth(self, axis: int) -> tuple[float, float]:
        box, _ = self.editor.cordon()
        if box is not None:
            return box.mins[axis], box.maxs[axis]
        bb = self.editor.doc.bbox()
        if bb is None:
            return DEFAULT_DEPTH
        return float(self.editor.snap(bb.mins[axis] - 64)), float(self.editor.snap(bb.maxs[axis] + 64))

    def _edges(self, vp: "Viewport", pos: QPointF) -> tuple[int, int] | str | None:
        """Welche Kanten unter der Maus liegen: (h, v) mit -1 = min, 1 = max, 0 = keine;
        "move" innen; None außerhalb."""
        box, _ = self.editor.cordon()
        if box is None:
            return None
        h, v, _ = vp.axes()
        a = vp.to_screen(box.mins[h], box.mins[v])
        b = vp.to_screen(box.maxs[h], box.maxs[v])
        x0, x1 = sorted((a.x(), b.x()))
        y0, y1 = sorted((a.y(), b.y()))
        x, y = pos.x(), pos.y()
        if not (x0 - EDGE_PX <= x <= x1 + EDGE_PX and y0 - EDGE_PX <= y <= y1 + EDGE_PX):
            return None
        eh = -1 if abs(x - x0) <= EDGE_PX else 1 if abs(x - x1) <= EDGE_PX else 0
        ev = -1 if abs(y - y0) <= EDGE_PX else 1 if abs(y - y1) <= EDGE_PX else 0
        # Bildschirm-y zeigt nach unten: obere Kante = größter Wert der senkrechten Achse
        if a.x() > b.x():
            eh = -eh
        if a.y() > b.y():
            ev = -ev
        if eh or ev:
            return eh, ev
        return "move"

    # ---- 2D -------------------------------------------------------------------------------
    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        h, v, d = vp.axes()
        wh, wv = vp.to_world(e.position())
        start = (float(self.editor.snap(wh)), float(self.editor.snap(wv)))
        box, _ = self.editor.cordon()
        hit = self._edges(vp, e.position())
        if hit is None or box is None:
            self.drag = {"mode": "new", "start": start, "screen": e.position(), "axes": (h, v, d)}
        else:
            self.drag = {"mode": hit, "start": start, "screen": e.position(), "axes": (h, v, d), "box": box}
        self.draft = None

    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if self.drag is None:
            return
        pos = e.position()
        s = self.drag["screen"]
        if self.draft is None and abs(pos.x() - s.x()) + abs(pos.y() - s.y()) < DRAG_PX:
            return
        h, v, d = self.drag["axes"]
        wh, wv = vp.to_world(pos)
        cur = (float(self.editor.snap(wh)), float(self.editor.snap(wv)))
        mode = self.drag["mode"]
        if mode == "new":
            (sh, sv), (ch, cv) = self.drag["start"], cur
            lo, hi = [0.0] * 3, [0.0] * 3
            lo[h], hi[h] = sorted((sh, ch))
            lo[v], hi[v] = sorted((sv, cv))
            lo[d], hi[d] = self._depth(d)
        else:
            box: BBox = self.drag["box"]
            lo, hi = list(box.mins), list(box.maxs)
            dh, dv = cur[0] - self.drag["start"][0], cur[1] - self.drag["start"][1]
            if mode == "move":
                lo[h], hi[h], lo[v], hi[v] = lo[h] + dh, hi[h] + dh, lo[v] + dv, hi[v] + dv
            else:
                eh, ev = mode
                for axis, edge, delta in ((h, eh, dh), (v, ev, dv)):
                    if edge < 0:
                        lo[axis] += delta
                    elif edge > 0:
                        hi[axis] += delta
        self.draft = BBox(tuple(lo), tuple(hi))  # type: ignore[arg-type]
        self.editor.redraw_requested.emit()

    def release_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if self.drag is None:
            return
        draft, self.drag, self.draft = self.draft, None, None
        if draft is None:
            return
        self.editor.set_cordon(draft, True)
        box, _ = self.editor.cordon()
        if box is not None:
            size = " × ".join(f"{b - a:.0f}" for a, b in zip(box.mins, box.maxs))
            self.editor.status_message.emit(tr('Bereich {0}: beim Kompilieren wird nur er gebaut').format(size))

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        hit = self._edges(vp, pos)
        if hit == "move":
            return Qt.SizeAllCursor
        if isinstance(hit, tuple):
            eh, ev = hit
            if eh and ev:
                # Ecke auf dem Bildschirm: links oben und rechts unten bekommen den fallenden Pfeil
                a, b = vp.to_screen(0, 0), vp.to_screen(1, 1)
                sx = eh if b.x() > a.x() else -eh
                sy = ev if b.y() > a.y() else -ev
                return Qt.SizeFDiagCursor if sx == sy else Qt.SizeBDiagCursor
            return Qt.SizeHorCursor if eh else Qt.SizeVerCursor
        return Qt.CrossCursor

    # ---- 3D -------------------------------------------------------------------------------
    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self.editor.status_message.emit(tr("Den Bereich in einer 2D-Ansicht ziehen"))

    # ---- Tasten ---------------------------------------------------------------------------
    def wants_key(self, key: int) -> bool:
        return key in (Qt.Key_Delete, Qt.Key_Escape)

    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        if e.key() == Qt.Key_Delete:
            if self.editor.cordon()[0] is not None:
                self.editor.set_cordon(None)
                self.editor.status_message.emit(tr("Bereich gelöscht: es wird wieder die ganze Map gebaut"))
            return True
        if e.key() == Qt.Key_Escape:
            if self.drag is not None:
                self.drag = self.draft = None
                self.editor.redraw_requested.emit()
            else:
                self.editor.set_tool("select")
            return True
        return False

    # ---- Zeichnen -------------------------------------------------------------------------
    def lines_2d(self, vp: "Viewport") -> np.ndarray | None:
        return box_lines(self.draft, DRAFT_COLOR) if self.draft is not None else None

    lines_3d = lines_2d


__all__ = ["CordonTool"]
