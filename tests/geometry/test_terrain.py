"""Gelände: Brushes umwandeln, Pinselstriche über mehrere Kacheln, Vorlagen, Dicht-Prüfung."""
import numpy as np
import pytest

from rampenschmiede.core.blocks import insert_block
from rampenschmiede.core.commands import solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.geometry.displacement import (
    has_displacement,
    is_displacement_solid,
    sew,
    surfaces,
)
from rampenschmiede.core.io.vmf import export_vmf, parse_vmf
from rampenschmiede.core.model import Entity, MapDocument
from rampenschmiede.core.surf.catalog import CATALOG, Placement
from rampenschmiede.core.surf.terrain_templates import MAX_TILE, value_noise
from rampenschmiede.core.terrain import TerrainError, convert, flatten, sew_all, stroke, top_face
from rampenschmiede.core.validation.seal import seals

TERRAIN_KEYS = [k for k, t in CATALOG.items() if t.world and t.category == "Gelände"]


def block(doc, lo, hi):
    return solids_from_faces(doc, primitives.block(lo, hi))[0]


def test_convert_uses_the_top_face_and_only_world_brushes():
    doc = MapDocument()
    s = block(doc, (0, 0, 0), (256, 256, 16))
    k = top_face(s)
    assert s.faces[k].plane.normal[2] == pytest.approx(1)
    t = convert(doc, s, 2)
    assert has_displacement(t.faces[k]) and sum(has_displacement(f) for f in t.faces) == 1
    assert convert(doc, t, 2) is t  # schon Gelände
    assert not is_displacement_solid(flatten(t))
    ent = Entity(id=doc.new_id(), classname="func_detail")
    detail = solids_from_faces(doc, primitives.block((0, 0, 0), (64, 64, 64)), parent_id=ent.id)[0]
    with pytest.raises(TerrainError):
        convert(doc, detail)
    with pytest.raises(TerrainError):
        convert(doc, s, 7)


def test_stroke_over_two_tiles_stays_sewn():
    doc = MapDocument()
    a = convert(doc, block(doc, (0, 0, 0), (256, 256, 16)), 3)
    b = convert(doc, block(doc, (256, 0, 0), (512, 256, 16)), 3)
    doc._insert([a, b])
    changed = stroke([a, b], (256, 128, 16), 96, 40, "heben")
    assert len(changed) == 2
    # Heben trifft die gemeinsame Kante auf beiden Seiten gleich
    assert sew(changed) == []
    rough = stroke(changed, (256, 128, 56), 96, 30, "rauschen", seed=3)
    assert sew(rough) != []
    doc._replace(rough)
    fixed = sew_all(doc, rough)
    assert fixed and sew(fixed) == []
    # Von oben (2D): nur der Abstand in x/y zählt, die Höhe der Mitte ist egal
    far_above = stroke([a], (128, 128, 5000), 64, 10, "heben", ignore_axis=2)
    assert len(far_above) == 1 and stroke([a], (128, 128, 5000), 64, 10, "heben") == []


def test_noise_is_repeatable_and_bounded():
    x = np.linspace(0, 3, 50)
    a = value_noise(x, x * 0.5, seed=4)
    assert np.allclose(a, value_noise(x, x * 0.5, seed=4))
    assert not np.allclose(a, value_noise(x, x * 0.5, seed=5))
    assert a.min() >= -1 and a.max() <= 1


@pytest.mark.parametrize("key", TERRAIN_KEYS)
def test_templates_make_sewn_world_tiles(key):
    doc = MapDocument()
    objs, gen = insert_block(doc, key, None, Placement(64, -32, 0, 0))
    assert objs and all(o.parent_id is None and is_displacement_solid(o) for o in objs)
    for o in objs:
        bb = o.bbox()
        assert bb.maxs[0] - bb.mins[0] <= MAX_TILE and bb.maxs[1] - bb.mins[1] <= MAX_TILE
        assert not seals(o)  # Gelände dichtet die Map nicht ab
    assert sew(objs) == []  # Kacheln passen genau aneinander
    height = CATALOG[key].values()["hoehe"]
    top = max(o.bbox().maxs[2] for o in objs)
    assert 0.5 * height < top - 16 <= height * 1.02


def test_mountain_is_tiled_and_rotates_in_quarter_turns():
    doc = MapDocument()
    objs, _ = insert_block(doc, "gelaende_berg", {"laenge": 2048, "breite": 1024}, Placement(0, 0, 0, 90))
    assert len(objs) == 2
    lo = np.min([o.bbox().mins for o in objs], axis=0)
    hi = np.max([o.bbox().maxs for o in objs], axis=0)
    assert (lo[0], lo[1], hi[0], hi[1]) == (-512, 0, 512, 2048)


def test_slope_alpha_and_vmf_roundtrip():
    doc = MapDocument()
    objs, _ = insert_block(doc, "gelaende_klippe", None, Placement(0, 0, 0, 0))
    (surf,) = surfaces(objs[0])
    assert surf.disp.alphas.max() > 200 and surf.disp.alphas.min() < 10
    doc._insert(objs)
    back, _ = parse_vmf(export_vmf(doc).text)
    (s2,) = back.solids()
    assert np.allclose(surfaces(s2)[0].positions, surf.positions, atol=1e-3)
    assert np.allclose(surfaces(s2)[0].disp.alphas, surf.disp.alphas, atol=0.01)
