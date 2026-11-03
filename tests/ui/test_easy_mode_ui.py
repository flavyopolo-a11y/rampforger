"""Easy Mode: Assistent in fünf Schritten, Layout-Manager, Rampen-Texturvorschau, Leiste im Fenster."""
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from rampenschmiede.core.blocks import block_info
from rampenschmiede.core.materials.theme import get_theme
from rampenschmiede.core.zones import parse_zone_name
from rampenschmiede.ui.dialogs.easy_mode import DIFFICULTY, EasyModeWizard
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
    # Andere Farben -> anderes Bild
    other = textured_ramp("gerade", (200, 200, 200), (40, 200, 40), QSize(240, 180), None)
    assert _colors(other) != _colors(pix)


def test_wizard_walks_through_the_steps_and_plans_the_map(qtbot):
    dlg = EasyModeWizard("css")
    qtbot.addWidget(dlg)
    assert dlg.stack.currentIndex() == 0 and not dlg.back_btn.isEnabled()
    dlg.ramps.textures.setCurrentRow(2)       # Lava
    dlg.ramps.kinds.setCurrentRow(2)          # Banane
    assert dlg.ramps.kind() == "banane"
    assert dlg.ramps.colors_chosen() == (PRESETS[2][1], PRESETS[2][2])
    dlg.next_btn.click()
    dlg.style_page.gallery.setCurrentRow(5)
    dlg.next_btn.click()
    dlg.course.stages.setValue(3)
    dlg.course.bonuses.setValue(2)
    dlg.course.difficulty.setCurrentIndex(list(DIFFICULTY).index("schwer"))
    dlg.next_btn.click()
    assert dlg.stack.currentIndex() == 3
    table = dlg.layout_page.table
    assert table.rowCount() == 5
    table.cellWidget(0, 0).setText("Eingang")
    table.cellWidget(1, 2).setCurrentIndex(table.cellWidget(1, 2).findData("ski"))
    table.cellWidget(3, 0).setText("Kurz")
    dlg.layout_page.layout_combo.setCurrentIndex(1)
    dlg._update_plan()
    assert dlg.layout_page.plan.items and not dlg._error
    assert "✓" in dlg.layout_page.size_label.text()
    dlg.next_btn.click()
    assert dlg.next_btn.isEnabled()
    choice = dlg.choice()
    s = choice.settings
    assert (choice.ramp, choice.lines) == (PRESETS[2][1], PRESETS[2][2])
    assert choice.style == "neon" or choice.style  # sechster Stil
    assert s.layout == "reihen" and s.ramp_kind == "banane" and s.angle == DIFFICULTY["schwer"][1]
    assert [st.name for st in s.stage_specs] == ["Eingang", "", ""]
    assert s.stage_specs[1].kind == "ski"
    assert [b.name for b in s.bonuses] == ["Kurz", ""]


def test_linear_course_has_one_row_and_too_big_maps_block_building(qtbot):
    dlg = EasyModeWizard()
    qtbot.addWidget(dlg)
    dlg.course.linear.setChecked(True)
    assert dlg.layout_page.table.rowCount() == 1
    assert dlg.settings().stage_specs[0].ramps >= 4
    dlg.course.staged.setChecked(True)
    dlg.course.fine.setChecked(True)
    dlg.course.length.setValue(8192)
    dlg.course.stages.setValue(8)
    dlg.go(3)
    assert dlg._error and not dlg.next_btn.isEnabled()
    dlg.layout_page.layout_combo.setCurrentIndex(1)  # in Reihen passt es
    dlg._update_plan()
    dlg.go(4)
    assert not dlg._error and dlg.next_btn.isEnabled()


def test_easy_map_is_built_styled_and_ready_to_paint(window, qtbot):
    from rampenschmiede.core.templates import CourseSpec, SurfMapSettings
    from rampenschmiede.ui.dialogs.easy_mode import EasyResult

    window.easy_bar.welcome()
    assert window.easy_bar.buttons["start"].isVisibleTo(window.easy_bar)
    assert not window.easy_bar.buttons["paint"].isVisibleTo(window.easy_bar)
    _name, ramp, lines, _wall = PRESETS[1]
    settings = SurfMapSettings(game="css", ramp_kind="welle", stage_specs=(CourseSpec("Eingang", 1), CourseSpec("", 1)),
                               bonuses=(CourseSpec("Kurz", 1),))
    assert window.build_easy_map(EasyResult(ramp, lines, "eis", settings))
    doc = window.editor.doc
    assert window.seal.check_now().sealed
    assert window.editor.tool.name == "paint"
    assert window.library.current_key() == "welle"
    theme = get_theme(doc)
    assert theme.colors["ramp"] == "#{:02x}{:02x}{:02x}".format(*ramp)
    names = {parse_zone_name(e.get("targetname") or ""): (block_info(e) or {}).get("values", {}).get("name")
             for e in doc.entities() if e.classname == "trigger_multiple"}
    assert names[("start", 0, 0)] == "Eingang" and names[("start", 1, 0)] == "Kurz"
    bar = window.easy_bar
    assert bar.guiding and bar.buttons["paint"].isChecked()
    window.editor.set_tool("wall")
    assert bar.buttons["wall"].isChecked() and "Wand" in bar.hint.text()
    assert window.editor.stack.is_clean()
    window.settings.remove("easy_welcome_done")


def test_closing_the_welcome_bar_is_remembered(window, qtbot):
    window.easy_bar.action.emit("close")
    assert window.settings.value("easy_welcome_done") == "true"
    window.settings.remove("easy_welcome_done")


def test_library_preview_uses_textures(window, qtbot):
    window.apply_ramp_colors(__import__("rampenschmiede.ui.dialogs.ramp_assistant", fromlist=["x"]).AssistantChoice(
        (27, 27, 43), (255, 43, 214), (90, 90, 90)))
    window.library.select_template("gerade")
    img = window.library.preview.pixmap().toImage()
    pink = sum(1 for x in range(0, img.width(), 2) for y in range(0, img.height(), 2)
               if (c := img.pixelColor(x, y)).alpha() == 255 and c.red() > 150 and c.green() < 120 and c.blue() > 120)
    assert pink > 5
    assert QColor  # noqa: B018
