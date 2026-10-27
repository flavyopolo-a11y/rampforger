"""Schneiden, Aushöhlen und Löcher."""
from rampenschmiede.core.blocks import build_block
from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.cutting import carve_with, clip, hole
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.geometry.csg import carve, split
from rampenschmiede.core.model import MapDocument, Solid


def _box(mins, maxs, material="WAND/A"):
    return primitives.block(mins, maxs, material)[0]


def _doc(*boxes):
    doc = MapDocument()
    stack = CommandStack(doc)
    solids = solids_from_faces(doc, [_box(*b) for b in boxes])
    stack.push(AddObjects(solids))
    return doc, stack, solids


def _bbox(solid):
    bb = solid.bbox()
    return (tuple(bb.mins), tuple(bb.maxs))


def _volume(solid):
    bb = solid.bbox()
    return (bb.maxs[0] - bb.mins[0]) * (bb.maxs[1] - bb.mins[1]) * (bb.maxs[2] - bb.mins[2])


def test_split_box_in_two():
    faces = _box((0, 0, 0), (128, 64, 64))
    back, front = split(faces, ((32, 0, 0), (32, 64, 0), (32, 0, 64)))
    assert back is not None and front is not None
    sizes = sorted(_bbox(Solid(id=1, faces=f)) for f in (back, front))
    assert sizes == [((0, 0, 0), (32, 64, 64)), ((32, 0, 0), (128, 64, 64))]
    for f in (back, front):
        s = Solid(id=1, faces=f)
        assert s.is_valid() and len(f) == 6
        assert all(c == int(c) for p in s.vertices() for c in p)
        assert all(face.material == "WAND/A" for face in f)


def test_split_outside_returns_none():
    faces = _box((0, 0, 0), (64, 64, 64))
    back, front = split(faces, ((200, 0, 0), (200, 64, 0), (200, 0, 64)))
    assert (back is None) != (front is None)


def test_diagonal_split_makes_wedges():
    faces = _box((0, 0, 0), (64, 64, 64))
    back, front = split(faces, ((0, 0, 0), (64, 64, 0), (0, 0, 64)))
    assert back is not None and front is not None
    assert len(back) == 5 and len(front) == 5
    assert Solid(id=1, faces=back).is_valid() and Solid(id=2, faces=front).is_valid()


def test_carve_window_into_wall():
    wall = _box((0, 0, 0), (256, 16, 256))
    cutter = _box((64, -32, 64), (192, 48, 192))
    pieces = carve(wall, cutter)
    assert pieces is not None and len(pieces) == 4
    solids = [Solid(id=i, faces=p) for i, p in enumerate(pieces)]
    assert all(s.is_valid() for s in solids)
    assert sum(_volume(s) for s in solids) == 256 * 16 * 256 - 128 * 16 * 128
    assert carve(wall, _box((0, 100, 0), (64, 164, 64))) is None
    assert carve(_box((80, 0, 80), (100, 16, 100)), cutter) == []


def test_clip_objects_and_undo():
    doc, stack, (a, b) = _doc(((0, 0, 0), (128, 128, 64)), ((512, 0, 0), (640, 128, 64)))
    cmd, ids = clip(doc, [a.id, b.id], ((64, 0, 0), (64, 0, 64), (64, 128, 0)), keep="both")
    stack.push(cmd)
    assert len(ids) == 2 and a.id in ids and doc.get(b.id) == b
    stack.undo()
    assert doc.get(a.id) == a
    cmd, ids = clip(doc, [a.id], ((64, 0, 0), (64, 0, 64), (64, 128, 0)), keep="back")
    stack.push(cmd)
    assert ids == [a.id] and _volume(doc.get(a.id)) == 64 * 128 * 64


def test_carve_with_selection_keeps_cutter():
    doc, stack, (wall, cutter) = _doc(((0, 0, 0), (256, 16, 256)), ((64, -32, 64), (192, 48, 192)))
    cmd, ids = carve_with(doc, [cutter.id])
    stack.push(cmd)
    assert len(ids) == 4 and doc.get(cutter.id) == cutter
    assert sum(_volume(doc.get(i)) for i in ids) == 256 * 16 * 256 - 128 * 16 * 128


def test_hole_through_selected_block():
    doc, stack, (wall,) = _doc(((0, 0, 0), (256, 16, 256)))
    # Ansicht „Vorne“: waagerecht X? nein: Vorne ist Y/Z, Blickachse X. Hier Seite: X/Z, Blick Y
    cmd, ids = hole(doc, [wall.id], (0, 2, 1), (96, 96, 160, 192))
    stack.push(cmd)
    assert len(ids) == 4
    assert sum(_volume(doc.get(i)) for i in ids) == 256 * 16 * 256 - 64 * 16 * 96


def test_blocks_are_not_cut():
    doc = MapDocument()
    stack = CommandStack(doc)
    objs, _ = build_block(doc, "gerade", {"laenge": 256})
    stack.push(AddObjects(objs))
    cmd, _ = clip(doc, [objs[0].id], ((0, 0, 0), (0, 0, 64), (0, 128, 0)))
    assert cmd is None
