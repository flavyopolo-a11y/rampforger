"""VMF öffnen/exportieren, Kompilieren mit Attrappen-Compilern, Log-Sprünge, Dialoge."""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from rampenschmiede.core.commands import AddObjects, solids_from_faces
from rampenschmiede.core.compile import CompileSettings, Level
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.io.vmf import load_vmf
from rampenschmiede.core.model import Entity
from rampenschmiede.core.profiles import ProfileStore

from ..compile.fake_tools import fake_profile

FIXTURE = Path(__file__).parent.parent / "fixtures" / "beispiel.vmf"


def test_open_vmf_and_export(window, qtbot, tmp_path, monkeypatch):
    for vp in window.grid_view.viewports():
        vp.repaint()  # Renderer hat die leere Start-Szene hochgeladen
    assert window.open_path(FIXTURE)
    ed = window.editor
    # Die neue Szene muss neu hochgeladen werden (früher: gleiche Versionsnummer, leere Ansichten)
    vp3d = next(vp for vp in window.grid_view.viewports() if vp.is_3d)
    vp3d.repaint()
    qtbot.wait(20)
    if vp3d.renderer is not None:  # ohne OpenGL 3.3 (Windows-CI offscreen) gibt es nichts zu prüfen
        assert vp3d.renderer._faces_count > 0
    assert len(list(ed.doc.solids())) == 3 and len(list(ed.doc.entities())) == 4
    assert "(importiert)" in window.windowTitle()
    assert ed.file_path is None and ed.import_path == FIXTURE

    target = tmp_path / "export"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    assert window.file_export_vmf()
    doc, report = load_vmf(target.with_suffix(".vmf"))
    assert report.solids == 3 and report.entities == 4


def _setup_map(window, tmp_path, behaviour=None):
    ed = window.editor
    solid = solids_from_faces(ed.doc, primitives.block((0, 0, 0), (128, 128, 16)))[0]
    spawn = Entity(id=ed.doc.new_id(), classname="info_player_counterterrorist", keyvalues=(("origin", "64 64 32"),))
    ed.run(AddObjects([solid, spawn]))
    prof = fake_profile(tmp_path, behaviour)
    window.profiles = ProfileStore([prof], prof.name)
    window.compile_settings = CompileSettings(launch_game=False)
    return solid, spawn, prof


def _run(window, qtbot):
    assert window.start_compile()
    qtbot.waitUntil(lambda: not window.compiler.running and window.compiler.last_result is not None, timeout=20000)
    qtbot.wait(50)  # gequeuete Signale abarbeiten
    return window.compiler.last_result


def test_compile_success_and_jump_to_brush(window, qtbot, tmp_path):
    solid, _, prof = _setup_map(window, tmp_path, {"vrad": {"lines": ["Brush 2: WARNING, completely degenerate brush"]}})
    result = _run(window, qtbot)
    assert result.ok
    assert window.log_dock.isVisible()
    assert (Path(prof.game_dir) / "maps" / "unbenannt.bsp").exists()
    assert window.act_compile.isEnabled() and not window.act_compile_cancel.isEnabled()

    panel = window.compile_log
    # Offene Testmap: Die Vorab-Prüfung warnt schon vor vbsp
    assert "Vorab-Prüfung" in panel.lines()[0].text and panel.lines()[0].level is Level.WARNING
    warn = next(line for line in panel.lines() if line.brush_id == 2)
    assert panel.jump_to(warn)
    assert window.editor.selection == {solid.id}
    assert "Fertig" in panel.status.text()


def test_compile_leak_shows_path_and_finds_entity(window, qtbot, tmp_path):
    _, spawn, _ = _setup_map(window, tmp_path, {"vbsp": {"leak": True}})
    result = _run(window, qtbot)
    assert result.leaked and not result.ok
    ed = window.editor
    assert ed.leak_lines is not None and len(ed.leak_lines) == 4  # 3 Punkte = 2 Linien
    assert window.compile_log.btn_leak.isEnabled()
    leak = next(line for line in window.compile_log.lines() if "leaked!" in line.text)
    assert window.compile_log.jump_to(leak)
    assert ed.selection == {spawn.id}
    window.act_clear_leak.trigger()
    assert ed.leak_lines is None
    # Neues Dokument räumt die Spur ebenfalls weg
    ed.set_leak_path([(0, 0, 0), (1, 1, 1)])
    window.file_new()
    assert ed.leak_points == []


