"""Ordnen im Fenster: Gruppen per Klick, Strg+T, Zur Welt, Mehrfach kopieren, Strg+B, Ecken-Werkzeug."""
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from rampenschmiede.core.commands import AddObjects, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.geometry.vertex_edit import vertices
from rampenschmiede.core.model import Entity


def _mouse(kind, pos: QPointF, buttons=Qt.LeftButton, mods=Qt.NoModifier):
    button = Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton
    return QMouseEvent(kind, pos, pos, button, buttons, mods)


def _front_view(window):
    return next(vp for vp in window.grid_view.viewports() if not vp.is_3d and vp.axes()[:2] == (0, 2))


def _boxes(window, n=2, z=0):
    ed = window.editor
    solids = solids_from_faces(ed.doc, [fs for i in range(n)
                                        for fs in primitives.block((i * 128, 0, z), (i * 128 + 64, 64, z + 64))])
    ed.run(AddObjects(solids))
    return solids


def test_group_selects_all_members_unless_ignored(window):
    ed = window.editor
    a, b, c = _boxes(window, 3)
    ed.set_selection([a.id, b.id])
    assert window.group_selection()
    ed.set_selection([a.id])
    assert ed.selection == {a.id, b.id}
    window.act_ignore_groups.trigger()
    ed.set_selection([a.id])
    assert ed.selection == {a.id}
    window.act_ignore_groups.trigger()
    ed.set_selection([b.id])
    assert window.ungroup_selection()
    ed.set_selection([a.id])
    assert ed.selection == {a.id}


def test_tie_to_entity_and_back(window):
    ed = window.editor
    a, b = _boxes(window)
    ed.set_selection([a.id, b.id])
    assert window.tie_to_entity("func_detail")
    (eid,) = ed.selection
    ent = ed.doc.get(eid)
    assert isinstance(ent, Entity) and ent.classname == "func_detail"
    assert window.move_to_world()
    assert eid not in ed.doc
    assert ed.selection == {a.id, b.id}


def test_multi_copy_and_snap(window):
    ed = window.editor
    (a,) = _boxes(window, 1, z=3)
    ed.set_selection([a.id])
    assert window.multi_copy({"count": 3, "offset": (0, 64, 32), "rotation": (0, 0, 0), "make_group": False})
    assert len(ed.selection) == 3
    ed.set_selection([a.id])
    ed.set_grid(16)
    assert window.snap_selection()
    assert ed.selection_bbox().mins[2] == 0
    assert not window.snap_selection()


def test_actions_are_in_edit_menu(window):
    texts = {a.text() for m in window.menuBar().actions() if m.menu() for a in m.menu().actions()}
    for name in ("&Gruppieren", "An &Entity binden …", "Zur &Welt", "&Mehrfach kopieren …", "Auswahl ans &Raster"):
        assert name in texts


def test_vertex_tool_drags_top_edge_in_front_view(window):
    ed = window.editor
    (a,) = _boxes(window, 1)
    ed.set_selection([a.id])
    window.tool_actions["vertex"].trigger()
    assert ed.tool.name == "vertex"
    assert window.tool_options.currentWidget() is window.tool_options._pages["vertex"]
    tool = ed.tool
    assert len(tool.handles()) > 0
    vp = _front_view(window)
    vp.cam2d.zoom, vp.cam2d.center_h, vp.cam2d.center_v = 2.0, 32, 32
    ed.set_grid(16)
    steps = len(ed.stack._undo)
    # Rahmen um die obere Kante (z = 64) in der Vorderansicht
    p0, p1 = vp.to_screen(-8, 56), vp.to_screen(72, 72)
    tool.press_2d(vp, _mouse(QEvent.MouseButtonPress, p0))
    tool.move_2d(vp, _mouse(QEvent.MouseMove, p1))
    tool.release_2d(vp, _mouse(QEvent.MouseButtonRelease, p1))
    assert tool.picked_count() == 4
    assert tool.nudge((0, 0, 32))
    verts = vertices(ed.doc.get(a.id))
    assert max(v[2] for v in verts) == 96
    assert len(ed.stack._undo) == steps + 1
    ed.stack.undo()
    assert max(v[2] for v in vertices(ed.doc.get(a.id))) == 64


def test_dialogs_offer_common_classes_and_values(qtbot):
    from rampenschmiede.ui.dialogs.organize_dialogs import MultiCopyDialog, TieEntityDialog

    tie = TieEntityDialog(["func_detail", "func_tracktrain", "worldspawn"])
    qtbot.addWidget(tie)
    items = [tie.classname.itemText(i) for i in range(tie.classname.count())]
    assert items[0] == "func_detail" and "func_tracktrain" in items and "worldspawn" not in items
    assert items.count("func_detail") == 1
    mc = MultiCopyDialog((128, 64, 32))
    qtbot.addWidget(mc)
    v = mc.values()
    assert v["count"] == 4 and v["offset"] == (128, 0, 0) and v["rotation"] == (0, 0, 0)
