import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.geometry.brush import polygon_area
from rampenschmiede.core.mathutil import is_integer_point
from rampenschmiede.core.model import Solid


def make(faces):
    return Solid(id=1, faces=faces)


def check_solid(faces):
    s = make(faces)
    assert s.is_valid(), "Brush muss gültig sein"
    for v in s.vertices():
        assert is_integer_point(v), f"Vertex {v} nicht ganzzahlig"
    for f in faces:
        assert f.has_integer_points()
    # Konvex: jeder Vertex liegt hinter oder auf jeder Ebene
    for f in s.faces:
        for v in s.vertices():
            assert f.plane.distance(v) <= 1e-6
    return s


def test_block_has_six_faces_and_eight_vertices():
    (faces,) = primitives.block((0, 0, 0), (64, 128, 32))
    s = check_solid(faces)
    assert len(s.faces) == 6
    assert len(s.vertices()) == 8
    assert s.bbox().mins == (0, 0, 0) and s.bbox().maxs == (64, 128, 32)


def test_block_normals_point_outwards():
    (faces,) = primitives.block((0, 0, 0), (64, 64, 64))
    s = make(faces)
    center = (32, 32, 32)
    for f in s.faces:
        assert f.plane.distance(center) < 0


def test_known_vmf_top_face_orientation():
    # Oberseite eines 128er-Würfels, wie Hammer sie schreibt: Normale +Z
    from rampenschmiede.core.mathutil import Plane
    p = Plane.from_vmf_points((-64, 64, 64), (64, 64, 64), (64, -64, 64))
    assert p.normal == pytest.approx((0, 0, 1))
    assert p.dist == pytest.approx(64)


def test_wedge():
    (faces,) = primitives.wedge((0, 0, 0), (64, 128, 64))
    s = check_solid(faces)
    assert len(s.faces) == 5
    assert len(s.vertices()) == 6


@pytest.mark.parametrize("sides", [3, 4, 6, 8, 12, 16, 32])
def test_cylinder(sides):
    (faces,) = primitives.cylinder((0, 0, 0), (256, 256, 64), sides)
    s = check_solid(faces)
    assert len(s.faces) == sides + 2


def test_small_cylinder_stays_valid_after_rounding():
    # Sehr klein mit vielen Seiten: Rundung legt Punkte zusammen, Hülle bleibt konvex.
    (faces,) = primitives.cylinder((0, 0, 0), (8, 8, 8), 32)
    check_solid(faces)


def test_arch_segments():
    parts = primitives.arch((0, 0, 0), (512, 512, 64), sides=8, wall=32, arc_deg=180)
    assert len(parts) == 8
    for faces in parts:
        check_solid(faces)


def test_stairs():
    parts = primitives.stairs((0, 0, 0), (64, 160, 80), steps=5, direction="+y")
    assert len(parts) == 5
    tops = []
    for faces in parts:
        s = check_solid(faces)
        tops.append(s.bbox().maxs[2])
    assert tops == [16, 32, 48, 64, 80]


@settings(max_examples=60, deadline=None)
@given(
    x=st.integers(-2048, 2048), y=st.integers(-2048, 2048), z=st.integers(-2048, 2048),
    w=st.integers(8, 1024), d=st.integers(8, 1024), h=st.integers(8, 1024),
    sides=st.integers(3, 24),
)
def test_random_cylinders_are_valid(x, y, z, w, d, h, sides):
    (faces,) = primitives.cylinder((x, y, z), (x + w, y + d, z + h), sides)
    check_solid(faces)


def test_polygon_area():
    assert polygon_area([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)]) == pytest.approx(4)
