"""3D-Vorschau in Modell- und Material-Browser: texturiert, drehbar."""
import pytest

from rampenschmiede.core.materials import MaterialLibrary
from rampenschmiede.ui.widgets.preview_3d import material_groups

from ..models.mdl_builder import write_cube_model, write_material


@pytest.fixture
def game_window(window, tmp_path, qtbot):
    root = tmp_path / "spiel"
    write_material(root, "models/test/crate_top", (250, 0, 0))
    write_material(root, "models/test/crate_side", (0, 0, 250))
    write_material(root, "brick/brickwall001a", (180, 90, 60))
    write_cube_model(root, name="models/test/crate.mdl")
    window.editor.set_material_library(MaterialLibrary.for_game(None, [root]))
    window.model_browser.wait_for_index()
    qtbot.waitUntil(lambda: len(window.model_browser._all) == 1)
    return window


def _center_color(widget, qtbot):
    widget.show()
    qtbot.waitExposed(widget)
    img = widget.grabFramebuffer()
    return img.pixelColor(img.width() // 2, img.height() // 2)


def test_model_preview_is_textured(game_window, qtbot):
    b = game_window.model_browser
    assert b.select_name("models/test/crate.mdl")
    groups = b.preview.groups
    assert groups and all(g.texture is not None for g in groups)
    c = _center_color(b.preview, qtbot)
    assert max(c.red(), c.blue()) > 60 and c.green() < 60  # rote oder blaue Seite, nicht der Hintergrund


def test_material_preview_on_shapes(game_window, qtbot):
    m = game_window.material_browser
    game_window.editor.set_current_material("BRICK/BRICKWALL001A")
    for i in range(m.shape.count()):
        m.shape.setCurrentIndex(i)
        g = m.preview3d.groups
        assert len(g) == 1 and g[0].texture is not None and len(g[0].positions) % 3 == 0
    c = _center_color(m.preview3d, qtbot)
    assert c.red() > c.blue() + 30


def test_drag_rotates_and_wheel_zooms(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent, QWheelEvent

    from rampenschmiede.ui.widgets.preview_3d import Preview3D

    w = Preview3D()
    w.set_groups(material_groups("x", None, "wuerfel"))
    before = w.eye().copy()

    def mouse(kind, x):
        return QMouseEvent(kind, QPointF(x, 10), QPointF(x, 10), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)

    w.mousePressEvent(mouse(QMouseEvent.MouseButtonPress, 10))
    w.mouseMoveEvent(mouse(QMouseEvent.MouseMove, 60))
    w.mouseReleaseEvent(mouse(QMouseEvent.MouseButtonRelease, 60))
    after = w.eye()
    assert abs(after - before).max() > 1
    dist = ((after - w._center) ** 2).sum() ** 0.5
    w.wheelEvent(QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                             Qt.NoModifier, Qt.NoScrollPhase, False))
    assert ((w.eye() - w._center) ** 2).sum() ** 0.5 < dist
