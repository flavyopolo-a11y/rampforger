"""Kompilier-Pipeline mit Attrappen-Compilern, Log-Auswertung und Leak-Spur."""
import sys
import threading
import time
from pathlib import Path

import pytest

from rampenschmiede.core.compile import (
    CompileRunner,
    CompileSettings,
    CopyStep,
    LaunchStep,
    Level,
    LineSplitter,
    ToolStep,
    build_plan,
    classify,
    map_name_for,
    parse_pointfile,
    preset,
)

from .fake_tools import calls, fake_profile, set_behaviour


def vmf_file(tmp_path: Path, name: str = "surf_test") -> Path:
    d = tmp_path / "work"
    d.mkdir(exist_ok=True)
    p = d / f"{name}.vmf"
    p.write_text("world\n{\n}\n")
    return p


def run(plan, settings=None):
    lines = []
    runner = CompileRunner(plan, (settings or CompileSettings()).stop_on_leak, on_line=lines.append)
    return runner.run(), lines


# ---- Plan ---------------------------------------------------------------------------

def test_plan_normal(tmp_path):
    prof = fake_profile(tmp_path)
    vmf = vmf_file(tmp_path)
    plan = build_plan(prof, vmf, CompileSettings(launch_game=False))
    assert plan.problems == []
    tools = [s for s in plan.steps if isinstance(s, ToolStep)]
    assert [s.tool for s in tools] == ["vbsp", "vvis", "vrad"]
    for s in tools:
        assert s.args[:2] == ["-game", prof.game_dir]
        assert s.args[-1] == str(vmf.with_suffix(""))
    copy = next(s for s in plan.steps if isinstance(s, CopyStep))
    assert copy.target == str(Path(prof.game_dir) / "maps" / "surf_test.bsp")
    assert not any(isinstance(s, LaunchStep) for s in plan.steps)
    # Starten ohne Steam und Exe geht nicht, das meldet der Plan vorab
    assert any("Weder Steam" in p for p in build_plan(prof, vmf, CompileSettings()).problems)


def test_plan_presets(tmp_path):
    prof = fake_profile(tmp_path)
    vmf = vmf_file(tmp_path)
    geo = build_plan(prof, vmf, preset("geometry"))
    assert [s.tool for s in geo.steps if isinstance(s, ToolStep)] == ["vbsp"]
    fast = build_plan(prof, vmf, preset("fast"))
    vvis = next(s for s in fast.steps if isinstance(s, ToolStep) and s.tool == "vvis")
    assert "-fast" in vvis.args
    final = preset("final")
    final.vrad_args += ' -extra "-foo bar"'
    vrad = next(s for s in build_plan(prof, vmf, final).steps if isinstance(s, ToolStep) and s.tool == "vrad")
    assert "-both" in vrad.args and "-foo bar" in vrad.args


def test_plan_launch_via_steam_and_exe(tmp_path):
    prof = fake_profile(tmp_path)
    vmf = vmf_file(tmp_path)
    prof.steam_exe = str(tmp_path / "steam.exe")
    prof.launch_via_steam = True
    launch = build_plan(prof, vmf, CompileSettings()).steps[-1]
    assert isinstance(launch, LaunchStep)
    assert launch.args[:2] == ["-applaunch", "240"]
    assert launch.args[-2:] == ["+map", "surf_test"]
    prof.launch_via_steam = False
    prof.game_exe = str(tmp_path / "hl2.exe")
    launch = build_plan(prof, vmf, CompileSettings()).steps[-1]
    assert launch.program == prof.game_exe and launch.args[:2] == ["-game", prof.game_dir]


def test_plan_reports_missing_tools(tmp_path):
    prof = fake_profile(tmp_path)
    prof.bin_dir = str(tmp_path / "nirgends")
    plan = build_plan(prof, vmf_file(tmp_path), CompileSettings(launch_game=False))
    assert any("vbsp" in p for p in plan.problems)
    result, lines = run(plan)
    assert not result.ok and result.failed_step == "Vorbereitung"
    assert all(line.level is Level.ERROR for line in lines)


