"""Sichtbare Kurven ohne Splitter: ungerundet, ein ebenes Viereck je Profilkante und Segment."""
import math

import pytest

from rampenschmiede.core.geometry.brush import solid_polygons
from rampenschmiede.core.surf import sweep
from rampenschmiede.core.surf.catalog import generate
from rampenschmiede.core.surf.sweep import VISIBLE_INSET, inset_profile


def _no_fallback(monkeypatch):
    calls = []
    real = sweep.loft_faces

    def spy(*a, **k):
        out = real(*a, **k)
        calls.append(out is not None)
        return out

    monkeypatch.setattr(sweep, "loft_faces", spy)
    return calls


@pytest.mark.parametrize("name", ["kurve", "kurve_halb", "s_kurve", "gabelung"])
def test_flat_curve_has_one_face_per_profile_edge(name, monkeypatch):
    calls = _no_fallback(monkeypatch)
    gen = generate(name, {}, exact=True)
    assert calls and all(calls)
    for faces in gen.face_sets:
        polys = solid_polygons(faces)
        assert all(p and len(p) >= 3 for p in polys)
        # zwei Kappen plus genau eine Fläche je Profilkante, keine geteilten Dreiecke
        assert len(faces) == 2 + max(len(p) for p in polys[:2])


@pytest.mark.parametrize("values", [{"gefaelle": -512}, {"gefaelle": -2048}, {"profil": "trapez", "gefaelle": -700}])
def test_descending_curve_stays_convex_and_closed(values, monkeypatch):
    calls = _no_fallback(monkeypatch)
    gen = generate("kurve", values, exact=True)
    assert calls and all(calls)
    previous = None
    for faces in gen.face_sets:
        polys = solid_polygons(faces)
        assert all(p and len(p) >= 3 for p in polys)
        # Jede Seite ist eben: alle ihre Eckpunkte liegen auf der Ebene der Seite
        for face, poly in zip(faces, polys):
            assert all(abs(face.plane.distance(p)) < 0.02 for p in poly)
        if previous is not None:
            # Naht ohne Spalt: Endkappe des einen = Anfangskappe des nächsten Segments
            assert all(min(math.dist(p, q) for q in polys[0]) < 0.05 for p in previous)
            assert all(min(math.dist(p, q) for q in previous) < 0.05 for p in polys[0])
        previous = polys[1]


def test_visible_curve_lies_inside_integer_clip():
    for values in ({}, {"gefaelle": -512}, {"oben": 64, "lippe": 32}):
        vis = generate("kurve", values, exact=True)
        clip = generate("kurve", values)
        for vf, cf in zip(vis.face_sets, clip.face_sets):
            pts = [p for poly in solid_polygons(vf) if poly for p in poly]
            surf = [f.plane for f in cf if 0.05 < abs(f.plane.normal[2]) < 0.95 and "NODRAW" not in f.material]
            assert surf and all(pl.distance(p) < -0.2 for pl in surf for p in pts)


def test_inset_keeps_bottom_and_shared_edges():
    # zwei Teile, die sich die senkrechte Kante x=0 teilen
    left = [(-100, 0), (0, 0), (0, 100)]
    right = [(0, 0), (100, 0), (0, 100)]
    a, b = inset_profile([left, right])
    # Unterkante bleibt auf h=0, die gemeinsame Kante bleibt auf x=0
    assert all(p[1] >= -1e-9 for p in a + b)
    assert min(p[1] for p in a) == pytest.approx(0)
    assert max(p[0] for p in a) == pytest.approx(0)
    # die schräge Außenkante wandert um genau VISIBLE_INSET nach innen
    top = max(a, key=lambda p: p[1])
    assert top[1] == pytest.approx(100 - VISIBLE_INSET * math.sqrt(2))


def test_degenerate_part_is_left_alone():
    thin = [(0, 0), (1, 0), (1, 1)]
    assert inset_profile([thin]) == [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]]
