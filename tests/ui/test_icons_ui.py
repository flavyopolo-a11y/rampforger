"""Symbole, hervorgehobenes Werkzeug und aktive Ansicht."""
from rampenschmiede.ui import icons


def test_all_icons_render(qapp):
    for name in icons.names():
        img = icons.pixmap(name, 24).toImage()
        painted = sum(1 for x in range(24) for y in range(24) if img.pixelColor(x, y).alpha() > 0)
        assert painted > 10, name
        assert not icons.icon(name).isNull()


def test_tools_have_icons_and_mode_label(window):
    for action in window.tool_actions.values():
        assert not action.icon().isNull()
    window.editor.set_tool("face")
    assert window.mode_label.text() == "Werkzeug: Seiten"
    assert window.tool_actions["face"].isChecked()


def test_active_viewport_is_highlighted(window):
    grid = window.grid_view
    grid.frames[2].viewport.activated.emit()
    assert grid.active_frame() is grid.frames[2]
    assert [f.active for f in grid.frames] == [False, False, True, False]
