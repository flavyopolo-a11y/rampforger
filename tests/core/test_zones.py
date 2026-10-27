"""Zeitnahme-Zonen: Namen für CS:S-Timer, Momentum-Zonendatei, Prüfung."""
import json
import math

import pytest

from rampenschmiede.core.blocks import build_block
from rampenschmiede.core.compile import CompileRunner, CompileSettings, WriteStep, build_plan
from rampenschmiede.core.model import MapDocument
from rampenschmiede.core.profiles import GameProfile
from rampenschmiede.core.surf.catalog import ORIGIN, Placement, zone_name
from rampenschmiede.core.templates import SurfMapSettings, new_surf_map
from rampenschmiede.core.zones import collect_zones, momentum_zones, parse_zone_name, zone_problems


def add(doc, template, at=ORIGIN, **values):
    objs, _gen = build_block(doc, template, values, at)
    doc._insert(objs)
    return objs[0]


def course(doc, stages=0, bonus=False):
    add(doc, "zone_start", Placement(0, 0, 0, 0))
    for n in range(2, 2 + stages):
        add(doc, "zone_stage", Placement(1000 * n, 0, -64 * n, 0), nummer=n)
    add(doc, "zone_ende", Placement(9000, 0, -512, 0))
    if bonus:
        add(doc, "zone_start", Placement(0, 2000, 0, 90), bonus=1)
        add(doc, "zone_ende", Placement(0, 4000, 0, 90), bonus=1)


@pytest.mark.parametrize(("kind", "bonus", "number", "name"), [
    ("start", 0, 0, "mod_zone_start"),
    ("end", 0, 0, "mod_zone_end"),
    ("stage", 0, 3, "mod_zone_checkpoint_3"),
    ("start", 2, 0, "mod_zone_bonus_2_start"),
    ("end", 2, 0, "mod_zone_bonus_2_end"),
])
def test_names_follow_mod_zone_standard(kind, bonus, number, name):
    assert zone_name(kind, bonus, number) == name
    assert parse_zone_name(name) == (kind, bonus, number)


def test_unrelated_triggers_are_not_zones():
    assert parse_zone_name("stage_1") is None
    assert parse_zone_name("mod_zone_start_extra") is None


def test_zone_block_is_named_trigger_multiple():
    doc = MapDocument()
    root = add(doc, "zone_stage", nummer=4)
    assert root.classname == "trigger_multiple"
    assert root.get("targetname") == "mod_zone_checkpoint_4"
    assert all(f.material == "TOOLS/TOOLSTRIGGER" for s in doc.children(root.id) for f in s.faces)


def test_collect_reads_footprint_and_height():
    doc = MapDocument()
    add(doc, "zone_start", Placement(100, 0, 64, 90), laenge=256, breite=128, hoehe=96)
    (z,) = collect_zones(doc)
    assert (z.kind, z.track, z.bottom, z.height, z.yaw) == ("start", 0, 64, 96, 90)
    xs = sorted({p[0] for p in z.points})
    ys = sorted({p[1] for p in z.points})
    assert xs == [36, 164] and ys == [0, 256]


def _check_region(region, needs_tele):
    """Die wichtigsten Regeln aus Momentums zone-validator.ts."""
    pts = region["points"]
    assert 3 <= len(pts) <= 64
    assert region["height"] > 0
    for i, cur in enumerate(pts):
        prev, nxt = pts[i - 1], pts[(i + 1) % len(pts)]
        a = (prev[0] - cur[0], prev[1] - cur[1])
        b = (nxt[0] - cur[0], nxt[1] - cur[1])
        la, lb = math.hypot(*a), math.hypot(*b)
        assert la >= 4 and lb >= 4
        angle = math.acos((a[0] * b[0] + a[1] * b[1]) / (la * lb))
        assert math.radians(15) <= angle < math.pi - 1e-4
    if needs_tele:
        assert len(region["teleDestPos"]) == 3 and "teleDestYaw" in region


