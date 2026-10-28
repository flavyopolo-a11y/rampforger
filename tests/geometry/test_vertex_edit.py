"""Ecken verschieben: Brush bleibt konvex und ganzzahlig, Texturen bleiben liegen."""
import random

import pytest

from rampenschmiede.core.commands import AddObjects, CommandStack, Deferred, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.geometry.vertex_edit import (
    VertexError,
    edges,
    move_selected,
    move_vertices,
    vertices,
)
from rampenschmiede.core.model import MapDocument
from rampenschmiede.core.surf import hull


def _cube(size=64, material="DEV/DEV_MEASUREGENERIC01B"):
    doc = MapDocument()
    return solids_from_faces(doc, primitives.block((0, 0, 0), (size, size, size), material))[0]


def test_cube_has_8_vertices_and_12_edges():
    s = _cube()
    assert len(vertices(s)) == 8
    assert len(edges(s)) == 12


def test_raise_top_edge_makes_a_roof_shape():
    s = _cube()
    edge = [(0, 0, 64), (64, 0, 64)]
    moved = move_selected(s, edge, (0, 0, 32))
    assert moved.is_valid()
    assert {(0, 0, 96), (64, 0, 96)} <= set(vertices(moved))
    assert len(moved.faces) == 6
    assert all(f.material == "DEV/DEV_MEASUREGENERIC01B" for f in moved.faces)


def test_merging_two_corners_gives_a_wedge():
    s = _cube()
    moved = move_vertices(s, {(64, 0, 64): (0, 0, 64), (64, 64, 64): (0, 64, 64)})
    assert moved.is_valid()
    assert len(vertices(moved)) == 6
    assert len(moved.faces) == 5


def test_concave_move_is_rejected():
    s = _cube()
    with pytest.raises(VertexError):
        move_vertices(s, {(64, 64, 64): (32, 32, 32)})


def test_flat_brush_is_rejected():
    s = _cube()
    top = [v for v in vertices(s) if v[2] == 64]
    with pytest.raises(VertexError):
        move_selected(s, top, (0, 0, -64))


def test_untouched_faces_keep_their_texture_axes():
    s = _cube()
    bottom = next(f for f in s.faces if f.plane.normal[2] < -0.5)
    moved = move_selected(s, [(0, 0, 64)], (0, 0, 16))
    new_bottom = next(f for f in moved.faces if f.plane.normal[2] < -0.5)
    assert new_bottom.uaxis == bottom.uaxis and new_bottom.vaxis == bottom.vaxis


def test_numpy_hull_matches_python_hull():
    rnd = random.Random(7)
    for _ in range(3):
        pts = list({(rnd.randint(-64, 64), rnd.randint(-64, 64), rnd.randint(-64, 64)) for _ in range(40)})
        fast = hull._hull_planes_np(pts)
        old = hull._VECTOR_FROM
        try:
            hull._VECTOR_FROM = 10_000
            slow = hull.hull_planes(pts)
        finally:
            hull._VECTOR_FROM = old
        assert sorted((n, d, sorted(on)) for n, d, on in fast) == sorted((n, d, sorted(on)) for n, d, on in slow)


@pytest.mark.parametrize("make", [
    lambda: primitives.spike((0, 0, 0), (128, 128, 256), sides=6),
    lambda: primitives.sphere((0, 0, 0), (256, 256, 256), sides=8),
    lambda: primitives.sphere((0, 0, 0), (256, 256, 256), sides=40),
])
def test_new_shapes_are_single_valid_brushes(make):
    doc = MapDocument()
    solids = solids_from_faces(doc, make())
    assert len(solids) == 1
    assert solids[0].is_valid()
    assert len(solids[0].faces) <= 128  # vbsp-Grenze


def test_torus_is_a_ring_of_valid_brushes():
    doc = MapDocument()
    solids = solids_from_faces(doc, primitives.torus((0, 0, 0), (512, 512, 64), sides=12, wall=48))
    assert len(solids) == 12
    assert all(s.is_valid() for s in solids)


def test_deferred_builds_once_and_undoes_in_reverse():
    doc = MapDocument()
    stack = CommandStack(doc)
    calls = []
    s = solids_from_faces(doc, primitives.block((0, 0, 0), (16, 16, 16)))[0]

    def step(_doc):
        calls.append(1)
        return AddObjects([s])

    stack.push(Deferred([step], "Test"))
    assert s.id in doc and len(calls) == 1
    stack.undo()
    assert s.id not in doc
    stack.redo()
    assert s.id in doc and len(calls) == 1
