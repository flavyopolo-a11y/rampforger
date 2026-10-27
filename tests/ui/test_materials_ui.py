"""Material-Browser und Seiten-Werkzeug."""
import numpy as np
from PySide6.QtCore import Qt

from rampenschmiede.core.commands import AddObjects, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.materials import MaterialLibrary

from ..materials.fakegame import make_game


def _game(window, tmp_path, qtbot):
    window.editor.set_material_library(MaterialLibrary.for_game(make_game(tmp_path / "g")))
    browser = window.material_browser
    qtbot.waitUntil(lambda: browser.model.rowCount() == 4, timeout=5000)
    return browser


def _block(window):
    doc = window.editor.doc
    solid = solids_from_faces(doc, primitives.block((0, 0, 0), (64, 64, 64)))[0]
    window.editor.run(AddObjects([solid]))
    return solid


def test_browser_lists_searches_and_applies(window, tmp_path, qtbot):
    browser = _game(window, tmp_path, qtbot)
    browser.search.setText("rot")
    assert browser.model.names == ["test/rot"]
    browser.search.setText("")
    row = browser.model.names.index("lose/blau")
    browser._on_click(browser.model.index(row))
    assert window.editor.current_material == "LOSE/BLAU"
    solid = _block(window)
    window.editor.set_selection({solid.id})
    assert browser.apply_to_selection()
    assert {f.material for f in window.editor.doc.get(solid.id).faces} == {"LOSE/BLAU"}
    browser.filter.setCurrentIndex(browser.filter.findData("recent"))
    assert browser.model.names == ["lose/blau"]
    browser.filter.setCurrentIndex(browser.filter.findData("map"))
    assert browser.model.names == ["lose/blau"]


def test_thumbnails_load_in_background(window, tmp_path, qtbot):
    browser = _game(window, tmp_path, qtbot)
    model = browser.model
    idx = model.index(model.names.index("test/rot"))
    model.data(idx, Qt.DecorationRole)
    qtbot.waitUntil(lambda: "test/rot" in model._thumbs, timeout=5000)


def test_favorites(window, tmp_path, qtbot):
    browser = _game(window, tmp_path, qtbot)
    window.editor.set_current_material("TEST/GRUEN")
    browser.fav_button.setChecked(True)
    browser.filter.setCurrentIndex(browser.filter.findData("favorites"))
    assert browser.model.names == ["test/gruen"]


def test_new_shapes_use_current_material(window):
    window.editor.set_current_material("test/rot")
    assert window.editor.current_material == "TEST/ROT"


def test_face_tool_picks_and_edits_a_face(window, tmp_path, qtbot):
    _game(window, tmp_path, qtbot)
    solid = _block(window)
    tool = window.editor.tools["face"]
    window.editor.set_tool("face")
    ref = tool.pick(np.array([32.0, 32.0, 500.0]), np.array([0.0, 0.0, -1.0]))
    assert ref is not None and ref[0] == solid.id
    assert solid.faces[ref[1]].plane.normal[2] > 0.5
    tool.set_faces([ref])
    assert tool.apply_material("test/rot")
    faces = window.editor.doc.get(solid.id).faces
    assert faces[ref[1]].material == "TEST/ROT" and sum(f.material == "TEST/ROT" for f in faces) == 1
    page = window.tool_options
    assert "TEST/ROT" in page.face_info.text()
    assert tool.per_face(lambda f, poly, size: __import__(
        "rampenschmiede.core.materials.texturing", fromlist=["justify"]).justify(f, poly, size, "fit"), "x")
    assert window.editor.doc.get(solid.id).faces[ref[1]].uaxis.scale == 1.0  # 64 Units auf 64 Pixel