def test_map_name():
    assert map_name_for("surf mein Level ä") == "surf_mein_Level"
    assert map_name_for("   ") == "unbenannt"


# ---- Ausführen ------------------------------------------------------------------------

def test_run_success_copies_bsp(tmp_path):
    prof = fake_profile(tmp_path, {"vrad": {"lines": ["Brush 7: WARNING, completely degenerate brush"]}})
    vmf = vmf_file(tmp_path)
    plan = build_plan(prof, vmf, CompileSettings(launch_game=False))
    result, lines = run(plan)
    assert result.ok, [line.text for line in lines]
    assert result.warnings == 1 and result.errors == 0
    assert (Path(prof.game_dir) / "maps" / "surf_test.bsp").read_bytes() == b"VBSP"
    assert [c[0] for c in calls(Path(prof.bin_dir))] == ["vbsp", "vvis", "vrad"]
    warn = next(line for line in lines if line.level is Level.WARNING)
    assert warn.brush_id == 7
    # Fortschritt ohne Zeilenende landet trotzdem vollständig im Log
    assert any(line.text.endswith("0...1...2......10") for line in lines)


def test_run_stops_on_leak_and_reads_pointfile(tmp_path):
    prof = fake_profile(tmp_path, {"vbsp": {"leak": True}})
    vmf = vmf_file(tmp_path)
    result, lines = run(build_plan(prof, vmf, CompileSettings(launch_game=False)))
    assert not result.ok and result.leaked and result.failed_step == "VBSP"
    assert result.pointfile == [(64, 64, 32), (64, 64, -100), (0, 0, -4000)]
    assert [c[0] for c in calls(Path(prof.bin_dir))] == ["vbsp"]
    leak = next(line for line in lines if "leaked!" in line.text)
    assert leak.level is Level.ERROR and leak.position == (64, 64, 32)


def test_old_pointfile_is_removed(tmp_path):
    prof = fake_profile(tmp_path)
    vmf = vmf_file(tmp_path)
    vmf.with_suffix(".lin").write_text("1 2 3\n")
    result, _ = run(build_plan(prof, vmf, CompileSettings(launch_game=False)))
    assert result.ok and not result.leaked and result.pointfile == []
    assert not vmf.with_suffix(".lin").exists()


def test_leak_can_be_ignored(tmp_path):
    prof = fake_profile(tmp_path, {"vbsp": {"leak": True}})
    settings = CompileSettings(launch_game=False, run_vvis=False, stop_on_leak=False)
    result, _ = run(build_plan(prof, vmf_file(tmp_path), settings), settings)
    assert result.ok and result.leaked


def test_run_fails_on_exit_code(tmp_path):
    prof = fake_profile(tmp_path, {"vvis": {"code": 3, "lines": ["Error: couldn't open surf_test.prt"]}})
    result, lines = run(build_plan(prof, vmf_file(tmp_path), CompileSettings(launch_game=False)))
    assert not result.ok and result.failed_step == "VVIS"
    assert result.errors >= 2
    assert not (Path(prof.game_dir) / "maps" / "surf_test.bsp").exists()


def test_missing_bsp_fails_copy(tmp_path):
    prof = fake_profile(tmp_path, {"vbsp": {"no_bsp": True}})
    settings = CompileSettings(launch_game=False, run_vvis=False, run_vrad=False)
    result, _ = run(build_plan(prof, vmf_file(tmp_path), settings))
    assert not result.ok and result.failed_step == "Kopieren"


@pytest.mark.skipif(sys.platform == "win32", reason="Batch-Wrapper reichen kill() nicht an Python weiter")
def test_cancel_stops_running_tool(tmp_path):
    prof = fake_profile(tmp_path, {"vbsp": {"sleep": 30}})
    plan = build_plan(prof, vmf_file(tmp_path), CompileSettings(launch_game=False))
    runner = CompileRunner(plan)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", runner.run()))
    t.start()
    deadline = time.monotonic() + 10
    while not calls(Path(prof.bin_dir)) and time.monotonic() < deadline:
        time.sleep(0.05)
    runner.cancel()
    t.join(10)
    assert not t.is_alive()
    assert out["r"].cancelled and not out["r"].ok
    assert [c[0] for c in calls(Path(prof.bin_dir))] == ["vbsp"]
    set_behaviour(Path(prof.bin_dir), {})


