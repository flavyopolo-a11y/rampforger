"""Rauchtests der Oberfläche: echte Maus- und Tastaturereignisse auf die Ansichten."""
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication


def send_mouse(widget, kind, pos, button=Qt.LeftButton, buttons=Qt.LeftButton, mods=Qt.NoModifier):
    p = QPointF(pos)
    ev = QMouseEvent(kind, p, QPointF(widget.mapToGlobal(p.toPoint())), button, buttons, mods)
    QApplication.sendEvent(widget, ev)


def drag(widget, start, end, mods=Qt.NoModifier, steps=5):
    send_mouse(widget, QEvent.MouseButtonPress, start, mods=mods)
    for i in range(1, steps + 1):
        x = start.x() + (end.x() - start.x()) * i / steps
        y = start.y() + (end.y() - start.y()) * i / steps
        send_mouse(widget, QEvent.MouseMove, QPointF(x, y), Qt.NoButton, Qt.LeftButton, mods)
    send_mouse(widget, QEvent.MouseButtonRelease, end, buttons=Qt.NoButton, mods=mods)


def top_view(window):
    vp = next(v for v in window.grid_view.viewports() if v.view == "top")
    vp.cam2d.center_h = vp.cam2d.center_v = 0
    vp.cam2d.zoom = 1.0
    return vp


def screen(vp, h, v):
    return vp.to_screen(h, v)


def create_block(window, qtbot, mins=(0, 0), maxs=(128, 64)):
    vp = top_view(window)
    window.editor.set_tool("shape")
    drag(vp, screen(vp, *mins), screen(vp, *maxs))
    qtbot.keyClick(vp, Qt.Key_Return)
    return vp


def test_window_has_four_views(window):
    views = [vp.view for vp in window.grid_view.viewports()]
    assert views == ["3d", "top", "front", "side"]


def test_shape_tool_creates_block_and_undo(window, qtbot):
    create_block(window, qtbot)
    solids = list(window.editor.doc.solids())
    assert len(solids) == 1
    bb = solids[0].bbox()
    assert bb.mins[:2] == (0, 0) and bb.maxs[:2] == (128, 64)
    assert bb.size[2] == 64  # Tiefe vom Standardrahmen
    window.act_undo.trigger()
    assert len(window.editor.doc) == 0
    window.act_redo.trigger()
    assert len(window.editor.doc) == 1


def test_select_and_move_snaps_to_grid(window, qtbot):
    vp = create_block(window, qtbot)
    window.editor.set_tool("select")
    sid = next(window.editor.doc.solids()).id
    window.editor.set_selection(())
    drag(vp, screen(vp, 64, 32), screen(vp, 64 + 37, 32 - 70))
    obj = window.editor.doc.get(sid)
    assert window.editor.selection == {sid}
    assert obj.bbox().mins[:2] == (32, -64)  # 37 -> 32, -70 -> -64 bei Raster 16
    assert len(window.editor.stack) == 2  # Erstellen + ein Verschiebe-Schritt


def test_shift_drag_clones(window, qtbot):
    vp = create_block(window, qtbot)
    window.editor.set_tool("select")
    drag(vp, screen(vp, 64, 32), screen(vp, 64 + 256, 32), mods=Qt.ShiftModifier)
    solids = sorted(window.editor.doc.solids(), key=lambda s: s.id)
    assert len(solids) == 2
    assert solids[0].bbox().mins[0] == 0
    assert solids[1].bbox().mins[0] == 256


def test_arrow_keys_nudge(window, qtbot):
    vp = create_block(window, qtbot)
    window.editor.set_tool("select")
    vp.setFocus()
    qtbot.keyClick(vp, Qt.Key_Right)
    qtbot.keyClick(vp, Qt.Key_Up)
    s = next(window.editor.doc.solids())
    assert s.bbox().mins[:2] == (16, 16)


def test_marquee_selects(window, qtbot):
    vp = create_block(window, qtbot)
    window.editor.set_tool("select")
    window.editor.set_selection(())
    drag(vp, screen(vp, -32, -32), screen(vp, 200, 100))
    assert len(window.editor.selection) == 1


def test_scale_handle(window, qtbot):
    vp = create_block(window, qtbot)
    window.editor.set_tool("select")
    tool = window.editor.tool
    rect = tool._sel_rect(vp)
    handle = dict(tool._handle_points(rect))[(1, 0)]
    drag(vp, handle, handle + QPointF(64, 0))
    s = next(window.editor.doc.solids())
    assert s.bbox().size[0] == 192


def test_entity_tool_places_light(window, qtbot):
    vp = top_view(window)
    window.editor.set_tool("entity")
    window.editor.tools["entity"].classname = "light"
    send_mouse(vp, QEvent.MouseButtonPress, screen(vp, 100, 50))
    send_mouse(vp, QEvent.MouseButtonRelease, screen(vp, 100, 50), buttons=Qt.NoButton)
    ents = list(window.editor.doc.entities())
    assert len(ents) == 1 and ents[0].classname == "light"
    assert ents[0].origin[:2] == (96, 48)


def test_copy_paste_and_delete(window, qtbot):
    create_block(window, qtbot)
    window.act_copy.trigger()
    window.act_paste.trigger()
    assert len(list(window.editor.doc.solids())) == 2
    window.act_delete.trigger()
    assert len(list(window.editor.doc.solids())) == 1


def test_transform_dialog_rotate(window, qtbot):
    from rampenschmiede.ui.dialogs.transform_dialog import TransformDialog

    create_block(window, qtbot)
    dlg = TransformDialog(window.editor, window)
    dlg.tabs.setCurrentIndex(1)
    dlg.rot_angle.setValue(90)
    assert dlg.apply()
    s = next(window.editor.doc.solids())
    assert s.bbox().size[:2] == (64, 128)


def test_save_and_open(window, qtbot, tmp_path):
    create_block(window, qtbot)
    path = tmp_path / "raum.rsmap"
    assert window._save_to(path)
    assert window.editor.stack.is_clean()
    window.editor.set_document(type(window.editor.doc)(), None)
    assert window.open_path(path)
    assert len(list(window.editor.doc.solids())) == 1
    assert "raum.rsmap" in window.windowTitle()


def test_hide_and_unhide(window, qtbot):
    create_block(window, qtbot)
    window.act_hide.trigger()
    s = next(window.editor.doc.solids())
    assert s.editor.hidden and not window.editor.selection
    window.act_unhide.trigger()
    assert not next(window.editor.doc.solids()).editor.hidden


def test_rendering_produces_pixels(window, qtbot):
    """Nur mit OpenGL 3.3: Die 3D-Ansicht zeichnet den Block."""
    import pytest

    create_block(window, qtbot)
    vp3d = window.grid_view.viewports()[0]
    if vp3d.renderer is None:
        pytest.skip("kein OpenGL 3.3 verfügbar")
    vp3d.center_on((64, 32, 32), 128)
    img = vp3d.grabFramebuffer()
    center = img.pixelColor(img.width() // 2, img.height() // 2)
    assert center.red() > 60  # grauer Block statt dunklem Hintergrund
