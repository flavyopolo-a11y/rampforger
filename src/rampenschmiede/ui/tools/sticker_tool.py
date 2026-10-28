"""Aufkleber (Shift+T): Decals und Overlays mit einem Klick auf eine Fläche kleben.

In der 3D-Ansicht zeigt ein Rahmen unter der Maus, wo der Aufkleber landet; ein Klick setzt
ihn. Das Material kommt aus dem Material-Browser: Decals brauchen eines aus `decals/` (sonst
nimmt das Werkzeug ein Standard-Decal), Overlays nehmen jedes Material, auch Wandtexturen
für Wege oder Schilder. Overlays haben eine einstellbare Größe; Decals sind so groß wie ihr Bild.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from ...core.commands import AddObjects
from ...core.decals import DEFAULT_DECAL, LIFT, basis, make_decal, make_overlay
from ...core.materials.sizes import texture_size
from ...core.model import DEFAULT_MATERIAL, Solid
from ...i18n import tr
from .base import Tool, hit_solid_face, pick_3d

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

PREVIEW = (1.0, 0.6, 0.15)
DECAL_PREFIXES = ("decals/", "overlays/")


@dataclass
class StickerOptions:
    #: "decal" oder "overlay"
    mode: str = "overlay"
    #: Längere Seite eines Overlays in Units
    size: int = 128


class StickerTool(Tool):
    name = "decal"
    label = "Aufkleber"
    shortcut = "Shift+T"
    hint = ("Aufkleber: Material im Browser wählen und in 3D auf eine Fläche klicken. Overlay = beliebige Größe "
            "und jedes Material, Decal = Bild aus decals/ in Originalgröße")

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.options = StickerOptions()
        self.preview: list[tuple[float, float, float]] | None = None

    def deactivate(self) -> None:
        self.preview = None

    # ---- Material und Größe ---------------------------------------------------------------
    def material(self) -> str:
        cur = (self.editor.current_material or "").lower()
        if cur.startswith(DECAL_PREFIXES):
            return cur
        if self.options.mode == "overlay" and cur and not cur.startswith("tools/") and cur != DEFAULT_MATERIAL.lower():
            return cur
        return DEFAULT_DECAL

    def size(self, material: str) -> tuple[float, float]:
        w, h = texture_size(material)
        if self.options.mode == "decal":
            return float(w), float(h)
        longest = max(w, h) or 1
        return self.options.size * w / longest, self.options.size * h / longest

    # ---- Treffer --------------------------------------------------------------------------
    def _hit(self, vp: "Viewport", pos: QPointF):
        """(Punkt, Normale) der Fläche unter der Maus, oder None."""
        origin, direction = vp.ray(pos)
        hit = pick_3d(self.editor, origin, direction, roots=False)
        if hit is None or not isinstance(hit[0], Solid):
            return None
        solid: Solid = hit[0]
        o = tuple(float(c) for c in origin)
        d = tuple(float(c) for c in direction)
        face_hit = hit_solid_face(solid, o, d)
        if face_hit is None:
            return None
        t, index = face_hit
        p = tuple(o[k] + d[k] * t for k in range(3))
        if index is None:
            # Die Seite, in deren Ebene der Punkt liegt und die zur Kamera zeigt
            best = None
            for i, f in enumerate(solid.faces):
                n = f.plane.normal
                off = abs(sum(n[k] * p[k] for k in range(3)) - f.plane.dist)
                facing = sum(n[k] * d[k] for k in range(3))
                if off < 0.5 and facing < 0 and (best is None or facing < best[1]):
                    best = (i, facing)
            if best is None:
                return None
            index = best[0]
        n = solid.faces[index].plane.normal
        return p, (float(n[0]), float(n[1]), float(n[2]))

    def _snap_in_plane(self, p, n):
        """Punkt in der Ebene ans Raster legen (nur entlang der Ebene, nicht aus ihr heraus)."""
        g = self.editor.snap
        q = [float(g(c)) for c in p]
        axis = max(range(3), key=lambda k: abs(n[k]))
        q[axis] = p[axis]
        if abs(n[axis]) < 0.999:  # schräge Fläche: auf die Ebene zurück
            dist = sum(n[k] * p[k] for k in range(3))
            q[axis] = (dist - sum(n[k] * q[k] for k in range(3) if k != axis)) / n[axis]
        return tuple(q)

    # ---- 3D -------------------------------------------------------------------------------
    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() != Qt.LeftButton:
            return
        hit = self._hit(vp, e.position())
        if hit is None:
            self.editor.status_message.emit(tr("Auf eine Fläche klicken"))
            return
        self.place(*hit)

    def place(self, point, normal) -> int:
        ed = self.editor
        material = self.material()
        w, h = self.size(material)
        p = self._snap_in_plane(point, normal)
        if self.options.mode == "decal":
            ent = make_decal(ed.doc, p, normal, material, (int(w), int(h)))
        else:
            ent = make_overlay(ed.doc, p, normal, material, w, h)
        ed.run(AddObjects([ent], "Aufkleber"))
        ed.set_selection([ent.id])
        kind = "Decal" if self.options.mode == "decal" else "Overlay"
        note = "" if material == (ed.current_material or "").lower() else tr(" (Standard-Decal: im Browser ein decals/-Material wählen)")
        ed.status_message.emit(f"{kind} {material} gesetzt{note}")
        return ent.id

    def move_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        hit = self._hit(vp, e.position())
        if hit is None:
            if self.preview is not None:
                self.preview = None
                self.editor.redraw_requested.emit()
            return
        p, n = hit
        p = self._snap_in_plane(p, n)
        w, h = self.size(self.material())
        u, v = basis(n)
        hw, hh = w / 2, h / 2
        self.preview = [tuple(p[k] + u[k] * a + v[k] * b + n[k] * LIFT * 2 for k in range(3))
                        for a, b in ((-hw, -hh), (-hw, hh), (hw, hh), (hw, -hh))]
        self.editor.redraw_requested.emit()

    def cursor_3d(self, vp: "Viewport", pos) -> Qt.CursorShape:
        return Qt.CrossCursor

    # ---- 2D -------------------------------------------------------------------------------
    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if e.button() == Qt.LeftButton:
            self.editor.status_message.emit(tr("Aufkleber in der 3D-Ansicht auf eine Fläche klicken"))

    # ---- Tasten ---------------------------------------------------------------------------
    def wants_key(self, key: int) -> bool:
        return key == Qt.Key_Escape

    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        if e.key() == Qt.Key_Escape:
            self.editor.set_tool("select")
            return True
        return False

    # ---- Zeichnen -------------------------------------------------------------------------
    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        if not self.preview:
            return None
        out = []
        for i in range(4):
            a, b = self.preview[i], self.preview[(i + 1) % 4]
            out += [[*a, *PREVIEW], [*b, *PREVIEW]]
        a, b, c, d = self.preview
        out += [[*a, *PREVIEW], [*c, *PREVIEW], [*b, *PREVIEW], [*d, *PREVIEW]]
        return np.asarray(out, dtype=np.float32)


__all__ = ["StickerOptions", "StickerTool"]
