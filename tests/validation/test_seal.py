"""Dicht-Prüfung gegen typische Fälle: offene Decke, Spalt, Clip-Wand, Brush-Entity."""
import pytest

from rampenschmiede.core.mathutil import BBox
from rampenschmiede.core.model import Entity, MapDocument
from rampenschmiede.core.templates import hull_around, starter_room
from rampenschmiede.core.validation.seal import check_seal, describe, seals


def room(doc, **kw):
    return hull_around(doc, BBox((-256, -256, 0), (256, 256, 256)), **kw)


def spawn(doc, x=0, y=0, z=16, cls="info_player_start"):
    return Entity(id=doc.new_id(), classname=cls, keyvalues=(("origin", f"{x} {y} {z}"),))


def test_no_entities_is_unknown():
    doc = MapDocument()
    doc._insert(room(doc))
    r = check_seal(doc)
    assert r.sealed and r.unknown
    assert "nicht prüfbar" in describe(doc, r)


def test_missing_ceiling_leaks_with_path_to_outside():
    doc = MapDocument()
    walls = room(doc)
    s = spawn(doc)
    doc._insert([*walls[:1], *walls[2:], s])
    r = check_seal(doc)
    assert not r.sealed and r.entity_id == s.id
    assert r.path[0] == (0, 0, 16)
    assert r.path[-1][2] > 256  # endet oberhalb des Raums, also draußen
    assert "info_player_start" in describe(doc, r)


def test_spawn_outside_room_leaks():
    doc = MapDocument()
    doc._insert([*room(doc), spawn(doc, x=1000)])
    assert not check_seal(doc).sealed


def test_small_gap_is_found_at_fine_grid():
    doc = MapDocument()
    walls = room(doc)
    # +X-Wand um 16 Units kürzen: Spalt von 16 Units an der Decke
    from rampenschmiede.core.geometry import primitives
    from rampenschmiede.core.model import Solid

    short = Solid(id=walls[3].id, faces=primitives.block((256, -272, 0), (272, 272, 240))[0])
    walls[3] = short
    doc._insert([*walls, spawn(doc)])
    assert not check_seal(doc).sealed


@pytest.mark.parametrize("material", ["TOOLS/TOOLSPLAYERCLIP", "TOOLS/TOOLSTRIGGER"])
def test_tool_textures_do_not_seal(material):
    doc = MapDocument()
    walls = room(doc, material=material, floor_material="DEV/DEV_MEASUREGENERIC01B")
    assert not seals(walls[1])
    doc._insert([*walls, spawn(doc)])
    assert not check_seal(doc).sealed


def test_brush_entities_do_not_seal():
    doc = MapDocument()
    walls = room(doc)
    detail = Entity(id=doc.new_id(), classname="func_detail")
    ceiling = walls[1].replace(parent_id=detail.id)
    doc._insert([walls[0], ceiling, *walls[2:], detail, spawn(doc)])
    assert not check_seal(doc).sealed


def test_spawn_reported_before_other_entities():
    doc = MapDocument()
    objs = starter_room(doc, "momentum")
    objs = [o for o in objs if not (hasattr(o, "faces") and o.faces[0].material == "TOOLS/TOOLSSKYBOX"
                                    and o.bbox().mins[2] >= 512)]  # Decke weg
    doc._insert(objs)
    r = check_seal(doc)
    assert not r.sealed
    assert doc.get(r.entity_id).classname == "info_player_start"
    assert len(r.leaking_ids) == 2  # Spawn und Sonne


def test_large_map_uses_coarser_cells_and_still_seals():
    doc = MapDocument()
    doc._insert([*hull_around(doc, BBox((-16384, -16384, -8192), (16384, 16384, 8192))), spawn(doc)])
    r = check_seal(doc, max_cells=300_000)
    assert r.sealed and r.cell_size > 64
