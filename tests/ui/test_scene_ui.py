"""BSP ins Fenster ziehen und im Szenen-Baum Ordner ausblenden."""
from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl

from rampenschmiede.ui.viewports.viewport import dropped_maps

from ..io.bsp_builder import build_bsp


def _mime(*paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return mime


def test_only_map_files_count_as_drops(tmp_path):
    mime = _mime(tmp_path / "a.bsp", tmp_path / "b.png", tmp_path / "c.VMF")
    assert [p.name for p in dropped_maps(mime)] == ["a.bsp", "c.VMF"]
    assert dropped_maps(QMimeData()) == []


def test_dropped_bsp_opens_with_scene_folders(window, qtbot, tmp_path):
    path = build_bsp(tmp_path / "surf_test.bsp")
    window.editor.files_dropped.emit([path])
    qtbot.waitUntil(lambda: any(e.classname == "trigger_teleport" for e in window.editor.doc.entities()))
    # Kompilieren darf nie die Original-BSP überschreiben
    assert window.editor.import_path == Path(tmp_path / "surf_test_bearbeitet.vmf")
    assert "surf_test" in window.windowTitle()
    scene = window.scene
    assert len(scene.folder_ids("trigger")) == 1
    assert len(scene.folder_ids("rampen")) == 1  # Detail-Rampe aus der BSP
    assert len(scene.folder_ids("welt")) == 2
    assert scene._items["trigger"].text(0) == "Trigger (1)"
    assert scene._items["props"].isHidden()  # leere Ordner verschwinden


def test_eye_hides_whole_folder_and_undo_restores(window, qtbot, tmp_path):
    window.open_path(build_bsp(tmp_path / "surf_test.bsp"))
    scene = window.scene
    doc = window.editor.doc
    [tele_id] = scene.folder_ids("trigger")
    brush_ids = [s.id for s in doc.children(tele_id)]
    scene._clicked(scene._items["trigger"], 1)
    assert all(doc.get(i).editor.hidden for i in [tele_id, *brush_ids])
    scene.refresh()
    assert scene._items["trigger"].toolTip(1) == "Einblenden"
    window.editor.undo()
    assert not any(doc.get(i).editor.hidden for i in [tele_id, *brush_ids])


def test_clicking_entry_selects_object(window, tmp_path):
    window.open_path(build_bsp(tmp_path / "surf_test.bsp"))
    scene = window.scene
    folder = scene._items["spawns"]
    folder.setExpanded(True)
    child = folder.child(0)
    child.setSelected(True)
    [spawn] = scene.folder_ids("spawns")
    assert window.editor.selection == {spawn}
    # Auge am Eintrag blendet nur dieses Objekt aus
    scene._clicked(child, 1)
    assert window.editor.doc.get(spawn).editor.hidden
