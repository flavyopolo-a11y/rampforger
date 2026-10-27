"""Startraum für neue Maps und die laufende Dicht-Prüfung."""
from PySide6.QtCore import QSettings

from rampenschmiede.core.model import Entity, Solid


def test_new_map_starts_with_sealed_room(window, qtbot):
    QSettings("Rampenschmiede", "Rampenschmiede").setValue("new_map_starter", "true")
    window.act_starter.setChecked(True)
    window.file_new()
    doc = window.editor.doc
    assert len([o for o in doc.objects() if isinstance(o, Solid)]) == 6
    classes = {o.classname for o in doc.objects() if isinstance(o, Entity)}
    # Ohne Spielprofil: alle Spawn-Arten
    assert {"info_player_start", "info_player_counterterrorist", "light_environment"} <= classes
    assert window.editor.stack.is_clean()  # Startraum ist kein Undo-Schritt
    qtbot.waitUntil(lambda: window.seal.result is not None and window.seal.result.checked > 0, timeout=5000)
    assert window.seal.result.sealed
    assert "dicht" in window.seal_button.text()

    # Decke löschen: Die Prüfung meldet das Leck, ohne zu kompilieren
    ceiling = max((o for o in doc.objects() if isinstance(o, Solid)), key=lambda s: s.bbox().maxs[2])
    window.editor.set_selection([ceiling.id])
    window.editor.delete_selection()
    qtbot.waitUntil(lambda: window.seal.result is not None and not window.seal.result.sealed, timeout=5000)
    assert "Leck" in window.seal_button.text()
    window.show_seal_problem()
    assert window.editor.leak_lines is not None
    sel = window.editor.selected_objects()
    assert len(sel) == 1 and sel[0].classname.startswith("info_player")

    # Umhüllen macht die Map wieder dicht, in einem Undo-Schritt
    window.act_enclose.trigger()
    assert window.seal.check_now().sealed
    assert window.editor.leak_lines is None
    window.act_undo.trigger()
    assert not window.seal.check_now().sealed


def test_new_empty_and_setting_off(window):
    window.act_starter.setChecked(True)
    window.act_new_empty.trigger()
    assert len(window.editor.doc) == 0
    window.act_starter.trigger()  # ausschalten
    assert not window._starter_enabled()
    window.file_new()
    assert len(window.editor.doc) == 0


def test_starter_uses_game_of_active_profile(window, tmp_path):
    from rampenschmiede.core.profiles import GameProfile, ProfileStore

    window.profiles = ProfileStore([GameProfile(key="momentum", name="Momentum Mod")], "Momentum Mod")
    window.act_starter.setChecked(True)
    window.file_new()
    spawns = {o.classname for o in window.editor.doc.objects()
              if isinstance(o, Entity) and o.classname.startswith("info_player")}
    assert spawns == {"info_player_start"}
