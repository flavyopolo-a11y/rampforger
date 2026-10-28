"""Gelände formen: mit einem runden Pinsel über Displacements ziehen.

In 3D wird dort gemalt, wo der Strahl das Gelände trifft. In 2D zählt nur der Abstand in der
Ansichts-Ebene (von oben: der ganze Hang unter dem Kreis). Shift kehrt die Pinsel-Art um
(heben ↔ senken, Textur malen ↔ wegnehmen), [ und ] ändern die Größe. Ein Strich ist ein
Undo-Schritt; beim Loslassen werden die Nähte zu Nachbar-Flächen geschlossen.
"""
from __future__ import annotations

import itertools
import math
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from ...core.commands import ReplaceObjects
from ...core.geometry.displacement import BRUSH_MODES, is_displacement_solid, solid_ray_face
from ...core.model import Solid
from ...core.terrain import TerrainError, convert, flatten, sew_all, stroke, terrain_solids
from .base import Tool, _visible

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

MODE_LABELS = {
    "heben": "Heben", "senken": "Senken", "glaetten": "Glätten", "rauschen": "Rauschen", "ebnen": "Ebnen",
    "alpha": "Textur malen", "alpha_weg": "Textur weg",
}
MODE_HELP = {
    "heben": "Hebt das Gelände unter dem Pinsel an (Shift: senken)",
    "senken": "Senkt das Gelände (Shift: heben)",
    "glaetten": "Gleicht Kanten und Spitzen aus",
    "rauschen": "Macht die Fläche unruhig, wie Felsen oder Erde",
    "ebnen": "Zieht alles unter dem Pinsel auf eine Höhe",
    "alpha": "Malt die zweite Textur eines Überblend-Materials (z. B. Gras auf Kies) auf (Shift: weg)",
    "alpha_weg": "Nimmt die zweite Textur wieder weg (Shift: malen)",
}
INVERSE = {"heben": "senken", "senken": "heben", "alpha": "alpha_weg", "alpha_weg": "alpha"}
RING_COLOR = (0.35, 0.95, 0.45)
RADIUS_STEPS = (16, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024)
_strokes = itertools.count(1)


