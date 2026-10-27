"""Seiten-Werkzeug: Textur in der 3D-Ansicht mit der Maus verschieben und skalieren."""
import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt

from rampenschmiede.core.blocks import block_info
from rampenschmiede.core.model import Entity, Solid

from .test_main_window import create_block, drag, send_mouse


def _view(window, eye, target):
    vp = next(v for v in window.grid_view.viewports() if v.is_3d)
    vp.resize(800, 600)
    vp.cam3d.position = np.array(eye, dtype=float)
    vp.cam3d.look_at_point(np.array(target, dtype=float))
    return vp


def _top_face(window):
    s = next(o for o in window.editor.doc.objects() if isinstance(o, Solid))
    i = max(range(len(s.faces)), key=lambda k: s.faces[k].plane.normal[2])
    return s.id, i


def test_drag_shifts_texture_of_brush_face(window, qtbot):
    create_block(window, qtbot, (0, 0), (256, 256))
    window.editor.set_tool("face")
    vp = _view(window, (128, -300, 600), (128, 128, 0))
    sid, i = _top_face(window)
    before = window.editor.doc.get(sid).faces[i]
    top_z = max(p[2] for p in window.editor.doc.get(sid).polygons()[i])
    a = vp.project((100, 100, top_z))
    b = vp.project((164, 100, top_z))  # 64 Units in +X
    drag(vp, a, b, steps=6)
    after = window.editor.doc.get(sid).faces[i]
    assert window.editor.tool.faces == [(sid, i)]
    shift_u = (before.uaxis.offset - after.uaxis.offset) % 512
    assert abs(shift_u - 64 / before.uaxis.scale % 512) < 1.0
    window.editor.undo()
    assert window.editor.doc.get(sid).faces[i].uaxis.offset == before.uaxis.offset


def test_alt_drag_scales_and_alt_click_picks(window, qtbot):
    create_block(window, qtbot, (0, 0), (256, 256))
    window.editor.set_tool("face")
    vp = _view(window, (128, -300, 600), (128, 128, 0))
    sid, i = _top_face(window)
    before = window.editor.doc.get(sid).faces[i].uaxis.scale
    top_z = max(p[2] for p in window.editor.doc.get(sid).polygons()[i])
    a = vp.project((128, 128, top_z))
    drag(vp, a, QPointF(a.x(), a.y() - 150), mods=Qt.AltModifier)
    assert window.editor.doc.get(sid).faces[i].uaxis.scale == __import__("pytest").approx(before * 2, rel=0.02)
    window.editor.set_current_material("TOOLS/TOOLSSKIP")
    send_mouse(vp, QEvent.MouseButtonPress, a, mods=Qt.AltModifier)
    send_mouse(vp, QEvent.MouseButtonRelease, a, buttons=Qt.NoButton, mods=Qt.AltModifier)
    assert window.editor.current_material == window.editor.doc.get(sid).faces[i].material


def test_drag_on_ramp_moves_whole_ramp_texture(window, qtbot):
    root = window.library.insert("gerade", (0.0, 0.0, 0.0))
    window.editor.set_tool("face")
    # Rampe läuft entlang +X, ein Hang zeigt nach -Y: von dort draufschauen
    vp = _view(window, (512, -900, 500), (512, -150, 100))
    origin, direction = vp.ray(QPointF(400, 300))
    ref = window.editor.tool.pick(origin, direction)
    assert ref is not None
    p0 = QPointF(400, 300)
    drag(vp, p0, QPointF(480, 300), steps=6)
    info = block_info(window.editor.doc.get(root))
    assert info["values"]["textur_laengs"] != 0
    drag(vp, p0, QPointF(400, 200), mods=Qt.AltModifier)
    info = block_info(window.editor.doc.get(root))
    assert info["values"]["textur_groesse"] > 100
    assert isinstance(window.editor.doc.get(root), Entity)
