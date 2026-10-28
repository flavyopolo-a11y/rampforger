import numpy as np
import pytest

from rampenschmiede.core.commands import solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.geometry.displacement import (
    Displacement,
    brush_stroke,
    face_displacement,
    has_displacement,
    make_displacement,
    set_surface,
    sew,
    solid_ray_hit,
    surface_corners,
    surfaces,
)
from rampenschmiede.core.geometry.transform import rotate, translate
from rampenschmiede.core.io.vmf import export_vmf, parse_vmf
from rampenschmiede.core.model import MapDocument


def block(doc, lo=(0, 0, 0), hi=(64, 32, 16)):
    return solids_from_faces(doc, primitives.block(lo, hi))[0]


def top_index(solid):
    return max(range(len(solid.faces)), key=lambda k: solid.faces[k].plane.normal[2])


def terrain(doc, lo=(0, 0, 0), hi=(64, 32, 16), power=2):
    s = block(doc, lo, hi)
    return make_displacement(s, top_index(s), power)


def test_corners_clockwise_from_outside_starting_at_start():
    poly = [(0, 0, 16), (64, 0, 16), (64, 32, 16), (0, 32, 16)]  # gegen den Uhrzeigersinn von oben
    c = surface_corners(poly, (0, 0, 1), (0, 0, 16))
    assert c.tolist() == [[0, 0, 16], [0, 32, 16], [64, 32, 16], [64, 0, 16]]
    c = surface_corners(poly, (0, 0, 1), (60, 30, 0))
    assert c[0].tolist() == [64, 32, 16]
    assert surface_corners(poly[:3], (0, 0, 1), (0, 0, 0)) is None


def test_flat_grid_like_vbsp_rows_along_y():
    """Zeile i läuft von der Startecke entlang +Y, Spalte j entlang +X (wie VMF-Dateien aus Hammer)."""
    doc = MapDocument()
    s = terrain(doc)
    (surf,) = surfaces(s)
    assert surf.size == 5
    assert np.allclose(surf.positions[:, 2], 16)
    assert np.allclose(surf.positions[1], (16, 0, 16))   # i=0, j=1
    assert np.allclose(surf.positions[5], (0, 8, 16))    # i=1, j=0
    assert np.allclose(surf.positions[-1], (64, 32, 16))
    assert len(surf.triangles()) == 32


def test_raw_roundtrip_and_vmf_export(tmp_path):
    doc = MapDocument()
    s = terrain(doc)
    (surf,) = surfaces(s)
    raised = brush_stroke(surf, (32, 16, 16), 24, 10, "heben")
    s = set_surface(s, surf, raised)
    again = Displacement.from_raw(raised.to_raw())
    assert np.allclose(again.vectors, raised.vectors) and again.start == raised.start
    doc._insert([s])
    text = export_vmf(doc).text
    assert "dispinfo" in text and "triangle_tags" in text and "allowed_verts" in text
    back, _ = parse_vmf(text)
    (solid,) = back.solids()
    (surf2,) = surfaces(solid)
    assert np.allclose(surf2.positions, surfaces(s)[0].positions, atol=1e-4)


def test_raise_lower_smooth_and_alpha():
    doc = MapDocument()
    s = terrain(doc, hi=(256, 256, 16), power=3)
    (surf,) = surfaces(s)
    up = brush_stroke(surf, (128, 128, 16), 64, 32, "heben")
    s = set_surface(s, surf, up)
    (surf,) = surfaces(s)
    z = surf.positions[:, 2].reshape(9, 9)
    assert z[4, 4] == pytest.approx(48) and z[0, 0] == pytest.approx(16)
    assert brush_stroke(surf, (9999, 0, 0), 64, 32, "heben") is None
    smooth = brush_stroke(surf, (128, 128, 16), 128, 16, "glaetten")
    assert smooth.vectors[40, 2] < up.vectors[40, 2]
    flat = brush_stroke(surf, (128, 128, 16), 512, 16, "ebnen")
    assert np.ptp((surf.base + flat.vectors)[:, 2]) < np.ptp(surf.positions[:, 2])
    # Pinsel sitzt auf der angehobenen Spitze (z = 48)
    alpha = brush_stroke(surf, (128, 128, 48), 64, 100, "alpha")
    assert alpha.alphas[40] == 100 and alpha.alphas[0] == 0
    gone = brush_stroke(surfaces(set_surface(s, surf, alpha))[0], (128, 128, 48), 64, 300, "alpha_weg")
    assert gone.alphas.max() == 0


def test_sew_closes_seams_between_neighbours():
    doc = MapDocument()
    a = terrain(doc, (0, 0, 0), (64, 64, 16))
    b = terrain(doc, (64, 0, 0), (128, 64, 16))
    (sa,) = surfaces(a)
    a = set_surface(a, sa, brush_stroke(sa, (64, 32, 16), 40, 20, "heben"))
    changed = sew([a, b])
    assert len(changed) == 2
    pa, pb = surfaces(changed[0])[0].positions, surfaces(changed[1])[0].positions
    edge_a = pa[np.isclose(surfaces(changed[0])[0].base[:, 0], 64)]
    edge_b = pb[np.isclose(surfaces(changed[1])[0].base[:, 0], 64)]
    assert np.allclose(sorted(map(tuple, edge_a)), sorted(map(tuple, edge_b)))
    assert sew(changed) == []  # schon geschlossen


def test_move_and_rotate_keep_the_shape():
    doc = MapDocument()
    s = terrain(doc, hi=(64, 64, 16))
    (surf,) = surfaces(s)
    s = set_surface(s, surf, brush_stroke(surf, (0, 0, 16), 30, 20, "heben"))
    before = surfaces(s)[0].positions
    moved = translate(s, (100, 0, 0))
    assert np.allclose(surfaces(moved)[0].positions, before + (100, 0, 0))
    turned = rotate(s, (32, 32, 0), 2, 90)
    peak = surfaces(turned)[0].positions[np.argmax(surfaces(turned)[0].positions[:, 2])]
    assert np.allclose(peak[:2], (64, 0)) and peak[2] == pytest.approx(36)


def test_ray_hits_the_raised_surface_not_the_box():
    doc = MapDocument()
    s = terrain(doc, hi=(256, 256, 16), power=3)
    (surf,) = surfaces(s)
    s = set_surface(s, surf, brush_stroke(surf, (128, 128, 16), 64, 100, "heben"))
    t = solid_ray_hit(s, (128, 128, 500), (0, 0, -1))
    assert t == pytest.approx(500 - 116)
    assert solid_ray_hit(s, (1000, 1000, 500), (0, 0, -1)) is None


def test_face_helpers():
    doc = MapDocument()
    s = terrain(doc)
    k = top_index(s)
    assert has_displacement(s.faces[k]) and not has_displacement(s.faces[(k + 1) % 6])
    assert face_displacement(s.faces[k]).power == 2
    with pytest.raises(ValueError):
        make_displacement(solids_from_faces(doc, primitives.wedge((0, 0, 0), (64, 64, 64)))[0], 0)
