"""Formen in der Bibliothek links: anklicken wählt das Formen-Werkzeug mit dieser Form."""
from rampenschmiede.core.model import Solid
from rampenschmiede.ui.panels.library_panel import SHAPE_PREFIX
from rampenschmiede.ui.tools.shape_tool import SHAPES


def _item(window, key):
    tree = window.library.tree
    for i in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(i)
        for j in range(group.childCount()):
            if group.child(j).data(0, 256) == key:
                return group.child(j)
    raise AssertionError(key)


def test_library_lists_every_shape_with_icon(window):
    group = window.library.shape_group
    keys = [group.child(i).data(0, 256) for i in range(group.childCount())]
    assert keys == [SHAPE_PREFIX + k for k in SHAPES]
    assert all(not group.child(i).icon(0).isNull() for i in range(group.childCount()))


def test_click_shape_activates_shape_tool(window):
    item = _item(window, SHAPE_PREFIX + "stairs")
    window.library.tree.setCurrentItem(item)
    window.library._template_clicked(item)
    assert window.editor.tool.name == "shape"
    assert window.editor.tool.options.shape == "stairs"
    assert "Treppe" in window.library.box.title()
    assert window.library.insert_btn.isEnabled()


def test_shape_tool_highlights_library_entry(window):
    window.editor.set_tool("shape")
    window.editor.tools["shape"].set_shape("cylinder")
    assert window.library.tree.currentItem().data(0, 256) == SHAPE_PREFIX + "cylinder"


def test_drop_shape_builds_brushes(window):
    before = len([o for o in window.editor.doc.objects() if isinstance(o, Solid)])
    root = window.library.insert(SHAPE_PREFIX + "wedge", (256.0, 256.0, 0.0))
    after = [o for o in window.editor.doc.objects() if isinstance(o, Solid)]
    assert root is not None and len(after) == before + 1
    assert window.editor.tools["shape"].options.shape == "wedge"
