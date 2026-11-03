"""Easy Mode: Surf-Map aus Räumen, jede Stage für sich mit Platz für Kurven."""
from rampenschmiede.core.blocks import block_info
from rampenschmiede.core.model import MapDocument
from rampenschmiede.core.templates import RoomMapSettings, RoomSpec, new_room_map, plan_room_map
from rampenschmiede.core.templates.room_map import room_grid
from rampenschmiede.core.validation.seal import check_seal
from rampenschmiede.core.zones import parse_zone_name


def _build(s):
    doc = MapDocument()
    doc._insert(new_room_map(doc, s))
    return doc


def test_every_stage_is_its_own_sealed_room():
    s = RoomMapSettings(game="css", stages=(RoomSpec("Eingang", 4096), RoomSpec("", 3072), RoomSpec("", 6144)),
                        bonuses=(RoomSpec("Kurz", 3072),))
    doc = _build(s)
    assert check_seal(doc).sealed
    plan, err = plan_room_map(s)
    assert not err
    rooms = [i for i in plan if i.kind == "room"]
    assert [r.label for r in rooms] == ["Eingang", "Stage 2", "Stage 3", "Kurz"]
    # Räume überlappen nicht
    for a in rooms:
        for b in rooms:
            if a is not b:
                assert a.rect[2] <= b.rect[0] or b.rect[2] <= a.rect[0] or a.rect[3] <= b.rect[1] or b.rect[3] <= a.rect[1]
    zones = {parse_zone_name(e.get("targetname") or "") for e in doc.entities() if e.classname == "trigger_multiple"}
    assert ("start", 0, 0) in zones and ("start", 1, 0) in zones
    teleports = [(block_info(e) or {}).get("values", {}).get("ziel") for e in doc.entities()
                 if e.classname == "trigger_teleport"]
    # Ziel jeder Stage -> nächste Stage, Boden jedes Raums -> sein eigener Start
    assert teleports.count("stage_2") == 2 and teleports.count("stage_3") == 2
    assert teleports.count("stage_1") == 1 and teleports.count("bonus_1") == 1
    assert sum(1 for e in doc.entities() if e.classname.startswith("info_player")) > 0


def test_linear_map_is_one_room_with_start_and_end():
    s = RoomMapSettings(stages=(RoomSpec("", 8192), RoomSpec()), linear=True)
    plan, err = plan_room_map(s)
    assert not err
    assert [i.kind for i in plan].count("room") == 1
    assert any(i.kind == "end" for i in plan) and not any(i.kind == "teleport" for i in plan)


def test_rooms_form_a_grid_not_a_line():
    corners = room_grid([4096] * 6)
    assert len({y for _x, y in corners}) == 2 and len({x for x, _y in corners}) == 3


def test_too_many_big_rooms_are_reported():
    _plan, err = plan_room_map(RoomMapSettings(stages=tuple(RoomSpec(size=8192) for _ in range(16))))
    assert "32768" in err
