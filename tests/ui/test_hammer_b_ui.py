"""Paket B im Fenster: Hohl machen, Ausrichten/Verteilen, Map-Eigenschaften, Kameras, Statistik, Lightmap-Raster."""
import numpy as np
import pytest
from PySide6.QtWidgets import QComboBox

from rampenschmiede.core.commands import AddObjects, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.model import Solid
from rampenschmiede.ui.viewports.viewport import RENDER_MODES


def _boxes(window, n=2):
    ed = window.editor
    xs = [0, 160, 512, 700][:n]  # absichtlich ungleiche Abstände
    solids = solids_from_faces(ed.doc, [fs for i, x in enumerate(xs)
                                        for fs in primitives.block((x, 0, i * 32), (x + 128, 128, i * 32 + 128))])
    ed.run(AddObjects(solids))
    return solids


def _solids(window):
    return [o for o in window.editor.doc.objects() if isinstance(o, Solid)]


def test_hollow_makes_walls_and_undoes(window):
    ed = window.editor
    (box,) = _boxes(window, 1)
    assert not window.hollow_selection(32)  # nichts ausgewählt
    ed.set_selection([box.id])
    assert window.hollow_selection(32)
    assert len(_solids(window)) == 6 and ed.selection == {s.id for s in _solids(window)}
    ed.undo()
    assert len(_solids(window)) == 1


def test_hollow_asks_thickness_and_remembers(window, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    ed = window.editor
    (box,) = _boxes(window, 1)
    ed.set_selection([box.id])
    window.settings.setValue("hollow_thickness", 32)
    asked = []
    monkeypatch.setattr(QInputDialog, "getInt", staticmethod(lambda *a, **k: (asked.append(a[3]), (16, True))[1]))
    window.act_hollow.trigger()
    assert asked == [32] and len(_solids(window)) == 6
    assert int(window.settings.value("hollow_thickness")) == 16


def test_align_and_distribute_from_menu(window):
    ed = window.editor
    a, b, c = _boxes(window, 3)
    ed.set_selection([a.id, b.id, c.id])
    assert window.align_selection(2, "min")
    assert {ed.doc.get(s.id).bbox().mins[2] for s in (a, b, c)} == {0}
    assert window.distribute_selection(0)
    assert ed.doc.get(b.id).bbox().mins[0] == 256  # Mitte zwischen 0 und 512
    ed.set_selection([a.id])
    assert not window.align_selection(2, "max")
    menus = {act.text().replace("&", "") for act in window.align_actions + window.distribute_actions if act}
    assert len(menus) >= 9


def test_map_properties_shown_without_selection(window):
    ed = window.editor
    panel = window.selection_panel
    ed.set_selection([])
    assert not panel.world_box.isHidden()
    panel.world_fields["message"].setText("Surf Test")
    panel.world_fields["message"].editingFinished.emit()
    assert dict(ed.doc.world_keyvalues)["message"] == "Surf Test"
    ed.undo()
    assert dict(ed.doc.world_keyvalues).get("message", "") == ""
    (box,) = _boxes(window, 1)
    ed.set_selection([box.id])
    assert panel.world_box.isHidden()


def test_camera_speed_and_saved_cameras(window):
    window.set_camera_speed(2500)
    assert all(v.cam3d.speed == 2500 for v in window.views_3d())
    assert window.speed_actions[2500].isChecked()
    v = window.views_3d()[0]
    v.cam3d.position = np.array((100.0, 200.0, 300.0))
    assert window.save_camera() == 1
    assert not window.editor.stack.is_clean()  # wird mit der Map gespeichert
    v.cam3d.position = np.array((0.0, 0.0, 0.0))
    assert window.goto_camera(0)
    assert tuple(v.cam3d.position) == (100.0, 200.0, 300.0)
    assert not window.goto_camera(5)
    window._fill_cameras_menu()
    assert any("Kamera 1" in a.text() for a in window.cameras_menu.actions())
    window.clear_cameras()
    assert window.cameras() == []


def test_stats_dialog_lists_limits(window):
    _boxes(window, 2)
    dlg = window.show_stats()
    by_key = {st.key: st for st in dlg.stats}
    assert dlg.table.rowCount() == len(dlg.stats)
    assert by_key["brushes"].value == 2 and by_key["brushes"].level == "ok"
    dlg.close()


def test_lightmap_mode_in_view_menu(window):
    combo = window.grid_view.findChildren(QComboBox)
    modes = [c.itemData(i) for c in combo for i in range(c.count())]
    assert "lightmap" in modes and "lightmap" in RENDER_MODES


@pytest.mark.parametrize("mode", ["lightmap"])
def test_lightmap_view_renders(window, qtbot, mode):
    (box,) = _boxes(window, 1)
    v = window.views_3d()[0]
    if v.renderer is None:
        pytest.skip("kein OpenGL 3.3 verfügbar")
    v.render_mode = mode
    v.center_on((64, 64, 64), 300)
    img = v.grabFramebuffer()
    px = np.asarray([[img.pixelColor(x, y).getRgb()[:3] for x in range(0, img.width(), 4)]
                     for y in range(0, img.height(), 4)], dtype=int)
    gray = (px[..., 0] > 90) & (np.abs(px[..., 0] - px[..., 2]) < 30)  # Standard 16: grau
    red = (px[..., 0] > 150) & (px[..., 2] < 110)
    assert gray.sum() > 50 and red.sum() == 0
