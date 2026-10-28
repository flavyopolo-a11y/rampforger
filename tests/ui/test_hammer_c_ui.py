"""Paket C im Fenster: Namen-Pipette, Pfad-Werkzeug."""
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent

from rampenschmiede.core.commands import AddObjects
from rampenschmiede.core.model import Entity, Output
from rampenschmiede.core.tracks import path_segments


def _add(window, *ents):
    window.editor.run(AddObjects(list(ents)))


def _top(window):
    return next(vp for vp in window.grid_view.viewports() if not vp.is_3d and vp.axes()[:2] == (0, 1))


def _click(vp, x, y):
    pos = vp.to_screen(x, y)
    vp.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, pos, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    vp.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, pos, pos, Qt.LeftButton, Qt.NoButton, Qt.NoModifier))


def _center(vp, x, y):
    vp.cam2d.center_h, vp.cam2d.center_v = x, y
    vp.cam2d.zoom = 1.0


def test_pipette_names_target_and_fills_field(window, qtbot):
    ed = window.editor
    tele = Entity(id=ed.doc.new_id(), classname="trigger_teleport", keyvalues=(("origin", "0 0 0"),))
    dest = Entity(id=ed.doc.new_id(), classname="info_teleport_destination", keyvalues=(("origin", "256 0 0"),))
    _add(window, tele, dest)
    ed.set_selection([tele.id])
    panel = window.selection_panel.entity_panel
    assert "target" in panel.target_pipettes
    panel.target_pipettes["target"].click()
    assert ed.picking
    vp = _top(window)
    _center(vp, 128, 0)
    _click(vp, 256, 0)
    assert not ed.picking and ed.selection == {tele.id}  # Auswahl bleibt
    named = ed.doc.get(dest.id).get("targetname")
    assert named == "teleport_destination_1"
    assert ed.doc.get(tele.id).get("target") == named
    ed.undo()
    assert ed.doc.get(dest.id).get("targetname") == "" and ed.doc.get(tele.id).get("target") == ""


def test_pipette_for_output_target_and_escape(window):
    ed = window.editor
    button = Entity(id=ed.doc.new_id(), classname="func_button", keyvalues=(("origin", "0 0 0"),),
                    outputs=(Output("OnPressed", "", "Toggle"),))
    door = Entity(id=ed.doc.new_id(), classname="func_door", keyvalues=(("origin", "0 512 0"), ("targetname", "tuer")))
    _add(window, button, door)
    ed.set_selection([button.id])
    panel = window.selection_panel.entity_panel
    panel.outputs.selectRow(0)
    panel.out_pipette.click()
    vp = _top(window)
    vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert not ed.picking
    panel.out_pipette.click()
    _center(vp, 0, 256)
    _click(vp, 0, 512)
    assert ed.doc.get(button.id).outputs[0].target == "tuer"


def test_path_tool_builds_linked_loop(window):
    ed = window.editor
    ed.set_tool("path")
    vp = _top(window)
    _center(vp, 0, 0)
    for x, y in ((0, 0), (256, 0), (256, 256)):
        _click(vp, x, y)
    _click(vp, 0, 0)  # erster Punkt: Rundkurs
    tracks = sorted((e for e in ed.doc.entities() if e.classname == "path_track"), key=lambda e: e.get("targetname"))
    assert [e.get("targetname") for e in tracks] == ["pfad_1", "pfad_2", "pfad_3"]
    assert [e.get("target") for e in tracks] == ["pfad_2", "pfad_3", "pfad_1"]
    assert tracks[0].origin == (0.0, 0.0, 64.0)
    assert len(path_segments(ed.doc)) == 3 and ed.io_lines() is not None
    # Zweiter Pfad bekommt freie Namen
    for x in (0, 512):
        _click(vp, x, 512)
    vp.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
    names = {e.get("targetname") for e in ed.doc.entities() if e.classname == "path_track"}
    assert {"pfad2_1", "pfad2_2"} <= names


def test_entity_report_filters_selects_and_deletes(window):
    ed = window.editor
    a = Entity(id=ed.doc.new_id(), classname="light", keyvalues=(("origin", "0 0 64"), ("targetname", "lampe")))
    b = Entity(id=ed.doc.new_id(), classname="light", keyvalues=(("origin", "128 0 64"),))
    c = Entity(id=ed.doc.new_id(), classname="info_player_counterterrorist", keyvalues=(("origin", "0 0 0"),))
    _add(window, a, b, c)
    rep = window.show_entity_report()
    assert rep.table.rowCount() == 3
    rep.search.setText("lampe")
    assert rep.table.rowCount() == 1
    rep.search.setText("")
    rep.classes.setCurrentIndex(rep.classes.findData("light"))
    assert rep.table.rowCount() == 2
    rep.select_filtered()
    assert ed.selection == {a.id, b.id}
    rep.table.selectRow(0)
    assert rep.delete_marked() == 1
    assert rep.table.rowCount() == 1  # Liste folgt dem Dokument
    ed.undo()
    assert rep.table.rowCount() == 2
    rep.close()


