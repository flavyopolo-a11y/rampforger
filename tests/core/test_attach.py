"""Zonen sitzen auf ihrem Block und folgen ihm."""
from rampenschmiede.core.attach import SITS_ON, fit_on, follow_supports, support_below
from rampenschmiede.core.blocks import change_block, is_block_root
from rampenschmiede.core.commands import AddObjects, CommandStack, RemoveObjects, ReplaceObjects
from rampenschmiede.core.geometry import transform
from rampenschmiede.core.mathutil import BBox
from rampenschmiede.core.model import MapDocument
from rampenschmiede.core.templates import starter_room
from rampenschmiede.core.templates.starter import START_BLOCK


def _room():
    doc = MapDocument()
    stack = CommandStack(doc)
    stack.push(AddObjects(starter_room(doc, "css")))
    zone = next(e for e in doc.entities() if e.get("targetname") == "mod_zone_start")
    block = doc.get(zone.extra[SITS_ON]["id"])
    return doc, stack, zone, block


def _run(doc, stack, cmd):
    stack.push(cmd)
    follow = follow_supports(doc)
    if follow is not None:
        stack.attach(follow)


def test_fit_on_top_with_margin_and_yaw():
    values, at = fit_on(BBox((0, 0, 0), (512, 256, 32)))
    assert values == {"laenge": 480, "breite": 224} and (at.x, at.y, at.z) == (16, 128, 32)
    values, at = fit_on(BBox((0, 0, 0), (512, 256, 32)), yaw=90)
    assert values == {"laenge": 224, "breite": 480} and (at.x, at.y) == (256, 16)


def test_start_zone_sits_on_start_block():
    doc, _, zone, block = _room()
    zb, bb = doc.bbox([zone.id]), block.bbox()
    assert zb.mins[2] == bb.maxs[2]
    assert bb.mins[0] < zb.mins[0] and zb.maxs[0] < bb.maxs[0]
    assert bb.size[0] == START_BLOCK
    assert follow_supports(doc) is None


def test_zone_follows_moved_and_resized_block_in_one_undo_step():
    doc, stack, zone, block = _room()
    before = doc.bbox([zone.id])
    moved = transform.translate(block, (256, 128, 64))
    _run(doc, stack, ReplaceObjects([moved]))
    after = doc.bbox([zone.id])
    assert after.mins[0] == before.mins[0] + 256 and after.mins[2] == before.mins[2] + 64
    assert follow_supports(doc) is None  # einmal angepasst, dann Ruhe
    assert is_block_root(doc.get(zone.id)) and SITS_ON in doc.get(zone.id).extra
    stack.undo()
    assert doc.bbox([zone.id]) == before


def test_regulator_change_keeps_the_link():
    doc, stack, zone, _ = _room()
    cmd, _gen = change_block(doc, zone.id, {"hoehe": 256})
    _run(doc, stack, cmd)
    assert SITS_ON in doc.get(zone.id).extra


def test_deleting_block_frees_the_zone():
    doc, stack, zone, block = _room()
    _run(doc, stack, RemoveObjects([block.id]))
    assert zone.id in doc and SITS_ON not in doc.get(zone.id).extra


def test_support_below_ignores_huge_floor_and_triggers():
    doc, _, zone, block = _room()
    c = block.bbox().center
    assert support_below(doc, c[0], c[1], 40) == block.id
    assert support_below(doc, 3000, 3000, 10) is None
