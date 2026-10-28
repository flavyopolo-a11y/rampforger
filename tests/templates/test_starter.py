"""Startraum und Hülle um die Map."""
from rampenschmiede.core.mathutil import BBox
from rampenschmiede.core.model import Entity, MapDocument, Solid
from rampenschmiede.core.templates import enclose_map, hull_around, starter_room
from rampenschmiede.core.validation.seal import check_seal


def _doc_with(objs):
    doc = MapDocument()
    doc._insert(objs(doc) if callable(objs) else objs)
    return doc


def test_starter_room_per_game():
    for game, expected in (("css", {"info_player_counterterrorist", "info_player_terrorist"}),
                           ("momentum", {"info_player_start"}),
                           (None, {"info_player_start", "info_player_counterterrorist", "info_player_terrorist"})):
        doc = MapDocument()
        objs = starter_room(doc, game)
        spawns = {o.classname for o in objs if isinstance(o, Entity) and o.classname.startswith("info_player")}
        assert spawns == expected
        assert any(isinstance(o, Entity) and o.classname == "light_environment" for o in objs)
        solids = [o for o in objs if isinstance(o, Solid)]
        # Hülle (6), Startblock, Startzone
        assert len(solids) == 8 and all(s.is_valid() for s in solids)
        assert any(isinstance(o, Entity) and o.get("targetname") == "mod_zone_start" for o in objs)


def test_starter_room_is_sealed_and_spawn_stands_inside():
    doc = MapDocument()
    doc._insert(starter_room(doc, "css"))
    result = check_seal(doc)
    assert result.sealed and not result.unknown
    floor_top = max(s.bbox().maxs[2] for s in doc.solids() if s.faces[0].material.startswith("DEV"))
    for e in doc.entities():
        if e.classname.startswith("info_player"):
            assert e.origin[2] > floor_top  # nicht im Boden


def test_hull_walls_do_not_overlap():
    doc = MapDocument()
    walls = hull_around(doc, BBox((0, 0, 0), (256, 128, 64)))
    boxes = [w.bbox() for w in walls]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            overlap = [min(a.maxs[k], b.maxs[k]) - max(a.mins[k], b.mins[k]) for k in range(3)]
            assert min(overlap) <= 0


def test_enclose_map_seals_open_map():
    doc = MapDocument()
    spawn = Entity(id=doc.new_id(), classname="info_player_start", keyvalues=(("origin", "100 -40 30"),))
    doc._insert([spawn])
    assert not check_seal(doc).sealed
    hull = enclose_map(doc)
    doc._insert(hull)
    assert check_seal(doc).sealed
    inner_lo = min(w.bbox().maxs[0] for w in hull)
    assert inner_lo <= 100 - 256


def test_hull_grows_when_content_sticks_out_and_undo_restores():
    from rampenschmiede.core.commands import AddObjects, CommandStack
    from rampenschmiede.core.geometry import primitives
    from rampenschmiede.core.model import MapDocument, Solid
    from rampenschmiede.core.templates.starter import grow_hull, hull_parts, starter_room

    doc = MapDocument()
    doc._insert(starter_room(doc, "css"))
    assert grow_hull(doc) is None  # leerer Startraum passt
    stack = CommandStack(doc)
    before = {k: s.bbox() for k, s in hull_parts(doc).items()}
    block = Solid(id=doc.new_id(), faces=primitives.block((4000, 0, 0), (4600, 256, 4000))[0])
    stack.push(AddObjects([block]))
    stack.attach(grow_hull(doc))
    parts = hull_parts(doc)
    assert parts["+x"].bbox().mins[0] >= 4600 + 512
    assert parts["decke"].bbox().mins[2] >= 4000 + 512
    assert parts["-x"].bbox().maxs[0] == before["-x"].maxs[0]  # andere Seiten bleiben
    assert parts["boden"].bbox().maxs[2] == 0  # Boden bleibt, wo er ist
    assert grow_hull(doc) is None
    stack.undo()
    assert doc.get(block.id) is None
    assert {k: s.bbox() for k, s in hull_parts(doc).items()} == before


def test_hull_never_shrinks_and_ignores_missing_parts():
    from rampenschmiede.core.model import MapDocument
    from rampenschmiede.core.templates.starter import grow_hull, hull_parts, starter_room

    doc = MapDocument()
    doc._insert(starter_room(doc, "css"))
    floor = hull_parts(doc)["boden"]
    doc._remove([floor.id])
    assert hull_parts(doc) is None and grow_hull(doc) is None
