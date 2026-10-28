"""Bereich (Cordon) im Fenster: ziehen, ändern, löschen, nur ihn kompilieren."""
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from rampenschmiede.core.commands import AddObjects, solids_from_faces
from rampenschmiede.core.geometry import primitives


def _mouse(kind, pos: QPointF):
    button = Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton
    return QMouseEvent(kind, pos, pos, button, Qt.LeftButton, Qt.NoModifier)


def _drag(tool, vp, a, b):
    tool.press_2d(vp, _mouse(QEvent.MouseButtonPress, vp.to_screen(*a)))
    tool.move_2d(vp, _mouse(QEvent.MouseMove, vp.to_screen(*b)))
    tool.release_2d(vp, _mouse(QEvent.MouseButtonRelease, vp.to_screen(*b)))


def _top(window):
    vp = next(v for v in window.grid_view.viewports() if not v.is_3d and v.axes()[:2] == (0, 1))
    vp.cam2d.zoom, vp.cam2d.center_h, vp.cam2d.center_v = 0.25, 512, 512
    return vp


def test_drag_resize_and_delete_cordon(window):
    ed = window.editor
    near = solids_from_faces(ed.doc, primitives.block((0, 0, 0), (256, 256, 64)))[0]
    far = solids_from_faces(ed.doc, primitives.block((3000, 3000, 0), (3256, 3256, 64)))[0]
    ed.run(AddObjects([near, far]))
    ed.set_grid(64)
    window.tool_actions["cordon"].trigger()
    tool = ed.tool
    assert tool.name == "cordon"
    assert window.tool_options.currentWidget() is window.tool_options._pages["cordon"]
    vp = _top(window)
    _drag(tool, vp, (-128, -128), (512, 512))
    box, on = ed.cordon()
    assert on and box.mins[:2] == (-128, -128) and box.maxs[:2] == (512, 512)
    assert box.mins[2] <= 0 and box.maxs[2] >= 64  # Tiefe über die ganze Map
    assert window.act_cordon.isChecked() and window.tool_options.cordon_on.isChecked()
    assert ed.cordon_lines() is not None and not ed.stack.is_clean()
    # Rechte Kante ziehen
    _drag(tool, vp, (512, 192), (768, 192))
    box, _ = ed.cordon()
    assert box.maxs[0] == 768 and box.mins[0] == -128 and box.maxs[1] == 512
    # Innen ziehen verschiebt
    _drag(tool, vp, (192, 192), (256, 192))
    box, _ = ed.cordon()
    assert box.mins[0] == -64 and box.maxs[0] == 832

    doc, res = window.compiler.build_doc()
    assert near.id in doc and far.id not in doc and res.dropped == 1
    window.tool_options.cordon_on.setChecked(False)
    assert not window.act_cordon.isChecked() and window.compiler.build_doc()[1] is None

    tool.key_press(vp, QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
    assert ed.cordon() == (None, False) and ed.cordon_lines() is None
    assert not window.act_cordon_clear.isEnabled()


def test_cordon_from_selection_and_menu_toggle(window):
    ed = window.editor
    s = solids_from_faces(ed.doc, primitives.block((0, 0, 0), (128, 128, 64)))[0]
    ed.run(AddObjects([s]))
    ed.set_selection([])
    window.act_cordon.trigger()  # ohne Bereich und Auswahl: Werkzeug zum Ziehen
    assert ed.tool.name == "cordon" and ed.cordon()[0] is None and not window.act_cordon.isChecked()
    ed.set_selection([s.id])
    window.act_cordon_selection.trigger()
    box, on = ed.cordon()
    assert on and box.mins == (-64, -64, -64) and box.maxs == (192, 192, 128)
    window.act_cordon.trigger()
    assert ed.cordon()[1] is False
    window.act_cordon.trigger()
    assert ed.cordon()[1] is True
