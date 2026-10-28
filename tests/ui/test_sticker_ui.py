"""Aufkleber-Werkzeug: in 3D auf eine Fläche klicken setzt ein Overlay oder Decal."""
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from rampenschmiede.core.commands import AddObjects, solids_from_faces
from rampenschmiede.core.decals import DEFAULT_DECAL, sticker_corners
from rampenschmiede.core.geometry import primitives
from rampenschmiede.render.scene_mesh import build_object_mesh


def _mouse(kind, pos: QPointF):
    button = Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton
    return QMouseEvent(kind, pos, pos, button, Qt.LeftButton if button else Qt.NoButton, Qt.NoModifier)


def _setup(window):
    ed = window.editor
    wall = solids_from_faces(ed.doc, primitives.block((0, 0, 0), (256, 32, 256)))[0]
    ed.run(AddObjects([wall]))
    window.tool_actions["decal"].trigger()
    vp = next(v for v in window.grid_view.viewports() if v.is_3d)
    vp.center_on((128, 0, 128), 500)
    ed.set_grid(16)
    return ed, vp


def test_click_on_wall_places_upright_overlay(window):
    ed, vp = _setup(window)
    tool = ed.tool
    assert tool.name == "decal" and window.tool_options.currentWidget() is window.tool_options._pages["decal"]
    ed.set_current_material("BRICK/BRICKWALL001A")
    window.tool_options.sticker_size.setValue(64)
    # Ein Punkt auf der Vorderseite (y = 0), die zur Kamera zeigt
    pos = vp.project((120, 0, 130))
    tool.move_3d(vp, _mouse(QEvent.MouseMove, pos))
    assert tool.lines_3d(vp) is not None
    steps = len(ed.stack._undo)
    tool.press_3d(vp, _mouse(QEvent.MouseButtonPress, pos))
    assert len(ed.stack._undo) == steps + 1
    (oid,) = ed.selection
    ent = ed.doc.get(oid)
    assert ent.classname == "info_overlay" and ent.get("material") == "brick/brickwall001a"
    n, pts = sticker_corners(ent)
    face_normal_y = n[1]
    assert abs(abs(face_normal_y) - 1) < 1e-6
    assert all(abs(p[1]) < 1e-6 for p in pts)  # liegt in der Wand-Ebene
    assert ent.origin[0] % 16 == 0 and ent.origin[2] % 16 == 0
    assert build_object_mesh(ent).tris.shape == (6, 12)
    ed.undo()
    assert oid not in ed.doc


def test_decal_mode_needs_a_decal_material(window):
    ed, vp = _setup(window)
    tool = ed.tool
    window.tool_options.sticker_modes["decal"].click()
    assert not window.tool_options.sticker_size.isEnabled()
    ed.set_current_material("BRICK/BRICKWALL001A")
    tool.press_3d(vp, _mouse(QEvent.MouseButtonPress, vp.project((128, 0, 128))))
    (oid,) = ed.selection
    ent = ed.doc.get(oid)
    assert ent.classname == "infodecal" and ent.get("texture") == DEFAULT_DECAL
    ed.set_current_material("DECALS/OFFPAINTING")
    assert tool.material() == "decals/offpainting"
