"""Easy Mode: Welt-Stil, Rampentextur (auch aus allen Texturen), Räume für Stages, Leiste im Fenster."""
from PySide6.QtCore import QSize

from rampenschmiede.core.blocks import block_info
from rampenschmiede.core.materials.theme import get_theme
from rampenschmiede.core.templates import LINEAR_ROOMS, STAGE_ROOMS, RoomMapSettings, RoomSpec
from rampenschmiede.core.zones import parse_zone_name
from rampenschmiede.ui.dialogs.easy_mode import STEPS, EasyModeWizard, EasyResult
from rampenschmiede.ui.dialogs.ramp_assistant import PRESETS, textured_ramp


def _colors(pix, step=6):
    img = pix.toImage()
    return {img.pixelColor(x, y).name() for x in range(0, img.width(), step) for y in range(0, img.height(), step)}


def test_textured_preview_shows_the_ramp_colours(qtbot):
    _name, ramp, lines, _wall = PRESETS[1]  # Neon: pinke Linien
    pix = textured_ramp("gerade", ramp, lines, QSize(240, 180), None)
    img = pix.toImage()
    pinkish = sum(1 for x in range(0, 240, 2) for y in range(0, 180, 2)
                  if (c := img.pixelColor(x, y)).alpha() == 255 and c.red() > 150 and c.blue() > 120 and c.green() < 120)
    assert pinkish > 10
    other = textured_ramp("gerade", (200, 200, 200), (40, 200, 40), QSize(240, 180), None)
    assert _colors(other) != _colors(pix)


def test_wizard_walks_style_texture_rooms_build(qtbot):
    dlg = EasyModeWizard("css")
    qtbot.addWidget(dlg)
    assert len(STEPS) == 4 and dlg.stack.currentIndex() == 0 and not dlg.back_btn.isEnabled()
    dlg.style_page.gallery.setCurrentRow(2)
    style = dlg.style_page.style()
    dlg.next_btn.click()
    # Vorgewählt: die Textur des Stils
    assert dlg.texture.colors_chosen() == (style.ramp, style.lines) and not dlg.texture.material()
    dlg.texture.textures.setCurrentRow(3)
    assert dlg.texture.colors_chosen() == (PRESETS[2][1], PRESETS[2][2])
    dlg.next_btn.click()
    page = dlg.course
    assert len(page.courses) == 3
    page.courses[0].name.setText("Eingang")
    page.courses[1].size.setCurrentIndex(3)   # Riesig
    page.add_bonus.click()
    dlg._update_plan()
    assert not dlg._error and "✓" in page.size_label.text()
    rooms = [i for i in page.plan.items if i.kind == "room"]
    assert len(rooms) == 4 and rooms[0].label == "Eingang"
    # Räume statt einer Linie: sie liegen nicht alle auf einer Höhe
    assert len({round(r.rect[1]) for r in rooms}) > 1
    dlg.next_btn.click()
    assert dlg.stack.currentIndex() == 3 and dlg.next_btn.isEnabled()
    choice = dlg.choice()
    s = choice.settings
    assert isinstance(s, RoomMapSettings) and not s.linear
    assert [st.name for st in s.stages] == ["Eingang", "", ""] and s.stages[1].size == STAGE_ROOMS[3][1]
    assert len(s.bonuses) == 1 and (choice.ramp, choice.lines) == (PRESETS[2][1], PRESETS[2][2])


def test_any_texture_can_be_the_ramp_texture(qtbot):
    dlg = EasyModeWizard()
    qtbot.addWidget(dlg)
    page = dlg.texture
    page.use_material("CONCRETE/CONCRETEFLOOR001A")
    assert page.material() == "CONCRETE/CONCRETEFLOOR001A"
    assert "concretefloor001a" in page.texture_name()
    assert dlg.choice().material == "CONCRETE/CONCRETEFLOOR001A"
    page.textures.setCurrentRow(0)
    assert not page.material()
    # Importieren gibt die neue Textur zurück und wählt sie
    page._import = lambda: ["EIGENE/MEIN_BILD"]
    assert page.import_image() == "EIGENE/MEIN_BILD" and page.material() == "EIGENE/MEIN_BILD"


