"""Gelände-Werkzeug im Fenster: umwandeln, malen (ein Undo-Schritt), Shift kehrt um, Vorlagen."""
import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from rampenschmiede.core.commands import AddObjects, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.geometry.displacement import is_displacement_solid, surfaces


def _mouse(kind, pos: QPointF, buttons=Qt.LeftButton, mods=Qt.NoModifier):
    button = Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton
    return QMouseEvent(kind, pos, pos, button, buttons, mods)


def _top_view(window):
    return next(vp for vp in window.grid_view.viewports() if not vp.is_3d and vp.axes()[:2] == (0, 1))


def _terrain(window, power_index=1):
    ed = window.editor
    s = solids_from_faces(ed.doc, primitives.block((0, 0, 0), (512, 512, 16)))[0]
    ed.run(AddObjects([s]))
    ed.set_selection({s.id})
    window.tool_actions["terrain"].trigger()
    assert ed.tool.name == "terrain"
    assert window.tool_options.currentWidget() is window.tool_options._pages["terrain"]
    assert ed.tool.convert_selection() == 1
    return ed.doc.get(s.id)


def _peak(window, sid):
    return float(surfaces(window.editor.doc.get(sid))[0].positions[:, 2].max())


def test_convert_and_paint_from_top_view_is_one_undo_step(window):
    ed = window.editor
    s = _terrain(window)
    assert is_displacement_solid(s)
    tool = ed.tool
    vp = _top_view(window)
    steps = len(ed.stack._undo)
    a, b = vp.to_screen(200, 256), vp.to_screen(320, 256)
    tool.press_2d(vp, _mouse(QEvent.MouseButtonPress, a))
    for t in np.linspace(0, 1, 8):
        tool.move_2d(vp, _mouse(QEvent.MouseMove, a + (b - a) * float(t)))
    tool.release_2d(vp, _mouse(QEvent.MouseButtonRelease, b))
    assert _peak(window, s.id) > 16 + tool.strength
    assert len(ed.stack._undo) == steps + 1
    assert tool.lines_2d(vp) is not None and len(tool.lines_2d(vp)) > 0
    ed.stack.undo()
    assert _peak(window, s.id) == 16


def test_shift_lowers_and_mode_buttons(window):
    ed = window.editor
    s = _terrain(window)
    tool = ed.tool
    vp = _top_view(window)
    p = vp.to_screen(256, 256)
    tool.press_2d(vp, _mouse(QEvent.MouseButtonPress, p, mods=Qt.ShiftModifier))
    tool.release_2d(vp, _mouse(QEvent.MouseButtonRelease, p))
    assert float(surfaces(ed.doc.get(s.id))[0].positions[:, 2].min()) < 16
    window.tool_options.terrain_modes["alpha"].click()
    assert tool.mode == "alpha"
    tool.press_2d(vp, _mouse(QEvent.MouseButtonPress, p))
    tool.release_2d(vp, _mouse(QEvent.MouseButtonRelease, p))
    assert surfaces(ed.doc.get(s.id))[0].disp.alphas.max() > 0


def test_brackets_change_brush_size_not_grid(window):
    ed = window.editor
    _terrain(window)
    tool = ed.tool
    vp = _top_view(window)
    grid = ed.grid
    radius = tool.radius
    vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_BracketRight, Qt.NoModifier, "]"))
    assert tool.radius > radius and ed.grid == grid
    assert window.tool_options.terrain_radius.value() == int(tool.radius)
    # Das Werkzeug hat Vorrang vor dem Raster-Kürzel (ShortcutOverride annehmen), andere nicht
    override = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_BracketLeft, Qt.NoModifier, "[")
    override.ignore()
    vp.event(override)
    assert override.isAccepted()
    window.tool_actions["select"].trigger()
    override = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_BracketLeft, Qt.NoModifier, "[")
    override.ignore()
    vp.event(override)
    assert not override.isAccepted()


def test_terrain_template_from_library(window):
    ed = window.editor
    before = len(list(ed.doc.solids()))
    window.library.insert("gelaende_huegel", (0.0, 0.0, 0.0))
    new = [s for s in ed.doc.solids()][before:]
    assert new and all(is_displacement_solid(s) and s.parent_id is None for s in new)
    assert ed.selection == {s.id for s in new}


def test_3d_pick_hits_terrain_surface(window):
    ed = window.editor
    s = _terrain(window)
    from rampenschmiede.ui.tools.base import pick_3d

    hit = pick_3d(ed, np.array([256.0, 256.0, 400.0]), np.array([0.0, 0.0, -1.0]))
    assert hit is not None and hit[0].id == s.id and hit[1] == 384
