"""Szenen-Ordner: Rampen, Welt, Trigger, Spawns … aus den Objekten abgeleitet."""
from rampenschmiede.core.blocks import build_block
from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.model import Entity, MapDocument
from rampenschmiede.core.scene import SceneIndex, kind_of, label, members


def _doc():
    doc = MapDocument()
    stack = CommandStack(doc)
    floor = solids_from_faces(doc, primitives.block((0, 0, -16), (256, 256, 0)))
    wedge = solids_from_faces(doc, primitives.wedge((0, 0, 0), (256, 256, 256)))
    block, _ = build_block(doc, "gerade", {})
    tele = Entity(id=doc.new_id(), classname="trigger_teleport", keyvalues=(("target", "d"),))
    trig_brush = solids_from_faces(doc, primitives.block((0, 0, 0), (32, 32, 32)))[0].replace(parent_id=tele.id)
    ents = [Entity(id=doc.new_id(), classname=c) for c in
            ("info_player_terrorist", "info_teleport_destination", "light_spot", "prop_static", "logic_relay")]
    stack.push(AddObjects([*floor, *wedge, *block, tele, trig_brush, *ents]))
    return doc, floor[0], wedge[0], block[0], tele, ents


def test_objects_land_in_one_folder_each():
    doc, floor, wedge, root, tele, ents = _doc()
    f = SceneIndex().folders(doc)
    assert floor.id in f["welt"]
    assert root.id in f["rampen"]
    assert tele.id in f["trigger"]
    assert [ents[0].id] == f["spawns"] and [ents[1].id] == f["teleport"]
    assert [ents[2].id] == f["lichter"] and [ents[3].id] == f["props"] and [ents[4].id] == f["sonstiges"]
    listed = [i for ids in f.values() for i in ids]
    assert len(listed) == len(set(listed))
    # Bausteine stehen als Ganzes drin, nicht ihre Einzelteile oder Clip-Hüllen
    assert not set(listed) & {s.id for s in doc.attached([root.id])}


def test_wedge_counts_as_ramp_only_when_steep():
    doc, _, wedge, *_ = _doc()
    f = SceneIndex().folders(doc)
    # 45°-Keil: Surf-Rampe
    assert wedge.id in f["rampen"]


def test_detail_brushes_are_sorted_like_world_brushes():
    doc = MapDocument()
    detail = Entity(id=doc.new_id(), classname="func_detail")
    box = solids_from_faces(doc, primitives.block((0, 0, 0), (64, 64, 64)))[0].replace(parent_id=detail.id)
    CommandStack(doc).push(AddObjects([detail, box]))
    f = SceneIndex().folders(doc)
    assert f["welt"] == [box.id] and detail.id not in [i for ids in f.values() for i in ids]


def test_members_include_brushes_and_labels():
    doc, _, _, root, tele, ents = _doc()
    assert set(members(doc, [tele.id])) == {tele.id, *(s.id for s in doc.children(tele.id))}
    assert label(tele) == "trigger_teleport"
    assert label(root).startswith("Gerade Rampe")


def test_kind_of_says_what_an_object_is():
    doc, floor, wedge, root, tele, ents = _doc()
    assert kind_of(doc, floor) == "Brush"
    assert kind_of(doc, root) == "Rampe"
    assert kind_of(doc, tele) == "Trigger"
    assert kind_of(doc, ents[2]) == "Licht"
    trig_brush = next(s for s in doc.solids() if s.parent_id == tele.id)
    assert kind_of(doc, trig_brush) == "Brush von trigger_teleport"


def test_lights_without_name_show_color_and_brightness():
    plain = Entity(id=1, classname="light", keyvalues=(("_light", "255 200 150 300"),))
    assert label(plain) == "light · 255 200 150 · 300"
    named = Entity(id=2, classname="light", keyvalues=(("_light", "255 200 150 300"), ("targetname", "lampe")))
    assert label(named) == "light · lampe"