class TerrainTool(Tool):
    name = "terrain"
    label = "Gelände"
    shortcut = "Shift+G"
    hint = ("Über das Gelände ziehen formt es. Shift kehrt um, [ und ] ändern die Pinselgröße. "
            "Neue Hügel: Brushes auswählen und rechts „Zu Gelände machen“")

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.mode = "heben"
        self.radius = 128.0
        self.strength = 8.0
        self.power = 3
        #: Pinsel-Mitte unter der Maus und die Achse, die dabei nicht zählt (2D: Blickrichtung)
        self.hover: tuple[float, float, float] | None = None
        self.hover_normal: tuple[float, float, float] = (0.0, 0.0, 1.0)
        self.ignore_axis: int | None = None
        self._stroke: object | None = None
        self._last: np.ndarray | None = None
        self._touched: dict[int, Solid] = {}
        self._invert = False
        #: Wird nach Änderungen an Größe oder Art aufgerufen (Options-Panel)
        self.on_change = None

    def deactivate(self) -> None:
        self.hover = None
        self._stroke = None

    # ---- Befehle für das Options-Panel ---------------------------------------------------
    def set_mode(self, mode: str) -> None:
        if mode in BRUSH_MODES:
            self.mode = mode

    def convert_selection(self) -> int:
        """Ausgewählte Brushes zu Gelände machen (ihre Oberseite). Gibt die Anzahl zurück."""
        ed = self.editor
        new, problems = [], []
        for obj in ed.selected_objects():
            if not isinstance(obj, Solid):
                continue
            try:
                converted = convert(ed.doc, obj, self.power)
            except TerrainError as exc:
                problems.append(str(exc))
                continue
            if converted is not obj:
                new.append(converted)
        if new:
            ed.run(ReplaceObjects(new, "Zu Gelände machen"))
            ed.status_message.emit(f"{len(new)} Brush(es) sind jetzt Gelände. Darüber ziehen formt es.")
        elif problems:
            ed.status_message.emit(problems[0])
        else:
            ed.status_message.emit("Erst einen oder mehrere Brushes auswählen")
        return len(new)

    def flatten_selection(self) -> int:
        ed = self.editor
        new = [flatten(o) for o in ed.selected_objects() if isinstance(o, Solid) and is_displacement_solid(o)]
        if new:
            ed.run(ReplaceObjects(new, "Gelände entfernen"))
        return len(new)

    def sew(self) -> int:
        changed = sew_all(self.editor.doc)
        if changed:
            self.editor.run(ReplaceObjects(changed, "Nähte schließen"))
        self.editor.status_message.emit(f"Nähte geschlossen ({len(changed)} Brush(es) angepasst)"
                                        if changed else "Alle Nähte sind schon geschlossen")
        return len(changed)

    # ---- Pinsel ---------------------------------------------------------------------------
    def _targets(self) -> list[Solid]:
        ed = self.editor
        return [s for s in terrain_solids(ed.doc) if _visible(ed, s)]

    def current_mode(self) -> str:
        return INVERSE.get(self.mode, self.mode) if self._invert else self.mode

    def dab(self, center, ignore_axis: int | None = None) -> int:
        """Ein Pinselabdruck. Gibt die Anzahl geänderter Brushes zurück."""
        if self._stroke is None:
            self._stroke = ("terrain", next(_strokes))
        changed = stroke(self._targets(), center, self.radius, self.strength, self.current_mode(),
                         ignore_axis=ignore_axis, seed=int(next(_strokes)))
        if changed:
            self.editor.run(ReplaceObjects(changed, "Gelände formen", self._stroke))
            for s in changed:
                self._touched[s.id] = s
        return len(changed)

    def begin(self, center, ignore_axis: int | None, invert: bool) -> None:
        self._stroke = ("terrain", next(_strokes))
        self._touched = {}
        self._invert = invert
        self._last = np.asarray(center, dtype=np.float64)
        self.dab(center, ignore_axis)

    def drag(self, center, ignore_axis: int | None) -> None:
        if self._stroke is None or self._last is None:
            return
        c = np.asarray(center, dtype=np.float64)
        delta = c - self._last
        if ignore_axis is not None:
            delta[ignore_axis] = 0.0
        # Abdrücke im Abstand eines Fünftels der Pinselgröße, damit der Strich gleichmäßig wird
        if np.linalg.norm(delta) < max(self.radius * 0.2, 1.0):
            return
        self._last = c
        self.dab(center, ignore_axis)

    def end(self) -> None:
        if self._stroke is None:
            return
        if self._touched:
            ids = set(self._touched)
            latest = [s for s in (self.editor.doc.get(i) for i in ids) if isinstance(s, Solid)]
            sewn = sew_all(self.editor.doc, latest)
            if sewn:
                self.editor.run(ReplaceObjects(sewn, "Gelände formen", self._stroke))
        self._stroke = None
        self._last = None
        self._touched = {}
        self._invert = False

    # ---- Maus ------------------------------------------------------------------------------
    def _hit_3d(self, vp: "Viewport", pos: QPointF):
        origin, direction = vp.ray(pos)
        o = tuple(float(c) for c in origin)
        d = tuple(float(c) for c in direction)
        best = None
        for s in self._targets():
            hit = solid_ray_face(s, o, d)
            if hit is not None and (best is None or hit[0] < best[0]):
                best = (hit[0], s, hit[1])
        if best is None:
            return None
        p = origin + direction * best[0]
        n = best[1].faces[best[2]].plane.normal
        return (float(p[0]), float(p[1]), float(p[2])), (float(n[0]), float(n[1]), float(n[2]))

    def _point_2d(self, vp: "Viewport", pos: QPointF):
        h, v, depth = vp.axes()
        wh, wv = vp.to_world(pos)
        p = [0.0, 0.0, 0.0]
        if self.hover is not None:
            p[depth] = self.hover[depth]
        p[h], p[v] = wh, wv
        return (p[0], p[1], p[2]), depth

    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        point, depth = self._point_2d(vp, e.position())
        self.hover, self.ignore_axis = point, depth
        self._set_view_normal(depth)
        self.begin(point, depth, bool(e.modifiers() & Qt.ShiftModifier))
        self.editor.redraw_requested.emit()

    def move_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        point, depth = self._point_2d(vp, e.position())
        self.hover, self.ignore_axis = point, depth
        self._set_view_normal(depth)
        if self._stroke is not None:
            self._invert = bool(e.modifiers() & Qt.ShiftModifier)
            self.drag(point, depth)
        self.editor.redraw_requested.emit()

    def release_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self.end()

    def _set_view_normal(self, depth: int) -> None:
        n = [0.0, 0.0, 0.0]
        n[depth] = 1.0
        self.hover_normal = (n[0], n[1], n[2])

    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        hit = self._hit_3d(vp, e.position())
        if hit is None:
            self.editor.status_message.emit("Hier ist kein Gelände. Brushes auswählen und „Zu Gelände machen“")
            return
        self.hover, self.hover_normal = hit
        self.ignore_axis = None
        self.begin(hit[0], None, bool(e.modifiers() & Qt.ShiftModifier))
        self.editor.redraw_requested.emit()

    def move_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        hit = self._hit_3d(vp, e.position())
        self.ignore_axis = None
        if hit is None:
            if self._stroke is None:
                self.hover = None
            self.editor.redraw_requested.emit()
            return
        self.hover, self.hover_normal = hit
        if self._stroke is not None:
            self._invert = bool(e.modifiers() & Qt.ShiftModifier)
            self.drag(hit[0], None)
        self.editor.redraw_requested.emit()

    def release_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self.end()

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        return Qt.CrossCursor

    def cursor_3d(self, vp: "Viewport", pos) -> Qt.CursorShape:
        return Qt.CrossCursor

    def wants_key(self, key: int) -> bool:
        return key in (Qt.Key_BracketLeft, Qt.Key_BracketRight)

    def grow(self, steps: int) -> float:
        """Pinselgröße eine Stufe größer (steps > 0) oder kleiner."""
        sizes = list(RADIUS_STEPS)
        k = min(range(len(sizes)), key=lambda i: abs(sizes[i] - self.radius))
        self.radius = float(sizes[max(0, min(len(sizes) - 1, k + steps))])
        self.editor.status_message.emit(f"Pinselgröße {int(self.radius)} Units")
        if self.on_change is not None:
            self.on_change()
        self.editor.redraw_requested.emit()
        return self.radius

    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        if e.key() == Qt.Key_BracketLeft:
            self.grow(-1)
            return True
        if e.key() == Qt.Key_BracketRight:
            self.grow(1)
            return True
        if e.key() == Qt.Key_Escape:
            self.editor.set_tool("select")
            return True
        return False

    # ---- Zeichnen -----------------------------------------------------------------------------
    def ring(self) -> np.ndarray | None:
        """Kreis um die Pinsel-Mitte, quer zur Normale der Fläche (bzw. der Blickrichtung)."""
        if self.hover is None:
            return None
        c = np.asarray(self.hover, dtype=np.float64)
        n = np.asarray(self.hover_normal, dtype=np.float64)
        n /= max(np.linalg.norm(n), 1e-9)
        a = np.cross(n, (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0))
        a /= np.linalg.norm(a)
        b = np.cross(n, a)
        rows = []
        for r in (self.radius, self.radius * 0.5):
            steps = 48
            pts = [c + (a * math.cos(t) + b * math.sin(t)) * r
                   for t in np.linspace(0, 2 * math.pi, steps + 1)]
            for p, q in zip(pts[:-1], pts[1:]):
                rows += [[*p, *RING_COLOR], [*q, *RING_COLOR]]
        return np.asarray(rows, dtype=np.float32)

    def lines_2d(self, vp: "Viewport") -> np.ndarray | None:
        return self.ring() if self.ignore_axis is not None else self._flat_ring(vp)

    def _flat_ring(self, vp: "Viewport") -> np.ndarray | None:
        if self.hover is None:
            return None
        saved = self.hover_normal
        depth = vp.axes()[2]
        self._set_view_normal(depth)
        ring = self.ring()
        self.hover_normal = saved
        return ring

    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        return self.ring() if self.ignore_axis is None else None


__all__ = ["MODE_HELP", "MODE_LABELS", "TerrainTool"]
