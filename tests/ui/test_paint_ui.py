"""Rampen malen, Material ziehen und Gültigkeit der Textur-Auswahl."""
import pytest

from rampenschmiede.core.blocks import block_info
from rampenschmiede.core.model import Entity
from rampenschmiede.ui.panels.material_browser import MIME_MATERIAL


def _select_template(window, key):
    tree = window.library.tree
    for i in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(i)
        for j in range(group.childCount()):
            item = group.child(j)
            if item.data(0, 256) == key:
                tree.setCurrentItem(item)
                window.library._template_clicked(item)
                return
    raise AssertionError(key)


def _blocks(window):
    return [o for o in window.editor.doc.objects() if isinstance(o, Entity) and block_info(o)]


def test_click_template_activates_paint_and_stroke_builds_ramp(window):
    _select_template(window, "gerade")
    tool = window.editor.tool
    assert tool.name == "paint"
    tool._move((0.0, 0.0, 0.0))
    assert tool.ghost() is not None
    before = len(_blocks(window))
    tool._press((0.0, 0.0, 0.0))
    tool._move((0.0, 768.0, 0.0))
    tool._release()
    blocks = _blocks(window)
    assert len(blocks) == before + 1
    info = block_info(blocks[-1])
    assert info["values"]["laenge"] == 768
    assert info["placement"][3] == pytest.approx(90)


def test_click_without_drag_places_default(window):
    _select_template(window, "gerade")
    tool = window.editor.tool
    tool._press((512.0, 0.0, 0.0))
    tool._release()
    info = block_info(_blocks(window)[-1])
    assert info["values"]["laenge"] == 1024


def test_library_form_values_feed_painting(window):
    _select_template(window, "gerade")
    window.library.next_values["gerade"] = {"breite": 384}
    tool = window.editor.tool
    tool._press((0.0, 0.0, 0.0))
    tool._move((512.0, 0.0, 0.0))
    tool._release()
    assert block_info(_blocks(window)[-1])["values"]["breite"] == 384


def test_escape_returns_to_select(window, qtbot):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    _select_template(window, "kurve")
    tool = window.editor.tool
    vp = window.grid_view.viewports()[1]
    tool.key_press(vp, QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert window.editor.tool.name == "select"


def test_material_browser_drag_and_scope(window):
    browser = window.material_browser
    browser.model.set_names(["test/rot"])
    mime = browser.model.mimeData([browser.model.index(0)])
    assert bytes(mime.data(MIME_MATERIAL)).decode() == "test/rot"
    browser.scope.setCurrentIndex(browser.scope.findData("einer"))
    assert window.editor.material_scope == "einer"
    browser.scope.setCurrentIndex(browser.scope.findData("alle"))
    assert window.editor.material_scope == "alle"
