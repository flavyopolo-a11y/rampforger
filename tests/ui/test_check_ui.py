"""Probleme suchen, Suchen und Ersetzen, Gehe zu ID und Messen im Fenster."""
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from rampenschmiede.core.commands import AddObjects, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.model import Entity
from rampenschmiede.ui.tools.measure_tool import describe


def _mouse(kind, pos: QPointF, buttons=Qt.LeftButton):
    button = Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton
    return QMouseEvent(kind, pos, pos, button, buttons, Qt.NoModifier)


def test_problems_dialog_jumps_and_fixes(window):
    ed = window.editor
    a = solids_from_faces(ed.doc, primitives.block((0, 0, 0), (64, 64, 64)))[0]
    dup = a.replace(id=ed.doc.new_id())
    ed.run(AddObjects([a, dup]))
    dlg = window.show_problems()
    texts = [dlg.tree.topLevelItem(i).text(2) for i in range(dlg.tree.topLevelItemCount())]
    assert any("Kein Spawn" in t for t in texts) and any("doppelte" in t for t in texts)
    row = next(i for i, t in enumerate(texts) if "doppelte" in t)
    dlg.tree.setCurrentItem(dlg.tree.topLevelItem(row))
    assert ed.selection == {dup.id}
    assert dlg.btn_fix.isEnabled()
    assert dlg.fix_current()
    assert dup.id not in ed.doc
    texts = [dlg.tree.topLevelItem(i).text(2) for i in range(dlg.tree.topLevelItemCount())]
    assert not any("doppelte" in t for t in texts)
    ed.undo()
    assert dup.id in ed.doc
    dlg.close()


def test_find_dialog_selects_and_replaces(window):
    ed = window.editor
    e = Entity(id=ed.doc.new_id(), classname="info_teleport_destination", keyvalues=(("targetname", "ziel_a"),))
    s = solids_from_faces(ed.doc, primitives.block((0, 0, 0), (64, 64, 64), "CONCRETE/A"))[0]
    ed.run(AddObjects([e, s]))
    dlg = window.show_find()
    dlg.ent_text.setText("ziel_a")
    assert dlg.select_entities() == [e.id] and ed.selection == {e.id}
    dlg.ent_new.setText("ziel_b")
    assert dlg.replace_entities()
    assert ed.doc.get(e.id).get("targetname") == "ziel_b"
    dlg.tabs.setCurrentIndex(1)
    dlg.tex_find.setCurrentText("concrete/a")
    assert dlg.select_textures() == [s.id]
    dlg.tex_new.setCurrentText("brick/b")
    assert dlg.replace_textures()
    assert ed.doc.get(s.id).faces[0].material == "BRICK/B"
    assert window.goto_dialog("ziel_b") and ed.selection == {e.id}
    assert not window.goto_dialog("gibtsnicht")
    dlg.close()


def test_measure_tool_in_top_view(window):
    ed = window.editor
    window.tool_actions["measure"].trigger()
    tool = ed.tool
    assert tool.name == "measure"
    vp = next(v for v in window.grid_view.viewports() if not v.is_3d and v.axes()[:2] == (0, 1))
    ed.set_grid(16)
    a, b = vp.to_screen(0, 0), vp.to_screen(256, 192)
    tool.press_2d(vp, _mouse(QEvent.MouseButtonPress, a))
    tool.move_2d(vp, _mouse(QEvent.MouseMove, b))
    tool.release_2d(vp, _mouse(QEvent.MouseButtonRelease, b, Qt.NoButton))
    assert tool.text().startswith("320 Units")
    assert tool.lines_2d(vp) is not None


def test_describe_slope():
    assert describe((0, 0, 0), (100, 0, 100)).endswith("Steigung 45°")
    assert "Steigung" not in describe((0, 0, 0), (100, 0, 0))


def test_wall_tool_draws_a_closed_room_in_top_view(window):
    ed = window.editor
    window.tool_actions["wall"].trigger()
    tool = ed.tool
    assert tool.name == "wall"
    assert window.tool_options.currentWidget() is window.tool_options._pages["wall"]
    vp = next(v for v in window.grid_view.viewports() if not v.is_3d and v.axes()[:2] == (0, 1))
    vp.cam2d.zoom, vp.cam2d.center_h, vp.cam2d.center_v = 0.5, 256, 256
    ed.set_grid(64)
    steps = len(ed.stack._undo)
    for x, y in ((0, 0), (512, 0), (512, 512), (0, 512)):
        tool.press_2d(vp, _mouse(QEvent.MouseButtonPress, vp.to_screen(x, y)))
    assert tool.lines_2d(vp) is not None
    tool.press_2d(vp, _mouse(QEvent.MouseButtonPress, vp.to_screen(0, 0)))  # erster Punkt: schließen
    assert len(ed.selection) == 4 and len(ed.stack._undo) == steps + 1
    groups = {ed.doc.get(i).editor.group_id for i in ed.selection}
    assert len(groups) == 1 and None not in groups


def test_start_zone_follows_dragged_start_block(window):
    from PySide6.QtCore import QSettings

    QSettings("Rampenschmiede", "Rampenschmiede").setValue("new_map_starter", "true")
    window.act_starter.setChecked(True)
    window.file_new()
    ed = window.editor
    zone = next(e for e in ed.doc.entities() if e.get("targetname") == "mod_zone_start")
    block_id = zone.extra["sitzt_auf"]["id"]
    before = ed.doc.bbox([zone.id])
    ed.set_selection([block_id])
    ed.move_selection((128, 0, 64))
    after = ed.doc.bbox([zone.id])
    assert after.mins[0] == before.mins[0] + 128 and after.mins[2] == before.mins[2] + 64
    ed.undo()
    assert ed.doc.bbox([zone.id]) == before


def test_drag_object_directly_in_3d_slides_it_on_the_grid(window):
    ed = window.editor
    s = solids_from_faces(ed.doc, primitives.block((0, 0, 0), (128, 128, 64)))[0]
    ed.run(AddObjects([s]))
    ed.set_selection(set())
    window.tool_actions["select"].trigger()
    tool = ed.tool
    vp = next(v for v in window.grid_view.viewports() if v.is_3d)
    vp.center_on((64, 64, 32), 600)
    ed.set_grid(16)
    start = vp.project((40, 64, 64))  # auf der Oberseite, abseits der Pfeile
    end = vp.project((40 + 200, 64, 64))
    steps = len(ed.stack._undo)
    tool.press_3d(vp, _mouse(QEvent.MouseButtonPress, start))
    assert ed.selection == {s.id}
    for t in (0.3, 0.6, 1.0):
        tool.move_3d(vp, _mouse(QEvent.MouseMove, start + (end - start) * t))
    tool.release_3d(vp, _mouse(QEvent.MouseButtonRelease, end, Qt.NoButton))
    bb = ed.doc.get(s.id).bbox()
    assert bb.mins[0] in (192, 208) and bb.mins[1] == 0 and bb.mins[2] == 0
    assert len(ed.stack._undo) == steps + 1
