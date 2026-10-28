"""Streu-Werkzeug im Fenster: Kit wählen, streuen (ein Undo-Schritt), Shift entfernt, Browser-Modell."""
import pytest
from PySide6.QtCore import Qt

from rampenschmiede.core.commands import AddObjects, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.materials import MaterialLibrary
from rampenschmiede.core.models.props import is_model_entity

from ..models.mdl_builder import write_cube_model


@pytest.fixture
def scatter_window(window, tmp_path, qtbot):
    root = tmp_path / "spiel"
    write_cube_model(root, name="models/props_foliage/tree_test.mdl", static=True, physics=False)
    write_cube_model(root, name="models/props_foliage/bush_test.mdl", static=True, physics=False)
    write_cube_model(root, name="models/props_foliage/tree_gib01.mdl")
    write_cube_model(root, name="models/props_c17/oildrum001.mdl", static=False, physics=True)
    window.editor.set_material_library(MaterialLibrary.for_game(None, [root]))
    window.model_browser.wait_for_index()
    qtbot.waitUntil(lambda: len(window.model_browser._all) == 4)
    ed = window.editor
    ed.run(AddObjects(solids_from_faces(ed.doc, primitives.block((-1024, -1024, -16), (1024, 1024, 0)))))
    window.tool_actions["scatter"].trigger()
    return window


def _props(window):
    return [e for e in window.editor.doc.entities() if is_model_entity(e)]


def test_kit_scatter_is_one_undo_step_and_shift_erases(scatter_window):
    w = scatter_window
    ed = w.editor
    tool = ed.tool
    assert tool.name == "scatter" and w.tool_options.currentWidget() is w.tool_options._pages["scatter"]
    opts = w.tool_options
    opts.scatter_source.setCurrentIndex(opts.scatter_source.findData("wald"))
    assert opts.scatter_list.count() == 2  # Bruchstück (gib) fehlt
    assert "2 Modelle" in opts.scatter_info.text()
    opts.scatter_list.item(1).setCheckState(Qt.Unchecked)
    assert len(tool.models()) == 1
    steps = len(ed.stack._undo)
    tool.settings.count = 4
    tool.settings.spacing = 32
    tool.begin((0.0, 0.0, 0.0))
    tool.drag((600.0, 0.0, 0.0))
    tool.end()
    placed = _props(w)
    assert 4 < len(placed) <= 8 and len(ed.stack._undo) == steps + 1
    assert {p.get("model") for p in placed} == {tool.models()[0]}
    assert all(p.classname == "prop_static" for p in placed)
    tool.begin((0.0, 0.0, 0.0), erase=True)
    tool.end()
    assert len(_props(w)) < len(placed)
    ed.stack.undo()
    ed.stack.undo()
    assert _props(w) == []


def test_browser_model_and_style_suggestion(scatter_window):
    w = scatter_window
    tool = w.editor.tool
    assert tool.source == "browser" and tool.models() == []
    w.model_browser.select_name("models/props_c17/oildrum001.mdl")
    assert "oildrum" in w.tool_options.scatter_info.text()
    assert tool.begin((0.0, 0.0, 0.0)) > 0
    tool.end()
    assert all(p.classname == "prop_dynamic" for p in _props(w))
    w.tool_options.suggest_kit("industrie")
    assert tool.source == "industrie" and tool.models() == ["models/props_c17/oildrum001.mdl"]