def _check_file(data):
    assert data["formatVersion"] == 1
    main = data["tracks"]["main"]
    for seg in main["zones"]["segments"]:
        assert all(isinstance(seg[k], bool) for k in ("limitStartGroundSpeed", "checkpointsRequired",
                                                      "checkpointsOrdered"))
        _check_region(seg["checkpoints"][0]["regions"][0], True)
    _check_region(main["zones"]["end"]["regions"][0], False)
    for bonus in data["tracks"]["bonuses"]:
        assert len(bonus["zones"]["segments"]) == 1
        _check_region(bonus["zones"]["segments"][0]["checkpoints"][0]["regions"][0], True)
        _check_region(bonus["zones"]["end"]["regions"][0], False)


def test_momentum_file_has_segments_per_stage_and_bonus():
    doc = MapDocument()
    course(doc, stages=3, bonus=True)
    zones = collect_zones(doc)
    assert zone_problems(zones) == []
    data = momentum_zones(zones, timestamp_ms=1)
    _check_file(data)
    assert len(data["tracks"]["main"]["zones"]["segments"]) == 4
    assert len(data["tracks"]["bonuses"]) == 1
    json.dumps(data)


def test_no_file_without_main_start_and_end():
    doc = MapDocument()
    add(doc, "zone_start")
    zones = collect_zones(doc)
    assert momentum_zones(zones) is None
    assert any("Zielzone fehlt" in p for p in zone_problems(zones))


def test_problems_for_gaps_and_duplicates():
    doc = MapDocument()
    course(doc)
    add(doc, "zone_stage", Placement(3000, 0, 0, 0), nummer=3)
    add(doc, "zone_stage", Placement(5000, 0, 0, 0), nummer=3)
    problems = zone_problems(collect_zones(doc))
    assert any("doppelt" in p for p in problems)
    assert any("lückenlos" in p for p in problems)


def test_wizard_map_has_valid_zones():
    doc = MapDocument()
    doc._insert(new_surf_map(doc, SurfMapSettings(game="momentum", stages=3, ramp_length=1024)))
    zones = collect_zones(doc)
    assert sorted((z.kind, z.number) for z in zones) == [("end", 0), ("stage", 2), ("stage", 3), ("start", 0)]
    assert zone_problems(zones) == []
    _check_file(momentum_zones(zones))


def _profile(tmp_path, key):
    return GameProfile(key=key, name=key, game_dir=str(tmp_path / "game"))


def test_plan_writes_zone_file_only_for_momentum(tmp_path):
    settings = CompileSettings(run_vbsp=False, run_vvis=False, run_vrad=False, copy_to_game=True, launch_game=False)
    vmf = tmp_path / "build" / "surf_test.vmf"
    plan = build_plan(_profile(tmp_path, "momentum"), vmf, settings, momentum_zones="{}")
    (step,) = [s for s in plan.steps if isinstance(s, WriteStep)]
    assert step.targets == [str(vmf.with_suffix(".json")),
                            str(tmp_path / "game" / "maps" / "zones" / "local" / "surf_test.json")]
    plan = build_plan(_profile(tmp_path, "css"), vmf, settings, momentum_zones="{}")
    assert not any(isinstance(s, WriteStep) for s in plan.steps)


def test_runner_writes_zone_files(tmp_path):
    target = tmp_path / "a" / "b" / "zonen.json"
    plan = build_plan(_profile(tmp_path, "momentum"), tmp_path / "x.vmf",
                      CompileSettings(run_vbsp=False, run_vvis=False, run_vrad=False, copy_to_game=False,
                                      launch_game=False))
    plan.problems.clear()
    plan.steps = [WriteStep("Momentum-Zonen", [str(target)], '{"formatVersion": 1}')]
    result = CompileRunner(plan).run()
    assert result.ok and json.loads(target.read_text(encoding="utf-8")) == {"formatVersion": 1}