def test_texture_picker_lists_textures_without_tools(qtbot):
    from rampenschmiede.ui.dialogs.texture_picker import TexturePicker

    dlg = TexturePicker(None)
    qtbot.addWidget(dlg)
    dlg._all = ["TOOLS/TOOLSSKYBOX", "METAL/METALWALL001A", "CONCRETE/CONCRETEFLOOR001A"]
    dlg.library = None
    dlg._refilter()
    assert dlg.model.names == ["METAL/METALWALL001A", "CONCRETE/CONCRETEFLOOR001A"]
    dlg.search.setText("metal")
    assert dlg.model.names == ["METAL/METALWALL001A"]
    dlg.view.setCurrentIndex(dlg.model.index(0))
    assert dlg.chosen() == "METAL/METALWALL001A"


def test_linear_is_one_big_room_and_too_big_maps_block_building(qtbot):
    dlg = EasyModeWizard()
    qtbot.addWidget(dlg)
    dlg.course.linear.setChecked(True)
    assert len(dlg.course._of(False)) == 1
    s = dlg.settings()
    assert s.linear and s.stages[0].size == LINEAR_ROOMS[0][1]
    dlg.course.staged.setChecked(True)
    assert len(dlg.course._of(False)) == 3
    for _ in range(9):
        dlg.course.add_stage.click()
    for c in dlg.course.courses:
        c.size.setCurrentIndex(3)
    dlg.go(3)
    assert dlg._error and not dlg.next_btn.isEnabled()
    for c in dlg.course.courses:
        c.size.setCurrentIndex(0)
    dlg._update_plan()
    assert not dlg._error and dlg.next_btn.isEnabled()


def test_easy_map_is_built_as_rooms_styled_and_ready_to_paint(window, qtbot):
    window.easy_bar.welcome()
    assert window.easy_bar.buttons["start"].isVisibleTo(window.easy_bar)
    assert not window.easy_bar.buttons["paint"].isVisibleTo(window.easy_bar)
    _name, ramp, lines, _wall = PRESETS[1]
    settings = RoomMapSettings(game="css", stages=(RoomSpec("Eingang", 3072), RoomSpec("", 3072)),
                               bonuses=(RoomSpec("Kurz", 3072),))
    assert window.build_easy_map(EasyResult(ramp, lines, "eis", settings))
    doc = window.editor.doc
    assert window.seal.check_now().sealed
    assert window.editor.tool.name == "paint"
    assert not any((block_info(e) or {}).get("template") == "gerade" for e in doc.entities())
    assert get_theme(doc).colors["ramp"] == "#{:02x}{:02x}{:02x}".format(*ramp)
    names = {parse_zone_name(e.get("targetname") or ""): (block_info(e) or {}).get("values", {}).get("name")
             for e in doc.entities() if e.classname == "trigger_multiple"}
    assert names[("start", 0, 0)] == "Eingang" and names[("start", 1, 0)] == "Kurz"
    bar = window.easy_bar
    assert bar.guiding and bar.buttons["paint"].isChecked() and "Raum" in bar.hint.text()
    window.editor.set_tool("wall")
    assert bar.buttons["wall"].isChecked() and "Wand" in bar.hint.text()
    # Neue Map: nichts zum Rückgängigmachen, Strg+Z nimmt den Stil nicht wieder ab
    assert not window.editor.stack.can_undo()
    window.settings.remove("easy_welcome_done")


def test_easy_map_with_a_library_texture(window, qtbot):
    settings = RoomMapSettings(game="css", stages=(RoomSpec("", 3072),))
    assert window.build_easy_map(EasyResult((0, 0, 0), (0, 0, 0), "eis", settings, material="metal/metalwall001a"))
    theme = get_theme(window.editor.doc)
    assert theme.ramp == "METAL/METALWALL001A" and theme.ramp_side == "METAL/METALWALL001A"
    assert window.editor.current_material.upper() == "METAL/METALWALL001A"
    window.settings.remove("easy_welcome_done")


def test_closing_the_welcome_bar_is_remembered(window, qtbot):
    window.easy_bar.action.emit("close")
    assert window.settings.value("easy_welcome_done") == "true"
    window.settings.remove("easy_welcome_done")
