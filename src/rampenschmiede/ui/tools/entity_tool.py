"""Entity-Werkzeug: Punkt-Entities setzen (Spawns, Lichter).

Schnellauswahl für die häufigsten (Spawns, Lichter, Cubemap, Teleport-Ziel); jede andere
Klasse aus der FGD lässt sich über die Suche setzen und bekommt deren Standardwerte.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from ...core.commands import AddObjects
from ...core.model import Entity, Solid
from .base import Tool, pick_3d

if TYPE_CHECKING:
    from ..viewports.viewport import Viewport

#: Abstand neuer Entities zur angeklickten Fläche, wenn die Schnellauswahl nichts sagt
DEFAULT_LIFT = 16

# Klassenname -> (Anzeigename, Standard-Keyvalues, Höhe des Ursprungs über der Fläche)
POINT_ENTITIES: dict[str, tuple[str, tuple[tuple[str, str], ...], int]] = {
    "info_player_counterterrorist": ("Spawn CT", (("angles", "0 0 0"),), 0),
    "info_player_terrorist": ("Spawn T", (("angles", "0 0 0"),), 0),
    "info_player_start": ("Spawn (Momentum)", (("angles", "0 0 0"),), 0),
    "light": ("Licht (Punkt)", (("_light", "255 255 255 200"), ("_lightHDR", "-1 -1 -1 1"),
                                 ("_quadratic_attn", "1"), ("style", "0")), 32),
    "light_spot": ("Licht (Spot)", (("_light", "255 255 255 400"), ("_lightHDR", "-1 -1 -1 1"),
                                     ("angles", "-90 0 0"), ("pitch", "-90"), ("_inner_cone", "30"),
                                     ("_cone", "45"), ("_exponent", "1"), ("_quadratic_attn", "1")), 64),
    "light_environment": ("Sonne (light_environment)", (("_light", "255 240 220 300"),
                                                        ("_ambient", "150 170 200 40"),
                                                        ("angles", "-50 45 0"), ("pitch", "-50")), 32),
    "env_cubemap": ("Cubemap", (("cubemapsize", "0"),), 64),
    "info_teleport_destination": ("Teleport-Ziel", (("angles", "0 0 0"),), 0),
}


class EntityTool(Tool):
    name = "entity"
    label = "Entity"
    shortcut = "Shift+E"
    hint = "Klick in eine Ansicht setzt die gewählte Entity"

    def __init__(self, editor) -> None:
        super().__init__(editor)
        self.classname = "info_player_counterterrorist"
        self.depth = 0  # Tiefe für 2D-Klicks (Höhe in der Oben-Ansicht)

    def preset(self) -> tuple[str, tuple[tuple[str, str], ...], int]:
        """Anzeigename, Start-Keyvalues und Abstand zur Fläche der gewählten Klasse. Klassen
        außerhalb der Schnellauswahl bekommen die Standardwerte aus der FGD."""
        hit = POINT_ENTITIES.get(self.classname)
        if hit is not None:
            return hit
        cls = self.editor.entity_catalog.get(self.classname)
        return (self.classname, cls.defaults() if cls else (), DEFAULT_LIFT)

    def _place(self, origin: tuple[int, int, int]) -> None:
        label, kvs, _ = self.preset()
        ent = Entity(
            id=self.editor.doc.new_id(),
            classname=self.classname,
            keyvalues=(("origin", f"{origin[0]} {origin[1]} {origin[2]}"), *kvs),
        )
        self.editor.run(AddObjects([ent], f"{label} setzen"))
        self.editor.set_selection({ent.id})

    def press_2d(self, vp: "Viewport", e: QMouseEvent) -> None:
        h, v, d = vp.axes()
        wh, wv = vp.to_world(e.position())
        origin = [0, 0, 0]
        origin[h] = self.editor.snap(wh)
        origin[v] = self.editor.snap(wv)
        sel = self.editor.selection_bbox()
        origin[d] = int(sel.center[d]) if sel else self.depth
        self._place(tuple(origin))  # type: ignore[arg-type]

    def press_3d(self, vp: "Viewport", e: QMouseEvent) -> None:
        o, direction = vp.ray(e.position())
        hit = pick_3d(self.editor, o, direction, roots=False)
        if hit is None:
            return
        point = o + direction * hit[1]
        normal = np.array([0.0, 0.0, 1.0])
        if isinstance(hit[0], Solid):
            face = min(hit[0].faces, key=lambda f: abs(f.plane.distance(tuple(point))))
            normal = np.array(face.plane.normal)
        lift = self.preset()[2]
        pos = point + normal * max(lift, 1)
        snap = self.editor.snap
        self._place((snap(pos[0]), snap(pos[1]), int(round(pos[2]))))

    def cursor_2d(self, vp: "Viewport", pos: QPointF) -> Qt.CursorShape:
        return Qt.CrossCursor
