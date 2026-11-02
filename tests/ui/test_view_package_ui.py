"""Paket „Ansicht“: Trigger halbdurchsichtig/ausblendbar, Menü „Map“, leerer Material-Browser."""
from rampenschmiede.core.blocks import build_block
from rampenschmiede.core.commands import AddObjects
from rampenschmiede.core.model import Solid
from rampenschmiede.render.scene_mesh import is_translucent


def test_triggers_go_into_translucent_pass_and_can_be_hidden(window, qtbot):
    ed = window.editor
    objs, _ = build_block(ed.doc, "zone_start")
    ed.stack.push(AddObjects(objs))
    arrays = ed.scene.arrays()
    assert len(arrays.faces_translucent) > 0
    zone_solid = next(o for o in objs if isinstance(o, Solid))
    assert is_translucent(zone_solid)

    frame = window.grid_view.frames[0]
    assert frame.trigger_button.isVisible()
    frame.trigger_button.setChecked(False)
    assert not ed.show_triggers_3d
    # alle 3D-Ansichten folgen
    assert all(not f.trigger_button.isChecked() for f in window.grid_view.frames)
    frame.trigger_button.setChecked(True)
    assert ed.show_triggers_3d


def test_map_menu_collects_map_wide_actions(window):
    menus = {m.text(): m.menu() for m in window.menuBar().actions() if m.menu()}
    map_menu = menus["&Map"]
    actions = set(map_menu.actions())
    for a in (window.act_world_style, window.act_sky, window.act_skybox3d, window.act_problems, window.act_stats):
        assert a in actions
    tools = set(menus["&Werkzeuge"].actions())
    assert window.act_group in tools and window.act_carve in tools


def test_material_browser_without_game_offers_setup(window):
    mb = window.material_browser
    if window.editor.materials is None:
        assert not mb.empty.isHidden() and mb.view.isHidden()
