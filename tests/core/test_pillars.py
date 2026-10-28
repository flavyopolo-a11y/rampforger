"""Stützen unter Rampen: bis zum Boden, wandern mit, verschwinden beim Ausschalten."""
from rampenschmiede.core.blocks import change_block, insert_block
from rampenschmiede.core.commands import AddObjects, CommandStack
from rampenschmiede.core.model import MapDocument
from rampenschmiede.core.pillars import CONFIG, PILLAR, follow_pillars, set_pillars
from rampenschmiede.core.surf.catalog import Placement
from rampenschmiede.core.templates import starter_room


def _ramp(kind="gerade"):
    doc = MapDocument()
    stack = CommandStack(doc)
    stack.push(AddObjects(starter_room(doc, "css")))
    objs, _ = insert_block(doc, kind, {}, Placement(0, 0, 1024, 0))
    stack.push(AddObjects(objs))
    return doc, stack, objs[0]


def _run(doc, stack, cmd):
    stack.push(cmd)
    f = follow_pillars(doc)
    if f is not None:
        stack.attach(f)


def _pillars(doc, rid):
    return [s for s in doc.children(rid) if PILLAR in s.extra]


def test_pillars_reach_from_floor_to_ramp_and_follow():
    doc, stack, root = _ramp()
    _run(doc, stack, set_pillars(doc, [root.id], True, spacing=512))
    pil = _pillars(doc, root.id)
    assert len(pil) == 2 and all(p.is_valid() for p in pil)
    assert all(p.bbox().mins[2] == 0 for p in pil)  # Boden des Startraums
    ramp_bottom = min(s.bbox().mins[2] for s in doc.children(root.id) if PILLAR not in s.extra)
    assert all(p.bbox().maxs[2] <= ramp_bottom + 1 for p in pil)
    assert follow_pillars(doc) is None
    cmd, _ = change_block(doc, root.id, {}, Placement(256, 0, 1536, 0))
    _run(doc, stack, cmd)
    pil = _pillars(doc, root.id)
    assert len(pil) == 2 and all(p.bbox().maxs[2] > 1500 for p in pil)
    stack.undo()
    assert all(p.bbox().maxs[2] < 1100 for p in _pillars(doc, root.id))


def test_curve_gets_pillars_along_its_path_and_switch_off_removes_them():
    doc, stack, root = _ramp("kurve")
    _run(doc, stack, set_pillars(doc, [root.id], True, spacing=512))
    assert 2 <= len(_pillars(doc, root.id)) <= 8
    _run(doc, stack, set_pillars(doc, [root.id], False))
    assert not _pillars(doc, root.id) and CONFIG not in doc.get(root.id).extra
