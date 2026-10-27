"""I/O-Verbindungen: Ziele, eingehende Ausgänge, Linien."""
from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.entities.io import (
    IN_COLOR,
    OUT_COLOR,
    entities_named,
    incoming,
    io_segments,
    target_names,
)
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.model import Entity, MapDocument, Output


def _doc():
    doc = MapDocument()
    button = Entity(id=doc.new_id(), classname="trigger_multiple", keyvalues=(("targetname", "knopf"),),
                    outputs=(Output("OnStartTouch", "tuer*", "Open"), Output("OnStartTouch", "!activator", "Kill")))
    brush = solids_from_faces(doc, primitives.block((0, 0, 0), (64, 64, 64)))[0].replace(parent_id=button.id)
    door1 = Entity(id=doc.new_id(), classname="func_door", keyvalues=(("targetname", "tuer_links"),
                                                                       ("origin", "256 0 0")))
    door2 = Entity(id=doc.new_id(), classname="func_door", keyvalues=(("targetname", "Tuer_rechts"),
                                                                       ("origin", "512 0 0")))
    CommandStack(doc).push(AddObjects([button, brush, door1, door2]))
    return doc, button, door1, door2


def test_targets_by_name_prefix_and_special():
    doc, button, d1, d2 = _doc()
    assert {e.id for e in entities_named(doc, "tuer*")} == {d1.id, d2.id}
    assert entities_named(doc, "!activator") == []
    assert [e.id for e in entities_named(doc, "TUER_LINKS")] == [d1.id]
    assert target_names(doc) == ["knopf", "tuer_links", "Tuer_rechts"]


def test_incoming_lists_sources():
    doc, button, d1, _ = _doc()
    [(src, out)] = incoming(doc, d1)
    assert src.id == button.id and out.input == "Open"
    assert incoming(doc, button) == []


def test_lines_from_brush_entity_center_to_targets():
    doc, button, d1, d2 = _doc()
    segs = io_segments(doc, [button.id])
    assert len(segs) == 2 and all(c == OUT_COLOR for *_, c in segs)
    assert segs[0][0] == (32, 32, 32)
    assert {s[1][0] for s in segs} == {256, 512}
    # Von der Tür aus gesehen: eingehende Linie vom Auslöser
    [(a, b, c)] = io_segments(doc, [d1.id])
    assert c == IN_COLOR and a == (32, 32, 32) and b[0] == 256
