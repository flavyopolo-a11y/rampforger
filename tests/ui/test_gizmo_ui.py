"""3D-Achsen-Pfeile: Auswahl in der 3D-Ansicht entlang X, Y oder Z ziehen."""
from PySide6.QtCore import QEvent, QPointF, Qt

from .test_main_window import create_block, drag, send_mouse


def _setup(window, qtbot):
    create_block(window, qtbot)  # Block 0..128 × 0..64 × 0..64, ausgewählt
    window.editor.set_tool("select")
    vp = next(v for v in window.grid_view.viewports() if v.is_3d)
    vp.resize(800, 600)
    # Schräg von vorne oben auf den Block schauen
    vp.cam3d.position = vp.cam3d.position * 0 + (600.0, -700.0, 500.0)
    vp.cam3d.look_at_point(__import__("numpy").array([64.0, 32.0, 32.0]))
    return vp, window.editor.tool


def _bbox(window):
    return window.editor.selection_bbox()


def test_gizmo_has_three_arrows(window, qtbot):
    vp, tool = _setup(window, qtbot)
    center, tips = tool.gizmo(vp)
    assert all(t is not None for t in tips)
    # Z zeigt auf dem Bildschirm nach oben
    assert tips[2].y() < center.y()


def test_drag_along_each_axis_moves_only_that_axis(window, qtbot):
    vp, tool = _setup(window, qtbot)
    for axis in range(3):
        before = _bbox(window)
        center, tips = tool.gizmo(vp)
        tip = tips[axis]
        grab = QPointF(center.x() + (tip.x() - center.x()) * 0.7, center.y() + (tip.y() - center.y()) * 0.7)
        assert tool._hit_axis(vp, grab) == axis
        end = QPointF(grab.x() + (tip.x() - center.x()) * 1.5, grab.y() + (tip.y() - center.y()) * 1.5)
        drag(vp, grab, end)
        after = _bbox(window)
        moved = [after.mins[i] - before.mins[i] for i in range(3)]
        assert moved[axis] > 0, (axis, moved)
        assert moved[axis] % window.editor.grid == 0
        assert all(moved[i] == 0 for i in range(3) if i != axis), (axis, moved)
        assert window.editor.selection  # Auswahl bleibt


def test_axis_drag_is_one_undo_step(window, qtbot):
    vp, tool = _setup(window, qtbot)
    before = _bbox(window)
    center, tips = tool.gizmo(vp)
    tip = tips[0]
    grab = QPointF((center.x() + tip.x()) / 2, (center.y() + tip.y()) / 2)
    drag(vp, grab, QPointF(grab.x() + (tip.x() - center.x()), grab.y() + (tip.y() - center.y())), steps=8)
    assert _bbox(window).mins != before.mins
    window.editor.undo()
    assert _bbox(window).mins == before.mins


def test_click_away_from_arrows_still_picks(window, qtbot):
    vp, tool = _setup(window, qtbot)
    send_mouse(vp, QEvent.MouseButtonPress, QPointF(5, 5))
    send_mouse(vp, QEvent.MouseButtonRelease, QPointF(5, 5), buttons=Qt.NoButton)
    assert not window.editor.selection
