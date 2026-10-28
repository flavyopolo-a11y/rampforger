"""3D-Skybox aus dem Menü: anlegen, ersetzen, entfernen, je ein Undo-Schritt."""
from PySide6.QtWidgets import QInputDialog

from rampenschmiede.core.skybox3d import skybox_ids


def test_make_and_replace_skybox(window):
    ed = window.editor
    steps = len(ed.stack._undo)
    assert window.make_skybox3d("berge")
    ids = set(skybox_ids(ed.doc))
    assert ids and ed.selection == ids and len(ed.stack._undo) == steps + 1
    cam = [e for e in ed.doc.entities() if e.classname == "sky_camera"]
    assert len(cam) == 1
    assert window.make_skybox3d("stadt")
    assert not ids & set(skybox_ids(ed.doc))
    ed.undo()
    assert set(skybox_ids(ed.doc)) == ids


def test_dialog_can_remove(window, monkeypatch):
    ed = window.editor
    window.make_skybox3d("wueste")
    monkeypatch.setattr(QInputDialog, "getItem", lambda *a, **k: (a[3][-1], True))
    assert window.skybox3d_dialog()
    assert not skybox_ids(ed.doc)
