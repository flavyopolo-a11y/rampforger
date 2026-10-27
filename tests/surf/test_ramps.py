"""Rampen-Bibliothek: Geometrie-Regeln gegen Rampbugs."""
import math

import pytest

from rampenschmiede.core.model import Solid
from rampenschmiede.core.surf.catalog import CATALOG, Param, Placement, generate, ramp_height
from rampenschmiede.core.surf.sweep import NODRAW, Sweep, arc_joints, lattice_dir

PLACEMENTS = [Placement(), Placement(100, -37, 64, 33), Placement(5, 7, 0, 141.3), Placement(0, 0, 0, 270)]


def solids(gen):
    return [Solid(i, faces) for i, faces in enumerate(gen.face_sets)]


@pytest.mark.parametrize("key", sorted(CATALOG))
def test_every_template_builds_valid_integer_brushes(key):
    for at in PLACEMENTS:
        gen = generate(key, None, at)
        assert gen.face_sets, key
        for s in solids(gen):
            assert s.is_valid(), (key, at)
            for p in s.vertices():
                assert all(float(c).is_integer() for c in p), (key, at, p)
            for f in s.faces:
                assert f.has_integer_points()


@pytest.mark.parametrize("key", sorted(k for k, t in CATALOG.items() if t.check_angles))
def test_defaults_are_surfable(key):
    gen = generate(key)
    assert gen.warnings == []
    lo, hi = gen.angle_range
    assert 45 < lo <= hi < 65


def test_straight_double_ramp_has_requested_angle_and_flat_base():
    gen = generate("gerade", {"breite": 960, "winkel": 50, "lippe": 32})
    lo, hi = gen.angle_range
    assert abs(lo - 50) < 0.1 and abs(hi - 50) < 0.1
    (s,) = solids(gen)
    bottom = [f for f, poly in zip(s.faces, s.polygons()) if all(p[2] == 0 for p in poly)]
    assert len(bottom) == 1 and bottom[0].material == NODRAW
    assert s.bbox().maxs[2] == round(ramp_height({"breite": 960, "winkel": 50, "lippe": 32, "profil": "voll", "oben": 0}))


def test_rotated_straight_ramp_stays_an_exact_prism():
    # Gerade Rampen haben in jeder Richtung 7 Seiten: keine geknickten Flächen durchs Runden
    for at in PLACEMENTS:
        (s,) = solids(generate("gerade", None, at))
        assert len(s.faces) == 7


def test_curve_steps_stay_between_two_and_five_degrees():
    joints = arc_joints(1536, 90, segment_length=1e9, max_step=2.5)
    steps = [b.yaw - a.yaw for a, b in zip(joints, joints[1:])]
    assert all(abs(s - 2.5) < 1e-9 for s in steps)
    coarse = arc_joints(1536, 90, segment_length=96, max_step=5)
    assert all(0 < b.yaw - a.yaw <= 5 for a, b in zip(coarse, coarse[1:]))


def test_curve_segments_share_seam_points_exactly():
    v = CATALOG["kurve"].values()
    from rampenschmiede.core.surf.catalog import profile_from

    sweep = Sweep(arc_joints(v["radius"], 90, 1e9, 2.5, 13, -7, 0, 20), profile_from(v))
    pieces = sweep.build()
    assert len(pieces) == 36
    for k in range(len(pieces) - 1):
        a, b = Solid(1, pieces[k].faces), Solid(2, pieces[k + 1].faces)
        seam = set(a.vertices()) & set(b.vertices())
        ring = {tuple(float(c) for c in p) for p in sweep.joint_points(k + 1)[0]}
        assert seam == ring


def test_inner_seams_are_nodraw_and_ends_are_visible():
    gen = generate("kurve")
    first, last = solids(gen)[0], solids(gen)[-1]
    caps_first = [f.material for f in first.faces if abs(f.plane.normal[2]) < 1e-9 and f.material != "DEV/DEV_MEASUREGENERIC01"]
    assert NODRAW in caps_first  # Naht zum nächsten Segment
    assert any(f.material == "DEV/DEV_MEASUREGENERIC01" for f in last.faces)


def test_touching_profile_parts_hide_shared_faces():
    gen = generate("halfpipe", {"teile": 6})
    hidden = sum(f.material == NODRAW for faces in gen.face_sets for f in faces)
    # Zwischen 6 Teilen liegen 5 Fugen mit je zwei Seiten
    assert hidden >= 10


def test_flat_ramp_warns():
    gen = generate("gerade", {"winkel": 30})
    assert any("Zu flach" in w for w in gen.warnings)
    gen = generate("gerade", {"winkel": 75})
    assert any("steil" in w for w in gen.warnings)


def test_param_clean():
    p = Param("x", "X", 10, 0, 100, 1)
    assert p.clean(500) == 100 and p.clean("abc") == 10 and p.clean(3.6) == 4
    c = Param("c", "C", "a", choices=(("a", "A"), ("b", "B")))
    assert c.clean("b") == "b" and c.clean("z") == "a"
    assert CATALOG["halb"].values()["profil"] == "halb"


def test_lattice_dir_is_close_and_primitive():
    assert lattice_dir(359) is None  # zu nah an 0°, ohne zu langen Vektor nicht exakt genug
    for yaw in (0, 33, 45, 90, 141.3, 270):
        p, q = lattice_dir(yaw)
        assert math.gcd(p, q) == 1
        err = (math.degrees(math.atan2(q, p)) - yaw + 180) % 360 - 180
        assert abs(err) <= 0.25
