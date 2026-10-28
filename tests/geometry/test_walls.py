"""Wände aus einem Linienzug: verbunden, gültig, Gehrung an den Ecken."""
from rampenschmiede.core.commands import solids_from_faces
from rampenschmiede.core.geometry.walls import clean_points, wall_faces, wall_outlines
from rampenschmiede.core.model import MapDocument


def _solids(pts, closed=False):
    doc = MapDocument()
    return solids_from_faces(doc, wall_faces(pts, 16, 0, 256, closed))


def test_l_shape_meets_in_a_miter_without_gap():
    a, b = wall_outlines([(0, 0), (512, 0), (512, 512)], 16)
    # gemeinsame Gehrungskante
    assert a[1] == b[0] and a[2] == b[3]
    solids = _solids([(0, 0), (512, 0), (512, 512)])
    assert len(solids) == 2 and all(s.is_valid() for s in solids)


def test_closed_room_has_four_valid_walls():
    solids = _solids([(0, 0), (512, 0), (512, 512), (0, 512), (0, 0)], closed=True)
    assert len(solids) == 4 and all(s.is_valid() for s in solids)
    z = {round(c) for s in solids for c in (s.bbox().mins[2], s.bbox().maxs[2])}
    assert z == {0, 256}


def test_diagonal_and_sharp_corners_stay_valid():
    for pts in ([(0, 0), (300, 100), (0, 180)], [(0, 0), (500, 0), (10, 30)], [(0, 0), (64, 0)]):
        solids = _solids(pts)
        assert solids and all(s.is_valid() for s in solids)


def test_clean_points_drops_duplicates():
    assert clean_points([(0, 0), (0, 0), (5, 0), (0, 0)], closed=True) == [(0.0, 0.0), (5.0, 0.0)]