# ---- Log ----------------------------------------------------------------------------------

@pytest.mark.parametrize("text, level, brush, entity, pos", [
    ("Brush 12: WARNING, completely degenerate brush", Level.WARNING, 12, None, None),
    ("Entity 3, Brush 40: mixed face contents", Level.WARNING, 40, 3, None),
    ("**** leaked ****", Level.ERROR, None, None, None),
    ("Entity info_player_terrorist (-64.00 0.00 72.00) leaked!", Level.ERROR, None, None, (-64, 0, 72)),
    ("Error! Bad brush at (10.5, -3, 0)", Level.ERROR, None, None, (10.5, -3, 0)),
    ("MAX_MAP_BRUSHES limit exceeded", Level.ERROR, None, None, None),
    ("Material not found!: CONCRETE/FOO", Level.WARNING, None, None, None),
    ("Processing areas...done (0)", Level.INFO, None, None, None),
    ("1300 brushes", Level.INFO, None, None, None),
])
def test_classify(text, level, brush, entity, pos):
    line = classify(text)
    assert line.level is level
    assert line.brush_id == brush
    assert line.entity_index == entity
    assert line.position == pos


def test_line_splitter():
    s = LineSplitter()
    assert s.feed(b"abc\r\nde") == ["abc"]
    assert s.partial == "de"
    assert s.feed(b"f\rg\n") == ["def", "g"]
    assert s.feed("ä\n".encode("cp1252")) == ["ä"]
    s.feed(b"rest")
    assert s.flush() == ["rest"]


def test_parse_pointfile():
    assert parse_pointfile("1 2 3\n\nfoo\n4.5 -6 7e1 extra\n") == [(1, 2, 3), (4.5, -6, 70)]


# ---- Verweise auflösen ---------------------------------------------------------------------

def test_resolve_targets():
    from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
    from rampenschmiede.core.compile import resolve
    from rampenschmiede.core.geometry import primitives
    from rampenschmiede.core.io.vmf import export_vmf
    from rampenschmiede.core.model import EditorInfo, Entity, MapDocument

    doc = MapDocument()
    stack = CommandStack(doc)
    block = solids_from_faces(doc, primitives.block((0, 0, 0), (64, 64, 64)))[0]
    hidden = solids_from_faces(doc, primitives.block((128, 0, 0), (192, 64, 64)))[0]
    hidden = hidden.replace(editor=EditorInfo(hidden=True))
    spawn = Entity(id=doc.new_id(), classname="info_player_counterterrorist", keyvalues=(("origin", "32 32 100"),))
    relay = Entity(id=doc.new_id(), classname="logic_relay", keyvalues=(("origin", "500 0 0"),))
    stack.push(AddObjects([block, hidden, spawn, relay]))
    export = export_vmf(doc, for_compile=True)
    assert "hidden" not in export.text  # beim Kompilieren wird alles gebaut
    by_obj = {v: k for k, v in export.solid_ids.items()}

    t = resolve(classify(f"Brush {by_obj[hidden.id]}: WARNING, completely degenerate brush"), export, doc)
    assert t.object_ids == (hidden.id,)
    t = resolve(classify("Entity 2, Brush 99999: mixed face contents"), export, doc)
    assert t.object_ids == (relay.id,)
    t = resolve(classify("Entity info_player_counterterrorist (32.00 32.00 100.00) leaked!"), export, doc)
    assert t.object_ids == (spawn.id,) and t.position == (32, 32, 100)
    t = resolve(classify("Error at (5000 5000 5000)"), export, doc)
    assert t.object_ids == () and t.position == (5000, 5000, 5000)
    assert resolve(classify("Error: something"), export, doc) is None
