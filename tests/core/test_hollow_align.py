"""Hohl machen, Ausrichten und Verteilen."""
from rampenschmiede.core.commands import AddObjects
from rampenschmiede.core.cutting import hollow
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.mathutil import BBox
from rampenschmiede.core.model import EditorInfo, MapDocument, Solid
from rampenschmiede.core.organize import align, distribute


def _box(doc, lo, hi, group=None):
    s = Solid(id=doc.new_id(), faces=primitives.block(lo, hi)[0], editor=EditorInfo(group_id=group))
    AddObjects([s]).do(doc)
    return s


def _volume(doc, ids):
    total = 0.0
    for i in ids:
        b = doc.get(i).bbox()
        total += (b.maxs[0] - b.mins[0]) * (b.maxs[1] - b.mins[1]) * (b.maxs[2] - b.mins[2])
    return total


def test_hollow_inward_keeps_outer_size():
    doc = MapDocument()
    s = _box(doc, (0, 0, 0), (256, 256, 128))
    cmd, ids = hollow(doc, [s.id], 16)
    cmd.do(doc)
    assert len(ids) == 6 and s.id in ids  # erstes Stück behält die ID
    union = BBox.union(doc.get(i).bbox() for i in ids)
    assert union.mins == (0, 0, 0) and union.maxs == (256, 256, 128)
    assert _volume(doc, ids) == 256 * 256 * 128 - 224 * 224 * 96  # Wände überlappen nicht


def test_hollow_outward_and_too_thin():
    doc = MapDocument()
    s = _box(doc, (0, 0, 0), (128, 128, 128))
    cmd, ids = hollow(doc, [s.id], -16)
    cmd.do(doc)
    union = BBox.union(doc.get(i).bbox() for i in ids)
    assert union.mins == (-16, -16, -16) and union.maxs == (144, 144, 144)
    thin = _box(doc, (0, 0, 500), (128, 128, 520))
    assert hollow(doc, [thin.id], 16) == (None, [])


def test_align_min_max_center():
    doc = MapDocument()
    a = _box(doc, (0, 0, 0), (64, 64, 64))
    b = _box(doc, (200, 100, 0), (232, 132, 32))
    align(doc, [a, b], 0, "max").do(doc)
    assert doc.get(a.id).bbox().maxs[0] == 232 and doc.get(b.id).bbox().maxs[0] == 232
    align(doc, [doc.get(a.id), doc.get(b.id)], 2, "mitte").do(doc)
    assert doc.get(a.id).bbox().center[2] == doc.get(b.id).bbox().center[2]
    assert align(doc, [doc.get(a.id)], 0, "min") is None


def test_distribute_equal_gaps_and_groups_move_together():
    doc = MapDocument()
    a = _box(doc, (0, 0, 0), (64, 64, 64))
    b1 = _box(doc, (100, 0, 0), (132, 64, 64), group=7)
    b2 = _box(doc, (132, 0, 0), (164, 64, 64), group=7)
    c = _box(doc, (1000, 0, 0), (1064, 64, 64))
    distribute(doc, [a, b1, b2, c], 0).do(doc)
    xs = sorted((doc.get(i).bbox().mins[0], doc.get(i).bbox().maxs[0]) for i in (a.id, b1.id, b2.id, c.id))
    # Gruppe (64 breit) liegt mittig: Lücken links und rechts gleich
    g_lo, g_hi = xs[1][0], xs[2][1]
    assert g_lo - 64 == 1000 - g_hi
    assert doc.get(b2.id).bbox().mins[0] - doc.get(b1.id).bbox().mins[0] == 32