def test_visgroup_panel_hides_and_shows(window):
    from rampenschmiede.core.commands import solids_from_faces
    from rampenschmiede.core.geometry import primitives

    ed = window.editor
    solids = solids_from_faces(ed.doc, [fs for i in range(2) for fs in primitives.block((i * 128, 0, 0), (i * 128 + 64, 64, 64))])
    ed.run(AddObjects(solids))
    panel = window.scene.visgroups
    ed.set_selection([solids[0].id])
    gid = panel.create_from_selection("Dach")
    assert panel.list.count() == 1 and "Dach" in panel.list.item(0).text()
    panel.list.item(0).setCheckState(Qt.Unchecked)
    assert ed.doc.get(solids[0].id).editor.hidden and not ed.selection
    panel.list.item(0).setCheckState(Qt.Checked)
    assert not ed.doc.get(solids[0].id).editor.hidden
    ed.set_selection([solids[1].id])
    panel.list.setCurrentRow(0)
    panel.add_selection()
    panel.select_members(gid)
    assert ed.selection == {s.id for s in solids}
    panel.delete_current()
    assert panel.list.count() == 0


PRT = """PRT1
3
2
4 0 1 (0 0 0 ) (0 128 0 ) (0 128 128 ) (0 0 128 )
3 1 2 (64 0 0) (64 64 0) (64 0 64)
"""


def test_portal_file_drawn_and_cleared(window, tmp_path):
    from rampenschmiede.core.compile import parse_portalfile

    assert len(parse_portalfile(PRT)) == 2
    path = tmp_path / "karte.prt"
    path.write_text(PRT)
    assert window.open_portalfile(str(path)) == 2
    assert window.editor.portal_lines.shape == ((4 + 3) * 2, 6)
    window.act_clear_portals.trigger()
    assert window.editor.portal_lines is None


def _wav(path):
    import struct

    data = b"\x00\x00" * 800
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16)
                     + b"data" + struct.pack("<I", len(data)) + data)


def test_sound_browser_lists_plays_and_chooses(window, tmp_path, monkeypatch):
    from rampenschmiede.core.materials import MaterialLibrary
    from rampenschmiede.ui.dialogs.sound_browser import SoundBrowser

    root = tmp_path / "spiel"
    _wav(root / "sound" / "ambient" / "wind1.wav")
    _wav(root / "sound" / "buttons" / "button9.wav")
    ed = window.editor
    ed.set_material_library(MaterialLibrary.for_game(None, [root]))
    assert ed.sounds().names() == ["ambient/wind1.wav", "buttons/button9.wav"]
    dlg = SoundBrowser(ed.sounds(), ")ambient/wind1.wav")
    assert dlg.chosen() == "ambient/wind1.wav"
    dlg.search.setText("button")
    assert dlg.proxy.rowCount() == 1
    dlg.search.setText("")
    dlg.folder.setCurrentIndex(dlg.folder.findData("ambient"))
    assert dlg.proxy.rowCount() == 1
    dlg.play()
    assert dlg.last_played == "ambient/wind1.wav"
    dlg.close()

    amb = Entity(id=ed.doc.new_id(), classname="ambient_generic", keyvalues=(("origin", "0 0 0"),))
    _add(window, amb)
    ed.set_selection([amb.id])
    panel = window.selection_panel.entity_panel
    assert "message" in panel.sound_buttons

    class Picker(SoundBrowser):
        def exec(self):
            self.select("buttons/button9.wav")
            return SoundBrowser.Accepted

    assert panel.choose_sound("message", Picker)
    assert ed.doc.get(amb.id).get("message") == "buttons/button9.wav"


def test_instances_save_insert_show_and_collapse(window, tmp_path):
    from rampenschmiede.core.commands import solids_from_faces
    from rampenschmiede.core.geometry import primitives
    from rampenschmiede.core.instances import INSTANCE

    ed = window.editor
    window._save_to(tmp_path / "karte.rsmap")
    solids = solids_from_faces(ed.doc, primitives.block((256, 256, 0), (384, 320, 64)))
    lamp = Entity(id=ed.doc.new_id(), classname="light", keyvalues=(("origin", "320 288 32"), ("targetname", "lampe")))
    ed.run(AddObjects([*solids, lamp]))
    ed.set_selection([solids[0].id, lamp.id])
    inst_id = window.save_as_instance(str(tmp_path / "raum.vmf"))
    inst = ed.doc.get(inst_id)
    assert inst.classname == INSTANCE and inst.get("file") == "raum.vmf" and inst.get("origin") == "320 288 0"
    assert sum(1 for _ in ed.doc.solids()) == 0  # durch die Instanz ersetzt
    assert ed.selection_bbox().maxs == (384.0, 320.0, 64.0)  # Auswahl so groß wie der Inhalt
    assert len(ed.scene.arrays().faces) >= 36  # Inhalt wird gezeichnet
    ed.undo()
    assert sum(1 for _ in ed.doc.solids()) == 1
    ed.redo()

    second = window.insert_instance(str(tmp_path / "raum.vmf"))
    assert ed.doc.get(second).get("file") == "raum.vmf"
    doc, _ = window.compiler.build_doc()
    assert not any(e.classname == INSTANCE for e in doc.entities())
    assert sum(1 for _ in doc.solids()) == 2
    names = sorted(e.get("targetname") for e in doc.entities() if e.classname == "light")
    assert names == ["instanz_1-lampe", "raum-lampe"]
    assert not window.compiler.instance_problems
