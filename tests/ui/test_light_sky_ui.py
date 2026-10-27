"""Licht-Vorschau, Himmel, Auswahl links und der Schalter für Rampen-Texturen im Fenster."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from rampenschmiede.core.commands import AddObjects
from rampenschmiede.core.model import Entity
from rampenschmiede.ui.dialogs import sky_dialog
from rampenschmiede.ui.viewports.viewport import RENDER_MODES

from ..io.bsp_builder import build_bsp


def add(window, *objs):
    window.editor.run(AddObjects(list(objs)))


def test_light_preview_is_a_view_mode():
    assert RENDER_MODES["lit"] == "Licht-Vorschau"


def test_light_lines_only_for_selected_lights(window):
    ed = window.editor
    light = Entity(id=ed.doc.new_id(), classname="light", keyvalues=(("origin", "0 0 64"),))
    add(window, light)
    ed.set_selection(set())
    assert ed.light_lines() is None
    ed.set_selection({light.id})
    lines = ed.light_lines()
    assert lines is not None and lines.shape[1] == 6
    assert ed.lights().lights[0].entity_id == light.id


def test_aim_spot_at_camera(window):
    ed = window.editor
    spot = Entity(id=ed.doc.new_id(), classname="light_spot", keyvalues=(("origin", "0 0 64"), ("pitch", "-90")))
    add(window, spot)
    ed.set_selection({spot.id})
    panel = window.selection_panel.entity_panel
    cam = window.grid_view.viewports()[0].cam3d
    cam.yaw, cam.pitch = 90.0, -30.0
    ed.camera3d = cam
    assert panel.aim_at_camera()
    new = ed.doc.get(spot.id)
    assert new.get("pitch") == "-30" and new.get("angles") == "-30 90 0"


def test_selection_shows_on_the_left_with_what_it_is(window, qtbot):
    ed = window.editor
    assert window.dockWidgetArea(window.sel_dock) == Qt.LeftDockWidgetArea
    light = Entity(id=ed.doc.new_id(), classname="light", keyvalues=(("origin", "0 0 64"),
                                                                       ("_light", "255 200 150 300")))
    add(window, light)
    window.scene.refresh()
    ed.set_tool("select")
    ed.set_selection({light.id})
    folder = window.scene._items["lichter"]
    assert folder.isExpanded()
    item = folder.child(0)
    assert item.isSelected() and item.text(0) == "light · 255 200 150 · 300"
    summary = window.selection_panel.summary.text()
    assert "Licht" in summary and "light" in summary


def test_scope_switches_stay_in_sync(window):
    ed = window.editor
    browser = window.material_browser
    face_switch = window.tool_options.findChildren(type(browser.scope))[0]
    face_switch.buttons["einer"].click()
    assert ed.material_scope == "einer" and browser.scope.buttons["einer"].isChecked()
    browser.scope.buttons["alle"].click()
    assert face_switch.scope() == "alle"


def test_choose_sky_sets_skyname(window, monkeypatch):
    monkeypatch.setattr(sky_dialog.SkyDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(sky_dialog.SkyDialog, "chosen", lambda self: "sky_test")
    assert window.choose_sky()
    assert window.editor.doc.world_get("skyname") == "sky_test"
    window.editor.undo()
    assert window.editor.doc.world_get("skyname") != "sky_test"


def test_sky_dialog_lists_and_filters(qtbot, monkeypatch):
    monkeypatch.setattr(sky_dialog, "available_skies", lambda lib: ["sky_day01_01", "sky_dust"])
    dlg = sky_dialog.SkyDialog(None, "sky_dust")
    qtbot.addWidget(dlg)
    assert dlg.model.rowCount() == 2
    assert dlg.view.currentIndex().data(Qt.UserRole) == "sky_dust"
    dlg.filter.setText("day")
    assert dlg.model.rowCount() == 1 and dlg.model.index(0).data(Qt.DisplayRole) == "sky_day01_01"
    assert dlg.chosen() == "sky_dust"


def test_open_bsp_uses_its_packed_textures(window, tmp_path):
    from ..materials.fakegame import vmt_text, vtf_bytes

    path = build_bsp(tmp_path / "surf_eigen.bsp", world_mat="eigen/boden", pack={
        "materials/eigen/boden.vmt": vmt_text("eigen/boden").encode(),
        "materials/eigen/boden.vtf": vtf_bytes((10, 200, 30, 255)),
    })
    assert window.open_path(path)
    lib = window.editor.materials
    assert lib.texture("eigen/boden") is not None
    assert lib.is_own("eigen/boden")  # wird beim Kompilieren wieder in die BSP gepackt


def test_lit_view_renders(window, qtbot):
    vp = window.grid_view.viewports()[0]
    if vp.renderer is None:
        pytest.skip("kein OpenGL 3.3 verfügbar")
    ed = window.editor
    add(window, Entity(id=ed.doc.new_id(), classname="light", keyvalues=(("origin", "0 0 64"),)))
    vp.render_mode = "lit"
    img = vp.grabFramebuffer()
    assert img.width() > 0
    assert ed.camera3d is vp.cam3d
