"""Automatische Sicherung, Sicherung vor dem Speichern, Wiederherstellen."""
from PySide6.QtWidgets import QMessageBox

from rampenschmiede.core.commands import AddObjects, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.ui import autosave


def _add_box(window):
    ed = window.editor
    ed.run(AddObjects(solids_from_faces(ed.doc, primitives.block((0, 0, 0), (64, 64, 64)))))


def test_autosave_only_when_changed_and_keeps_last_ten(window):
    saver = window.autosaver
    assert saver.autosave_now() is None  # nichts geändert
    for _ in range(12):
        _add_box(window)
        assert saver.autosave_now() is not None
    assert saver.autosave_now() is None
    files = list(autosave.backups_dir().glob("unbenannt_auto_*.rsmap"))
    assert len(files) == autosave.KEEP_AUTOSAVES


def test_saving_keeps_previous_version(window, tmp_path):
    path = tmp_path / "map.rsmap"
    _add_box(window)
    assert window._save_to(path)
    assert not list(autosave.backups_dir().glob("map_vorher_*"))
    _add_box(window)
    assert window._save_to(path)
    assert len(list(autosave.backups_dir().glob("map_vorher_*"))) == 1


def test_recovery_offer_opens_latest_autosave_as_unsaved(window, monkeypatch):
    _add_box(window)
    n = len(window.editor.doc)
    latest = window.autosaver.autosave_now()
    window.editor.stack.set_clean()
    window.file_new(empty=True)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    window._offer_recovery()
    assert len(window.editor.doc) == n
    assert window.editor.file_path is None and not window.editor.stack.is_clean()
    assert autosave.latest_autosave() == latest
    window.editor.stack.set_clean()


def test_autosave_toggle_is_remembered(window):
    window.act_autosave.setChecked(False)
    window._toggle_autosave(False)
    assert window.autosaver.minutes == 0 and not window.autosaver.timer.isActive()
    assert int(window.settings.value("autosave_minutes")) == 0
    window._toggle_autosave(True)
    assert window.autosaver.minutes == autosave.DEFAULT_MINUTES
    assert int(window.settings.value("autosave_minutes")) == autosave.DEFAULT_MINUTES
