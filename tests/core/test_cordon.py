from rampenschmiede.core.cordon import (
    active_cordon,
    apply_cordon,
    get_cordon,
    set_active,
    set_cordon,
)
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.mathutil import BBox
from rampenschmiede.core.model import Entity, MapDocument, Solid
from rampenschmiede.core.validation.seal import check_seal


def _brush(doc, lo, hi, parent=None):
    s = Solid(id=doc.new_id(), faces=primitives.block(lo, hi)[0], parent_id=parent)
    doc._insert([s])
    return s


def _map():
    doc = MapDocument()
    inside = _brush(doc, (0, 0, 0), (256, 256, 16))
    outside = _brush(doc, (4000, 0, 0), (4256, 256, 16))
    across = _brush(doc, (900, 0, 0), (1200, 64, 16))
    spawn = Entity(id=doc.new_id(), classname="info_player_terrorist", keyvalues=(("origin", "64 64 40"),))
    far = Entity(id=doc.new_id(), classname="info_player_counterterrorist", keyvalues=(("origin", "4100 64 40"),))
    trig = Entity(id=doc.new_id(), classname="trigger_teleport")
    logic = Entity(id=doc.new_id(), classname="logic_auto")
    doc._insert([spawn, far, trig, logic])
    trig_brush = _brush(doc, (3900, 0, 0), (3964, 64, 64), parent=trig.id)
    return doc, dict(inside=inside, outside=outside, across=across, spawn=spawn, far=far, trig=trig,
                     logic=logic, trig_brush=trig_brush)


def test_cordon_is_stored_and_toggled():
    doc = MapDocument()
    assert get_cordon(doc) == (None, False)
    set_cordon(doc, BBox((10, 0, 0), (-100, 500, 3)))
    box, on = get_cordon(doc)
    assert on and box.mins == (-100, 0, -31) and box.maxs == (10, 500, 33)  # sortiert, mind. 64 hoch
    assert set_active(doc, False) and active_cordon(doc) is None
    set_cordon(doc, None)
    assert get_cordon(doc) == (None, False) and not set_active(doc, True)


def test_apply_cordon_keeps_only_the_area_and_seals_it():
    doc, o = _map()
    res = apply_cordon(doc, BBox((-64, -64, -64), (1000, 1000, 512)))
    ids = {x.id for x in res.doc.objects()}
    assert {o["inside"].id, o["across"].id, o["spawn"].id, o["logic"].id} <= ids
    assert not ids & {o["outside"].id, o["far"].id, o["trig"].id, o["trig_brush"].id}
    assert res.dropped == 4 and res.spawns == 1
    assert len(ids) == 4 + 6  # plus Hülle
    assert check_seal(res.doc).sealed
    # Die Map selbst bleibt unverändert
    assert len(doc) == 8 and o["outside"].id in doc