def test_only_problems_filter(window, qtbot, tmp_path):
    _setup_map(window, tmp_path, {"vrad": {"lines": ["Brush 2: WARNING, x"]}})
    _run(window, qtbot)
    panel = window.compile_log
    panel.only_problems.setChecked(True)
    visible = [panel.list.item(i).data(Qt.UserRole) for i in range(panel.list.count())
               if not panel.list.item(i).isHidden()]
    assert visible and all(line.level is not Level.INFO for line in visible)


def test_compile_dialog_presets_and_preview(window, tmp_path):
    from rampenschmiede.ui.dialogs.compile_dialog import CompileDialog

    _setup_map(window, tmp_path)
    dlg = CompileDialog(window.profiles, CompileSettings(launch_game=False), window.compiler.prepare, True, window)
    assert dlg.btn_run.isEnabled()
    assert "vbsp" in dlg.preview.toPlainText()
    dlg.preset_buttons["fast"].setChecked(True)
    assert dlg.settings.preset == "fast" and dlg.settings.vvis_args == "-fast"
    assert not dlg.settings.launch_game  # Häkchen bleiben beim Wechsel erhalten
    dlg.preset_buttons["geometry"].setChecked(True)
    assert "vvis" not in dlg.preview.toPlainText()
    dlg.e_vbsp.setText("-notjunc")
    dlg.e_vbsp.textEdited.emit("-notjunc")
    assert dlg.settings.preset == "custom" and dlg.settings.vbsp_args == "-notjunc"
    assert not any(b.isChecked() for b in dlg.preset_buttons.values())
    dlg.close()


def test_compile_dialog_without_profile(window):
    from rampenschmiede.ui.dialogs.compile_dialog import CompileDialog

    dlg = CompileDialog(ProfileStore(), CompileSettings(), window.compiler.prepare, False, window)
    assert not dlg.btn_run.isEnabled()
    assert "Kein Spielprofil" in dlg.problems.text()
    dlg.close()


def test_profiles_dialog_add_edit_detect(window, tmp_path, monkeypatch):
    from rampenschmiede.ui.dialogs import profiles_dialog
    from rampenschmiede.ui.dialogs.profiles_dialog import ProfilesDialog

    found = fake_profile(tmp_path)
    found.name = "Gefunden"
    monkeypatch.setattr(profiles_dialog, "detect_profiles", lambda: [found])
    dlg = ProfilesDialog(ProfileStore(), window)
    assert not dlg.form_widget.isEnabled()
    assert dlg.detect() == 1
    assert dlg.store.profiles[0].name == "Gefunden"
    assert "Spiel-Exe fehlt" in dlg.problems.text()  # Attrappe hat keine Exe
    assert "1 Spiel(e) gefunden" in dlg.info.text()
    dlg.add_profile()
    assert dlg.list.count() == 2 and dlg.list.currentRow() == 1
    dlg.f_name.setText("Mein Spiel")
    dlg.f_name.editingFinished.emit()
    dlg.f_game.setText(found.game_dir)
    dlg.f_game.edit.editingFinished.emit()
    p = dlg.result_store().profiles[1]
    assert p.name == "Mein Spiel" and p.game_dir == found.game_dir
    assert "vbsp nicht gefunden" in dlg.problems.text()
    # Doppelte Namen werden abgelehnt
    dlg.f_name.setText("Gefunden")
    dlg.f_name.editingFinished.emit()
    assert dlg.result_store().profiles[1].name == "Mein Spiel"
    dlg.remove_profile()
    assert [x.name for x in dlg.result_store().profiles] == ["Gefunden"]
    dlg.close()
