"""Props streuen: Klicken oder Ziehen verteilt Modelle zufällig im Kreis auf Boden und Gelände.

Die Modelle kommen aus dem Modell-Browser (das gerade gewählte) oder aus einem Detail-Kit.
Shift entfernt die Props dieser Modelle im Kreis. Ein Strich ist ein Undo-Schritt.
"""
from __future__ import annotations

import itertools
import math
import random
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from ...core.commands import SwapObjects
from ...core.models.scatter import (
    KITS_BY_KEY,
    Ground,
    ScatterSettings,
    kit_models,
    props_in_circle,
    scatter,
)
from ...i18n import tr
from .base import Tool, _visible, pick_3d

if TYPE_CHECKING:
    from ..panels.model_browser import ModelBrowser
    from ..viewports.viewport import Viewport

#: Quelle der Modelle: das im Modell-Browser gewählte
FROM_BROWSER = "browser"
RING_COLOR = (0.95, 0.75, 0.3)
_strokes = itertools.count(1)


class ScatterTool(Tool):
    name = "scatter"
    label = "Streuen"
    shortcut = "Shift+D"
    hint = ("Klicken oder ziehen verteilt Props im Kreis (Modell aus dem Modell-Browser oder ein Kit). "
            "Shift entfernt sie wieder, [ und ] ändern die Größe")

    def __init__(self, editor, browser: "ModelBrowser") -> None:
        super().__init__(editor)
        self.browser = browser
        self.settings = ScatterSettings()
        self.source = FROM_BROWSER
        #: Abgewählte Modelle des Kits
        self.disabled: set[str] = set()
        self.hover: tuple[float, float, float] | None = None
        self._stroke: object | None = None
        self._last: np.ndarray | None = None
        self._erase = False
        self._rng = random.Random()
        self.on_change = None

    def deactivate(self) -> None:
        self.hover = None
        self._stroke = None

    # ---- Modelle ---------------------------------------------------------------------------
    def kit_names(self) -> list[str]:
        """Alle Modelle des gewählten Kits, die es im Spiel gibt."""
        lib = self.editor.models
        kit = KITS_BY_KEY.get(self.source)
        if lib is None or kit is None:
            return []
        return kit_models(kit, lib.names())

    def models(self) -> list[str]:
        if self.source == FROM_BROWSER:
            name = self.browser.current_name()
            return [name] if name else []
        return [n for n in self.kit_names() if n not in self.disabled]

    def set_source(self, source: str) -> None:
        self.source = source
        self.disabled = set()
        kit = KITS_BY_KEY.get(source)
        if kit is not None:
            self.settings.align = kit.align
        if self.on_change is not None:
            self.on_change()

    # ---- Streuen -----------------------------------------------------------------------------
    def _ground(self) -> Ground:
        ed = self.editor
        solids = [s for s in ed.doc.solids() if _visible(ed, s)]
        return Ground(solids, self.settings.terrain_only)

    def dab(self, center) -> int:
        """Ein Klick: Props streuen oder (Shift) entfernen. Gibt die Anzahl zurück."""
        ed = self.editor
        if self._stroke is None:
            self._stroke = ("scatter", next(_strokes))
        models = self.models()
        if not models:
            ed.status_message.emit(tr("Erst im Modell-Browser ein Modell anklicken oder links ein Kit wählen")
                                   if self.source == FROM_BROWSER else tr("Im Kit ist kein Modell gewählt"))
            return 0
        if self._erase:
            gone = props_in_circle(ed.doc, center, self.settings.radius, models)
            if gone:
                ed.run(SwapObjects(gone, [], tr("Props streuen"), self._stroke))
            return len(gone)
        new = scatter(ed.doc, self._ground(), center, models, ed.models, self.settings, self._rng)
        if new:
            ed.run(SwapObjects([], new, tr("Props streuen"), self._stroke))
        return len(new)

    def begin(self, center, erase: bool = False) -> int:
        self._stroke = ("scatter", next(_strokes))
        self._erase = erase
        self._last = np.asarray(center, dtype=np.float64)
        return self.dab(center)

    def drag(self, center) -> None:
        if self._stroke is None or self._last is None:
            return
        c = np.asarray(center, dtype=np.float64)
        if math.hypot(*(c - self._last)[:2]) < self.settings.radius * 0.6:
            return
        self._last = c
        self.dab(center)

    def end(self) -> None:
        self._stroke = None
        self._last = None
        self._erase = False

    # ---- Maus ---------------------------------------------------------------------------------
    def _point_3d(self, vp: "Viewport", pos: QPointF):
        origin, direction = vp.ray(pos)
        hit = pick_3d(self.editor, origin, direction, roots=False)
        if hit is None:
            return None
        p = origin + direction * hit[1]
        return float(p[0]), float(p[1]), float(p[2])

    def _point_2d(self, vp: "Viewport", pos: QPointF):
        if vp.axes()[:2] != (0, 1):
            return None  # nur von oben: von vorne oder der Seite ist die Fläche unklar
        x, y = vp.to_world(pos)
        bb = self.editor.doc.bbox()
        top = (bb.maxs[2] + 16) if bb is not None else 1024.0
        z = self._ground().height(x, y, top, top - (bb.mins[2] if bb is not None else -1024.0) + 32)
        return (x, y, z if z is not None else 0.0)

    def _press(self, point, e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        if point is None:
            self.editor.status_message.emit(tr("Props streut man in 3D oder in der Ansicht von oben"))
            return
        self.hover = point
        self.begin(point, bool(e.modifiers() & Qt.ShiftModifier))
        self.editor.redraw_requested.emit()

    def _move(self, point) -> None:
        self.hover = point
        if point is not None and self._stroke is not None:
            self.drag(point)
        self.editor.redraw_requested.emit()

    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        self._press(self._point_2d(vp, e.position()), e)

    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        self._move(self._point_2d(vp, e.position()))

    def release_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self.end()

    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        self._press(self._point_3d(vp, e.position()), e)

    def move_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        self._move(self._point_3d(vp, e.position()))

    def release_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self.end()

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        return Qt.CrossCursor

    def cursor_3d(self, vp: "Viewport", pos) -> Qt.CursorShape:
        return Qt.CrossCursor

    def wants_key(self, key: int) -> bool:
        return key in (Qt.Key_BracketLeft, Qt.Key_BracketRight)

    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        if e.key() in (Qt.Key_BracketLeft, Qt.Key_BracketRight):
            factor = 1.25 if e.key() == Qt.Key_BracketRight else 0.8
            self.settings.radius = float(min(4096, max(32, round(self.settings.radius * factor / 16) * 16)))
            self.editor.status_message.emit(f"Streu-Kreis {int(self.settings.radius)} Units")
            if self.on_change is not None:
                self.on_change()
            self.editor.redraw_requested.emit()
            return True
        if e.key() == Qt.Key_Escape:
            self.editor.set_tool("select")
            return True
        return False

    # ---- Zeichnen -------------------------------------------------------------------------------
    def ring(self) -> np.ndarray | None:
        if self.hover is None:
            return None
        c = np.asarray(self.hover, dtype=np.float64)
        r = self.settings.radius
        t = np.linspace(0, 2 * math.pi, 49)
        pts = np.stack([c[0] + r * np.cos(t), c[1] + r * np.sin(t), np.full_like(t, c[2] + 2)], axis=1)
        rows = np.concatenate([np.stack([pts[:-1], pts[1:]], axis=1).reshape(-1, 3)])
        return np.hstack([rows, np.tile(RING_COLOR, (len(rows), 1))]).astype(np.float32)

    def lines_2d(self, vp: "Viewport") -> np.ndarray | None:
        return self.ring()

    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        return self.ring()


__all__ = ["FROM_BROWSER", "ScatterTool"]
