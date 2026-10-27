"""Entity-Panel: FGD-Felder, Flags, Farben, Ausgänge; Entity-Werkzeug mit Suche."""
from rampenschmiede.core.commands import AddObjects
from rampenschmiede.core.model import Entity, Output


def _add(window, classname, kvs=(), outputs=()):
    doc = window.editor.doc
    ent = Entity(id=doc.new_id(), classname=classname, keyvalues=(("origin", "0 0 0"), *kvs), outputs=outputs)
    window.editor.run(AddObjects([ent]))
    window.editor.set_selection([ent.id])
    return ent.id


def _panel(window):
    return window.selection_panel.entity_panel


def test_light_shows_typed_fields_and_changes_value(window):
    eid = _add(window, "light", (("_light", "255 255 255 200"),))
    panel = _panel(window)
    assert panel.classname.currentText() == "light"
    panel.set_value("_light", "255 0 0 300")
    assert window.editor.doc.get(eid).get("_light") == "255 0 0 300"
    window.editor.undo()
    assert window.editor.doc.get(eid).get("_light") == "255 255 255 200"


def test_flags_toggle_bits_and_keep_case_of_existing_key(window):
    eid = _add(window, "trigger_teleport", (("SpawnFlags", "1"),))
    panel = _panel(window)
    panel._toggle_flag("spawnflags", 8, True)
    ent = window.editor.doc.get(eid)
    assert ent.get("SpawnFlags") == "9" and not ent.get("spawnflags")
    # Liste zeigt den Stand
    rows = {panel.flag_list.item(i).data(256): panel.flag_list.item(i).checkState().value
            for i in range(panel.flag_list.count())}
    assert rows[1] and rows[8] and not rows[2]


def test_unknown_keys_stay_editable(window):
    eid = _add(window, "light", (("mein_key", "42"),))
    panel = _panel(window)
    panel.set_value("mein_key", "43")
    assert window.editor.doc.get(eid).get("mein_key") == "43"


def test_outputs_add_edit_delete(window):
    _add(window, "func_door", (("targetname", "tuer"),))
    eid = _add(window, "logic_relay", (("targetname", "relais"),))
    panel = _panel(window)
    panel.add_output()
    ent = window.editor.doc.get(eid)
    assert len(ent.outputs) == 1 and ent.outputs[0].output == "OnSpawn"
    panel.outputs.selectRow(0)
    panel.out_name.setEditText("OnTrigger")
    panel.out_target.setEditText("tuer")
    panel._fill_inputs()
    assert panel.out_input.findText("Open") >= 0  # Eingänge der Zielklasse
    panel.out_input.setEditText("Open")
    panel.out_delay.setValue(1.5)
    panel.out_once.setChecked(True)
    panel._save_output_row()
    out = window.editor.doc.get(eid).outputs[0]
    assert out == Output("OnTrigger", "tuer", "Open", "", 1.5, 1)
    panel.outputs.selectRow(0)
    panel.copy_output()
    assert len(window.editor.doc.get(eid).outputs) == 2
    panel.outputs.selectRow(0)
    panel.delete_output()
    assert len(window.editor.doc.get(eid).outputs) == 1


def test_incoming_tab_lists_sources_and_jumps(window):
    door = _add(window, "func_door", (("targetname", "tuer"),))
    relay = _add(window, "logic_relay", (), (Output("OnTrigger", "tuer", "Open"),))
    window.editor.set_selection([door])
    panel = _panel(window)
    assert panel.inputs.rowCount() == 1 and panel.inputs.item(0, 2).text() == "Open"
    assert window.editor.io_lines() is not None
    panel._jump_to_source(0, 0)
    assert window.editor.selection == {relay}


def test_changing_class_adds_its_defaults(window):
    eid = _add(window, "info_target", (("targetname", "x"),))
    panel = _panel(window)
    panel.classname.setEditText("light")
    panel._class_edited()
    ent = window.editor.doc.get(eid)
    assert ent.classname == "light" and ent.get("_light") and ent.get("targetname") == "x"


def test_entity_tool_places_any_fgd_class(window, qtbot):
    window.editor.set_tool("entity")
    opts = window.tool_options
    opts.entity_search.setEditText("logic_relay")
    opts.entity_search.lineEdit().editingFinished.emit()
    tool = window.editor.tools["entity"]
    assert tool.classname == "logic_relay"
    tool._place((0, 0, 0))
    ent = next(e for e in window.editor.doc.entities() if e.classname == "logic_relay")
    assert ent.get("startdisabled") == "0"
    opts.entity_quick.setCurrentIndex(opts.entity_quick.findData("light"))
    assert tool.classname == "light"


def test_profile_fgd_adds_classes_and_broken_fgd_falls_back(window, tmp_path):
    good = tmp_path / "momentum.fgd"
    good.write_text('@include "basis.fgd"\n@PointClass base(Basis) = momentum_test : "Test" []\n', encoding="utf-8")
    (tmp_path / "basis.fgd").write_text('@BaseClass = Basis\n[\n\twert(integer) : "Wert" : 3\n]\n',
                                        encoding="utf-8")
    window.editor.set_entity_fgds([str(good)])
    info = window.editor.entity_catalog.get("momentum_test")
    assert info is not None and info.key("wert").default == "3"
    bad = tmp_path / "kaputt.fgd"
    bad.write_text("@PointClass = [[[ kaputt", encoding="utf-8")
    window.editor.set_entity_fgds([str(bad)])
    assert window.editor.entity_catalog.get("light") is not None
