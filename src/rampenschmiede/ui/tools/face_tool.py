"""Seiten-Werkzeug (Face-Editor, wie Shift+A in Hammer): einzelne Seiten auswählen und
ihre Textur ausrichten.

In der 3D-Ansicht: Klick wählt eine Seite, Strg+Klick ergänzt, Shift+Klick gibt der
Seite sofort das aktuelle Material, Alt+Klick nimmt das Material der Seite auf (Pipette).
Ziehen auf einer Seite verschiebt ihre Textur mit der Maus, Alt+Ziehen macht sie größer
(nach oben) oder kleiner (nach unten). Bei Rampen mit eingepasster Textur gilt das für die
ganze Rampe und landet in ihren Reglern. Die Werte stehen im Werkzeug-Panel.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

import numpy as np
from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent

from ...core.blocks import block_info, change_block, is_clip_member
from ...core.geometry.brush import ray_intersect_solid
from ...core.materials.apply import FaceRef, edit_faces, fitted_block, replace_material
from ...core.materials.texturing import scale_by, shift_by
from ...core.model import Face, Solid
from .base import Tool, _ray_box, _visible

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

FACE_COLOR = (1.0, 0.2, 0.2)
DRAG_THRESHOLD_PX = 4
#: Alt+Ziehen: so viele Pixel nach oben verdoppeln die Textur
SCALE_PX = 150.0


@dataclass
class _TexDrag:
    kind: str  # shift | scale
    ref: FaceRef
    press_pos: QPointF
    normal: tuple[float, float, float]
    dist: float
    start_hit: tuple[float, float, float]
    #: Rampe mit eingepasster Textur: ID der Wurzel und Regler beim Drücken
    root: int | None = None
    values: dict = field(default_factory=dict)
    axes: tuple = ()
    started: bool = False
    last: tuple[float, float, float] | float | None = None
    merge_key: object = field(default_factory=object)


class _Signals(QObject):
    faces_changed = Signal()


class FaceTool(Tool):
    name = "face"
    label = "Seiten"
    shortcut = "Shift+A"
    hint = ("Seite anklicken, Strg+Klick ergänzt. Ziehen: Textur verschieben, Alt+Ziehen: Textur größer/kleiner. "
            "Shift+Klick: aktuelles Material, Strg+Shift+Klick: überall umfärben, Alt+Klick: Material aufnehmen")

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.faces: list[FaceRef] = []
        self.signals = _Signals()
        self._drag: _TexDrag | None = None
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

    # ---- Textur ziehen -------------------------------------------------------------------
    def _begin_drag(self, vp: "Viewport", e: QMouseEvent, ref: FaceRef, kind: str) -> None:
        s = self.editor.doc.get(ref[0])
        assert isinstance(s, Solid)
        face = s.faces[ref[1]]
        origin, direction = vp.ray(e.position())
        hit = _plane_hit(origin, direction, face.plane.normal, face.plane.dist)
        if hit is None:
            return
        d = _TexDrag(kind, ref, e.position(), tuple(face.plane.normal), face.plane.dist, hit)  # type: ignore[arg-type]
        root = fitted_block(self.editor.doc, ref)
        if root is not None:
            info = block_info(root)
            assert info is not None
            d.root, d.values = root.id, dict(info["values"])
            d.axes = (face.uaxis.vec, face.vaxis.vec)
        self._drag = d

    def _drag_to(self, vp: "Viewport", e: QMouseEvent) -> None:
        d = self._drag
        assert d is not None
        if not d.started:
            moved = e.position() - d.press_pos
            if abs(moved.x()) + abs(moved.y()) < DRAG_THRESHOLD_PX:
                return
            d.started = True
            if d.ref not in self.faces:
                self.set_faces([d.ref])
        if d.kind == "scale":
            factor = 2 ** ((d.press_pos.y() - e.position().y()) / SCALE_PX)
            self._scale(d, factor)
            return
        origin, direction = vp.ray(e.position())
        hit = _plane_hit(origin, direction, d.normal, d.dist)
        if hit is not None:
            self._shift(d, tuple(hit[k] - d.start_hit[k] for k in range(3)))  # type: ignore[arg-type]

    def _shift(self, d: _TexDrag, total: tuple[float, float, float]) -> None:
        if d.root is not None:
            u, v = d.axes
            values = dict(d.values)
            values["textur_laengs"] = round(d.values.get("textur_laengs", 0) - _dot(total, u))
            values["textur_quer"] = round(d.values.get("textur_quer", 0) - _dot(total, v))
            self._change_block(d, values)
            return
        last = d.last if isinstance(d.last, tuple) else (0.0, 0.0, 0.0)
        step = tuple(total[k] - last[k] for k in range(3))
        d.last = total
        self.edit(lambda f: shift_by(f, step, self.texture_size(f.material)),  # type: ignore[arg-type]
                  "Textur verschieben", d.merge_key)

    def _scale(self, d: _TexDrag, factor: float) -> None:
        if d.root is not None:
            values = dict(d.values)
            values["textur_groesse"] = max(10, min(1000, round(d.values.get("textur_groesse", 100) * factor)))
            self._change_block(d, values)
            self.editor.status_message.emit(f"Textur-Größe {values['textur_groesse']} %")
            return
        last = d.last if isinstance(d.last, float) else 1.0
        step = factor / last
        d.last = factor
        self.edit(lambda f: scale_by(f, step, d.start_hit, self.texture_size(f.material)),
                  "Textur skalieren", d.merge_key)

    def _change_block(self, d: _TexDrag, values: dict) -> None:
        if d.root is None or self.editor.doc.get(d.root) is None:
            return
        info = block_info(self.editor.doc.get(d.root))
        if info is not None and all(info["values"].get(k) == v for k, v in values.items()):
            return
        cmd, _gen = change_block(self.editor.doc, d.root, values, merge_key=d.merge_key)
        self.editor.run(cmd)

    # ---- Maus ---------------------------------------------------------------------------
    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        origin, direction = vp.ray(e.position())
        ref = self.pick(origin, direction)
        mods = e.modifiers()
        self._drag = None
        if ref is None:
            if not mods & Qt.ControlModifier:
                self.clear()
            return
        if mods & Qt.AltModifier:
            # Klick nimmt das Material auf, Ziehen skaliert (entschieden beim Loslassen)
            self._begin_drag(vp, e, ref, "scale")
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
            return
        if ref not in self.faces:
            self.set_faces([ref])
        self._begin_drag(vp, e, ref, "shift")

    def move_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self._drag_to(vp, e)

    def release_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        d, self._drag = self._drag, None
        if d is None:
            return
        self.editor.stack.end_merge()
        if not d.started:
            if d.kind == "scale":
                self._pick_material(d.ref)
            return
        if d.root is not None:
            # Die Rampe wurde neu gebaut: die Seite unter der Maus wieder auswählen
            origin, direction = vp.ray(e.position())
            ref = self.pick(origin, direction)
            self.set_faces([ref] if ref is not None else [])
        self.editor.redraw_requested.emit()

    def _pick_material(self, ref: FaceRef) -> None:
        s = self.editor.doc.get(ref[0])
        if not isinstance(s, Solid) or ref[1] >= len(s.faces):
            return
        self.editor.set_current_material(s.faces[ref[1]].material)
        self.editor.status_message.emit(f"Material aufgenommen: {s.faces[ref[1]].material}")

    def cursor_3d(self, vp: "Viewport", pos) -> Qt.CursorShape:
        if self._drag is not None and self._drag.started:
            return Qt.ClosedHandCursor if self._drag.kind == "shift" else Qt.SizeVerCursor
        return Qt.PointingHandCursor

    def deactivate(self) -> None:
        self._drag = None

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


def _dot(a, b) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _plane_hit(origin, direction, normal, dist: float) -> tuple[float, float, float] | None:
    """Schnittpunkt des Mausstrahls mit der Ebene der Seite (auch außerhalb der Seite)."""
    denom = _dot(direction, normal)
    if abs(denom) < 1e-6:
        return None
    t = (dist - _dot(origin, normal)) / denom
    if t < 0 or not math.isfinite(t):
        return None
    return tuple(float(origin[k] + direction[k] * t) for k in range(3))  # type: ignore[return-value]
