"""Seiten-Werkzeug (Face-Editor, wie Shift+A in Hammer): einzelne Seiten auswählen und
ihre Textur ausrichten.

In der 3D-Ansicht: Klick wählt eine Seite, Strg+Klick ergänzt, Shift+Klick gibt der
Seite sofort das aktuelle Material, Alt+Klick nimmt das Material der Seite auf (Pipette).
Die Werte stehen im Werkzeug-Panel.
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Callable

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent

from ...core.blocks import is_clip_member
from ...core.geometry.brush import ray_intersect_solid
from ...core.materials.apply import FaceRef, edit_faces, replace_material
from ...core.model import Face, Solid
from .base import Tool, _ray_box, _visible

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

FACE_COLOR = (1.0, 0.2, 0.2)


class _Signals(QObject):
    faces_changed = Signal()


class FaceTool(Tool):
    name = "face"
    label = "Seiten"
    shortcut = "Shift+A"
    hint = ("Seite anklicken, Strg+Klick ergänzt. Shift+Klick: aktuelles Material auf die Seite, "
            "Strg+Shift+Klick: überall umfärben, Alt+Klick: Material der Seite aufnehmen")

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.faces: list[FaceRef] = []
        self.signals = _Signals()
        editor.document_changed.connect(self._prune)
        editor.document_replaced.connect(self.clear)

    # ---- Auswahl ------------------------------------------------------------------------
    def clear(self) -> None:
        if self.faces:
            self.faces = []
            self.signals.faces_changed.emit()
            self.editor.redraw_requested.emit()

    def _prune(self) -> None:
        doc = self.editor.doc
        kept = [(sid, i) for sid, i in self.faces
                if isinstance(s := doc.get(sid), Solid) and i < len(s.faces)]
        changed = kept != self.faces
        self.faces = kept
        self.signals.faces_changed.emit()  # Werte im Panel auffrischen
        if changed:
            self.editor.redraw_requested.emit()

    def set_faces(self, refs: list[FaceRef]) -> None:
        self.faces = refs
        self.signals.faces_changed.emit()
        self.editor.redraw_requested.emit()

    def selected(self) -> list[tuple[FaceRef, Face]]:
        out = []
        for sid, i in self.faces:
            s = self.editor.doc.get(sid)
            if isinstance(s, Solid) and i < len(s.faces):
                out.append(((sid, i), s.faces[i]))
        return out

    def pick(self, origin: np.ndarray, direction: np.ndarray) -> FaceRef | None:
        o = tuple(float(c) for c in origin)
        d = tuple(float(c) for c in direction)
        best: tuple[float, Solid] | None = None
        for s in self.editor.doc.solids():
            if is_clip_member(s) or not _visible(self.editor, s):
                continue
            bb = s.bbox()
            if bb is None:
                continue
            t = _ray_box(origin, direction, bb)
            if t is None or (best is not None and t >= best[0]):
                continue
            t = ray_intersect_solid(s, o, d)  # type: ignore[arg-type]
            if t is not None and (best is None or t < best[0]):
                best = (t, s)
        if best is None:
            return None
        t, s = best
        hit = tuple(o[k] + d[k] * t for k in range(3))
        index, dist = -1, 1e30
        for i, f in enumerate(s.faces):
            pl = f.plane
            if sum(pl.normal[k] * d[k] for k in range(3)) >= 0:
                continue  # Rückseite
            gap = abs(sum(pl.normal[k] * hit[k] for k in range(3)) - pl.dist)
            if gap < dist:
                index, dist = i, gap
        return (s.id, index) if index >= 0 else None

    # ---- Bearbeiten ---------------------------------------------------------------------
    def edit(self, fn: Callable[[Face], Face], description: str, merge_key: object | None = None,
             refs: list[FaceRef] | None = None) -> bool:
        cmd = edit_faces(self.editor.doc, refs if refs is not None else self.faces, fn, description, merge_key)
        return cmd is not None and self.editor.run(cmd)

    def texture_size(self, material: str) -> tuple[int, int]:
        lib = self.editor.materials
        tex = lib.texture(material) if lib is not None else None
        return (tex.source_width, tex.source_height) if tex else (512, 512)

    def per_face(self, fn: Callable[[Face, list, tuple[int, int]], Face], description: str) -> bool:
        """Wie `edit`, aber `fn` bekommt zusätzlich Polygon und Texturgröße jeder Seite."""
        new: dict[int, Face] = {}
        for (sid, i), face in self.selected():
            s = self.editor.doc.get(sid)
            assert isinstance(s, Solid)
            poly = s.polygons()[i] or []
            new[id(face)] = fn(face, poly, self.texture_size(face.material))
        return self.edit(lambda f: new.get(id(f), f), description)

    def apply_material(self, material: str, refs: list[FaceRef] | None = None) -> bool:
        material = material.upper()
        return self.edit(lambda f: dataclasses.replace(f, material=material), "Material anwenden", refs=refs)

    def recolor(self, ref: FaceRef, material: str | None = None) -> bool:
        """Umfärben per Klick: Das Material dieser Seite wird in der ganzen Map ersetzt."""
        s = self.editor.doc.get(ref[0])
        if not isinstance(s, Solid) or ref[1] >= len(s.faces):
            return False
        old = s.faces[ref[1]].material
        new = (material or self.editor.current_material).upper()
        if old.upper() == new:
            return False
        cmd = replace_material(self.editor.doc, old, new)
        if cmd is None or not self.editor.run(cmd):
            return False
        self.editor.status_message.emit(f"Umgefärbt: {old} → {new}")
        return True

    # ---- Maus ---------------------------------------------------------------------------
    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        origin, direction = vp.ray(e.position())
        ref = self.pick(origin, direction)
        mods = e.modifiers()
        if ref is None:
            if not mods & Qt.ControlModifier:
                self.clear()
            return
        if mods & Qt.AltModifier:
            s = self.editor.doc.get(ref[0])
            assert isinstance(s, Solid)
            self.editor.set_current_material(s.faces[ref[1]].material)
            self.editor.status_message.emit(f"Material aufgenommen: {s.faces[ref[1]].material}")
            return
        if mods & Qt.ShiftModifier and mods & Qt.ControlModifier:
            self.recolor(ref)
            return
        if mods & Qt.ShiftModifier:
            self.apply_material(self.editor.current_material, [ref])
            return
        if mods & Qt.ControlModifier:
            refs = [r for r in self.faces if r != ref] if ref in self.faces else [*self.faces, ref]
            self.set_faces(refs)
        else:
            self.set_faces([ref])

    def cursor_3d(self, vp: "Viewport", pos) -> Qt.CursorShape:
        return Qt.PointingHandCursor

    def key_press(self, vp: "Viewport", e: QKeyEvent) -> bool:
        if e.key() == Qt.Key_Escape and self.faces:
            self.clear()
            return True
        return False

    # ---- Zeichnen -----------------------------------------------------------------------
    def lines_3d(self, vp: "Viewport") -> np.ndarray | None:
        rows: list[list[float]] = []
        for (sid, i), _f in self.selected():
            s = self.editor.doc.get(sid)
            assert isinstance(s, Solid)
            poly = s.polygons()[i]
            if not poly:
                continue
            for k in range(len(poly)):
                rows.append([*poly[k], *FACE_COLOR])
                rows.append([*poly[(k + 1) % len(poly)], *FACE_COLOR])
        return np.asarray(rows, dtype=np.float32).reshape(-1, 6) if rows else None
