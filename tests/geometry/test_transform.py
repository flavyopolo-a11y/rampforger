import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from rampenschmiede.core.geometry import primitives, transform
from rampenschmiede.core.geometry.brush import ray_intersect_solid
from rampenschmiede.core.mathutil import is_integer_point
from rampenschmiede.core.model import Entity, Solid


def block(mins=(0, 0, 0), maxs=(64, 64, 64)):
    return Solid(id=1, faces=primitives.block(mins, maxs)[0])


def test_translate_is_exact():
    s = transform.translate(block(), (16, -32, 8))
    assert s.bbox().mins == (16, -32, 8)
    assert s.bbox().maxs == (80, 32, 72)


def test_translate_rounds_to_integer():
    s = transform.translate(block(), (0.4, 0.6, -0.5))
    assert all(is_integer_point(v) for v in s.vertices())


def test_texture_lock_on_translate_keeps_texture_in_place():
    s = block()
    moved = transform.translate(s, (16, 0, 0))
    top_before = [f for f in s.faces if f.plane.normal[2] > 0.9][0]
    top_after = [f for f in moved.faces if f.plane.normal[2] > 0.9][0]
    p = (10, 10, 64)
    u_before = sum(a * b for a, b in zip(p, top_before.uaxis.vec)) / top_before.uaxis.scale + top_before.uaxis.offset
    p2 = (26, 10, 64)
    u_after = sum(a * b for a, b in zip(p2, top_after.uaxis.vec)) / top_after.uaxis.scale + top_after.uaxis.offset
    assert u_after == pytest.approx(u_before)


@pytest.mark.parametrize("deg", [90, 180, 270, -90])
def test_rotate_90_is_exact(deg):
    s = transform.rotate(block((0, 0, 0), (64, 128, 32)), (0, 0, 0), 2, deg)
    assert s.is_valid()
    assert all(is_integer_point(v) for v in s.vertices())
    size = s.bbox().size
    if deg % 180:
        assert size == (128, 64, 32)
    else:
        assert size == (64, 128, 32)


@settings(max_examples=50, deadline=None)
@given(deg=st.floats(-360, 360, allow_nan=False), axis=st.integers(0, 2))
def test_any_rotation_keeps_plane_points_integer_and_convex(deg, axis):
    s = transform.rotate(block((0, 0, 0), (256, 128, 64)), (128, 64, 32), axis, deg)
    assert s.is_valid()
    for f in s.faces:
        assert f.has_integer_points()
        for v in s.vertices():
            assert f.plane.distance(v) <= 1e-6


def test_scale():
    s = transform.scale_obj(block(), (0, 0, 0), (2, 1, 0.5))
    assert s.bbox().size == (128, 64, 32)


def test_scale_to_zero_is_rejected():
    with pytest.raises(transform.TransformError):
        transform.scale_obj(block(), (0, 0, 0), (0, 1, 1))


def test_mirror_keeps_normals_outwards():
    s = transform.mirror(block((0, 0, 0), (64, 32, 16)), (0, 0, 0), 0)
    assert s.is_valid()
    assert s.bbox().mins == (-64, 0, 0)
    c = s.bbox().center
    for f in s.faces:
        assert f.plane.distance(c) < 0


def test_entity_translate_and_rotate():
    e = Entity(id=5, classname="info_player_counterterrorist", keyvalues=(("origin", "0 0 0"), ("angles", "0 0 0")))
    e2 = transform.translate(e, (64, 0, 0))
    assert e2.origin == (64, 0, 0)
    e3 = transform.rotate(e2, (0, 0, 0), 2, 90)
    assert e3.origin == (0, 64, 0)
    assert e3.get("angles") == "0 90 0"


def test_ray_pick():
    s = block()
    assert ray_intersect_solid(s, (32, 32, 200), (0, 0, -1)) == pytest.approx(136)
    assert ray_intersect_solid(s, (100, 32, 200), (0, 0, -1)) is None
