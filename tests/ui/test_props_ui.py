"""Props im Fenster: Modell-Browser, Setzen per Ziehen und Knopf, Prop-Art, Modell tauschen."""
import pytest
from PySide6.QtWidgets import QDialog

from rampenschmiede.core.materials import MaterialLibrary
from rampenschmiede.core.model import object_bbox
from rampenschmiede.core.models.props import prop_problems
from rampenschmiede.ui.dialogs import model_dialog

from ..models.mdl_builder import write_cube_model, write_material


@pytest.fixture
def game(tmp_path):
    root = tmp_path / "spiel"
    write_material(root, "models/test/crate_top", (250, 0, 0))
    write_material(root, "models/test/crate_side", (0, 0, 250))
    write_cube_model(root, name="models/test/crate.mdl", static=True, physics=False)
    write_cube_model(root, name="models/test/barrel.mdl", static=False, physics=True, size=(16, 16, 48),
                     lo=(-8, -8, 0))
    write_cube_model(root, name="models/other/rock.mdl")
    return root


@pytest.fixture
def props_window(window, game, qtbot):
    window.editor.set_material_library(MaterialLibrary.for_game(None, [game]))
    browser = window.model_browser
    browser.wait_for_index()
    qtbot.waitUntil(lambda: len(browser._all) == 3)
    return window


def test_browser_lists_models_by_folder_and_search(props_window):
    b = props_window.model_browser
    folders = [b.folder.itemText(i) for i in range(b.folder.count())]
    assert folders == ["Alle Ordner", "In dieser Map", "other", "test"]
    assert b.model.rowCount() == 3
    b.search.setText("bar")
    assert b.model.names == ["models/test/barrel.mdl"]
    b.search.clear()
    b.folder.setCurrentIndex(folders.index("other"))
    assert b.model.names == ["models/other/rock.mdl"]


def test_place_picks_a_fitting_prop_class(props_window):
    ed = props_window.editor
    b = props_window.model_browser
    assert b.select_name("models/test/crate.mdl")
    assert "statisch" in b.info.text()
    crate = ed.doc.get(b.place_current())
    assert crate.classname == "prop_static" and ed.selection == {crate.id}
    # Hülle aus dem Modell statt des 16er-Kästchens
    bb = object_bbox(crate)
    assert [round(bb.maxs[i] - bb.mins[i]) for i in range(3)] == [32, 32, 32]
    ed.model_dropped.emit("models/test/barrel.mdl", (10.4, 20, 30))
    barrel = ed.doc.get(max(ed.selection))
    assert barrel.classname == "prop_dynamic" and barrel.get("origin").endswith(" 30")
    # „In dieser Map“ zeigt genau die gesetzten Modelle
    b.folder.setCurrentIndex(b.folder.findData("map"))
    assert b.model.names == ["models/test/barrel.mdl", "models/test/crate.mdl"]


def test_prop_type_buttons_warn_and_switch(props_window):
    ed = props_window.editor
    b = props_window.model_browser
    b.select_name("models/test/barrel.mdl")
    ent_id = b.place_current()
    panel = props_window.selection_panel.entity_panel
    assert panel.prop_buttons["prop_dynamic"].isChecked()
    assert "⚠" in panel.prop_buttons["prop_static"].text()
    panel.set_prop_class("prop_static")
    assert ed.doc.get(ent_id).classname == "prop_static"
    assert panel.prop_warning.isVisible() or not panel.prop_warning.isHidden()
    assert "vbsp" in panel.prop_warning.text()
    problems = prop_problems(ed.doc, ed.models)
    assert len(problems) == 1 and "vbsp" in problems[0][1]
    ed.stack.undo()
    assert ed.doc.get(ent_id).classname == "prop_dynamic"


def test_swap_model_of_selected_props(props_window):
    ed = props_window.editor
    b = props_window.model_browser
    b.select_name("models/test/crate.mdl")
    ent_id = b.place_current()
    b.select_name("models/test/barrel.mdl")
    assert b.swap_btn.isEnabled() and "(1)" in b.swap_btn.text()
    assert b.apply_to_selection() == 1
    ent = ed.doc.get(ent_id)
    # Das neue Modell ist nicht statisch: die Klasse wird gleich mit angepasst
    assert ent.get("model") == "models/test/barrel.mdl" and ent.classname == "prop_dynamic"


def test_model_field_and_skin_in_entity_panel(props_window, monkeypatch):
    ed = props_window.editor
    b = props_window.model_browser
    b.select_name("models/test/crate.mdl")
    ent_id = b.place_current()
    panel = props_window.selection_panel.entity_panel
    monkeypatch.setattr(model_dialog.ModelDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(model_dialog.ModelDialog, "chosen", lambda self: "models/other/rock.mdl")
    assert panel.choose_model()
    assert ed.doc.get(ent_id).get("model") == "models/other/rock.mdl"
    assert panel.model_edit.text() == "models/other/rock.mdl"


def test_model_dialog_filters_and_picks(props_window, qtbot):
    dlg = model_dialog.ModelDialog(props_window.editor.models, "models/test/crate.mdl")
    qtbot.addWidget(dlg)
    assert dlg.model.rowCount() == 3
    assert dlg.view.currentIndex().data() == "crate"
    dlg.filter.setText("rock")
    assert dlg.model.names == ["models/other/rock.mdl"]
    dlg._pick("models/other/rock.mdl")
    assert dlg.chosen() == "models/other/rock.mdl" and "rock" in dlg.info.text()


def test_without_game_the_browser_explains(window):
    window.editor.set_material_library(None)
    assert "Spielprofil" in window.model_browser.status.text()
    assert window.model_browser.model.rowCount() == 0
