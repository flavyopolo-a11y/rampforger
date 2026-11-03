"""Easy Mode: Stages einzeln geplant, in Reihen, mit Bonus-Strecken."""
import time

from rampenschmiede.core.blocks import block_info
from rampenschmiede.core.model import MapDocument
from rampenschmiede.core.templates import CourseSpec, SurfMapSettings, new_surf_map, plan_surf_map
from rampenschmiede.core.templates.surf_map import total_length, total_width
from rampenschmiede.core.validation.seal import check_seal
from rampenschmiede.core.zones import parse_zone_name


def build(plan=None, **kw):
    doc = MapDocument()
    doc._insert(new_surf_map(doc, SurfMapSettings(**kw), plan))
    return doc


def zones(doc):
    out = {}
    for e in doc.entities():
        parsed = parse_zone_name(e.get("targetname") or "") if e.classname == "trigger_multiple" else None
        if parsed:
            out[parsed] = (block_info(e) or {}).get("values", {}).get("name", "")
    return out


def test_rows_with_bonuses_are_sealed_and_named():
    stages = (CourseSpec("Eingang", 2, "gerade"), CourseSpec("Lava-Raum", 1, "banane"), CourseSpec("", 3, "ski"))
    doc = build(game="css", layout="reihen", stage_specs=stages, bonuses=(CourseSpec("Kurz", 1),))
    assert check_seal(doc).sealed
    bb = doc.bbox()
    assert all(abs(c) <= 16384 for c in (*bb.mins, *bb.maxs))
    z = zones(doc)
    assert z[("start", 0, 0)] == "Eingang"
    assert z[("stage", 0, 2)] == "Lava-Raum"
    assert z[("stage", 0, 3)] == ""
    assert z[("end", 0, 0)] == ""
    assert z[("start", 1, 0)] == "Kurz" and ("end", 1, 0) in z
    kinds = sorted((block_info(e) or {}).get("template", "") for e in doc.entities()
                   if (block_info(e) or {}).get("template") in ("gerade", "banane", "ski"))
    assert kinds == ["banane", "gerade", "gerade", "gerade", "ski", "ski", "ski"]
    # Jede Stage außer der letzten endet mit einem Teleporter zur nächsten; Fall-Teleporter für 3 Stages + Bonus
    targets = sorted(e.get("target") for e in doc.entities() if e.classname == "trigger_teleport")
    assert targets == sorted(["stage_2", "stage_3", "stage_1", "stage_2", "stage_3", "bonus_1"])
    dests = {e.get("targetname") for e in doc.entities() if e.classname == "info_teleport_destination"}
    assert set(targets) <= dests


def test_rows_are_shorter_but_wider_than_a_line():
    line = SurfMapSettings(stages=4, ramps_per_stage=2)
    rows = SurfMapSettings(stages=4, ramps_per_stage=2, layout="reihen")
    assert total_length(rows) < total_length(line)
    assert total_width(rows) > total_width(line)


def test_plan_matches_the_course():
    plan = []
    build(plan, stages=2, ramps_per_stage=2, bonuses=(CourseSpec("", 1),))
    kinds = [p.kind for p in plan]
    assert kinds.count("ramp") == 5 and kinds.count("start") == 2 and kinds.count("stage") == 1
    assert kinds.count("end") == 2
    bonus = [p for p in plan if p.track == 1]
    main = [p for p in plan if p.track == 0]
    assert min(p.rect[1] for p in bonus) > max(p.rect[3] for p in main) - 1
    assert all(p.rect[0] < p.rect[2] and p.rect[1] < p.rect[3] for p in plan)


def test_quick_plan_is_the_same_and_reports_too_big_maps():
    s = SurfMapSettings(stages=6, ramps_per_stage=3, ramp_kind="banane", layout="reihen",
                        bonuses=(CourseSpec(), CourseSpec()))
    full = []
    new_surf_map(MapDocument(), s, full)
    t = time.perf_counter()
    quick, error = plan_surf_map(s)
    assert time.perf_counter() - t < 0.3
    assert quick == full and error == ""
    _plan, error = plan_surf_map(SurfMapSettings(stages=10, ramps_per_stage=4, ramp_length=4096))
    assert "Source" in error


def test_every_ramp_gets_the_shape_chosen_for_it():
    doc = build(game="css", stages=2,
                stage_specs=(CourseSpec("", 3, kinds=("gerade", "gerade", "welle")), CourseSpec("", 2, kinds=("ski", "banane"))))
    assert check_seal(doc).sealed
    placed = sorted(((block_info(e)["placement"][1], block_info(e)["placement"][0]), block_info(e)["template"])
                    for e in doc.entities() if (block_info(e) or {}).get("template") in ("gerade", "banane", "welle", "ski"))
    assert [k for _pos, k in placed] == ["gerade", "gerade", "welle", "ski", "banane"]


def test_frame_only_leaves_room_to_paint_ramps():
    doc = build(game="css", stages=3, ramps_per_stage=2, with_ramps=False, bonuses=(CourseSpec("", 1),))
    assert check_seal(doc).sealed
    assert not any((block_info(e) or {}).get("template") in ("gerade", "banane", "welle", "ski", "trapez")
                   for e in doc.entities())
    z = zones(doc)
    assert {("start", 0, 0), ("stage", 0, 2), ("stage", 0, 3), ("end", 0, 0), ("start", 1, 0)} <= set(z)
    # Fall-Teleporter decken den Platz für die Rampen ab
    assert sum(1 for e in doc.entities() if e.classname == "trigger_teleport") == 4
