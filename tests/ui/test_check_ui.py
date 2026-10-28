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
