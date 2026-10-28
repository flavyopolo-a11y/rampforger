"""Gruppen, An Entity binden, Zur Welt, Mehrfach kopieren, Auswahl ans Raster."""
import pytest

from rampenschmiede.core import organize
from rampenschmiede.core.blocks import insert_block, is_block_root
from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.io import vmf
from rampenschmiede.core.model import Entity, MapDocument
from rampenschmiede.core.surf.catalog import CATALOG

TEMPLATE = next(iter(CATALOG))


def _doc(n=2):
    doc = MapDocument()
    stack = CommandStack(doc)
    solids = solids_from_faces(doc, [fs for i in range(n) for fs in primitives.block((i * 128, 0, 0), (i * 128 + 64, 64, 64))])
    stack.push(AddObjects(solids))
    return doc, stack, solids


def test_group_and_expand_and_ungroup():
    doc, stack, (a, b, c) = _doc(3)
    cmd, gid = organize.group(doc, [a, b])
    stack.push(cmd)
    assert doc.get(a.id).editor.group_id == gid == doc.get(b.id).editor.group_id
    assert organize.expand_groups(doc, [a.id]) == {a.id, b.id}
    assert organize.expand_groups(doc, [c.id]) == {c.id}
    assert organize.group(doc, [c]) is None
    stack.push(organize.ungroup(doc, [doc.get(a.id)]))
    assert doc.get(b.id).editor.group_id is None
    stack.undo()
    assert doc.get(b.id).editor.group_id == gid


def test_tie_to_trigger_and_back_to_world():
    doc, stack, (a, b) = _doc(2)
    cmd, eid = organize.tie_to_entity(doc, [a, b], "trigger_teleport")
    stack.push(cmd)
    ent = doc.get(eid)
    assert isinstance(ent, Entity) and ent.classname == "trigger_teleport"
    assert ent.get("spawnflags") == "1"
    kids = doc.children(eid)
    assert {k.id for k in kids} == {a.id, b.id}
    assert all(f.material == organize.TRIGGER for k in kids for f in k.faces)
    # Ein Brush zurück zur Welt: Entity bleibt mit dem anderen
    cmd, ids = organize.move_to_world(doc, [doc.get(a.id)])
    stack.push(cmd)
    assert doc.get(a.id).parent_id is None and eid in doc
    # Der letzte auch: leere Entity verschwindet
    stack.push(organize.move_to_world(doc, [doc.get(eid)])[0])
    assert eid not in doc and doc.get(b.id).parent_id is None
    stack.undo()
    stack.undo()
    stack.undo()
    assert eid not in doc and doc.get(a.id).faces == a.faces


def test_retie_removes_emptied_entity():
    doc, stack, (a, b) = _doc(2)
    cmd, first = organize.tie_to_entity(doc, [a, b], "func_detail")
    stack.push(cmd)
    cmd, second = organize.tie_to_entity(doc, [doc.get(first)], "func_illusionary")
    stack.push(cmd)
    assert first not in doc
    assert {k.id for k in doc.children(second)} == {a.id, b.id}


def test_blocks_must_be_dissolved_first():
    doc = MapDocument()
    stack = CommandStack(doc)
    objs, _gen = insert_block(doc, TEMPLATE)
    stack.push(AddObjects(objs))
    root = next(o for o in objs if is_block_root(o))
    with pytest.raises(organize.OrganizeError):
        organize.tie_to_entity(doc, [root], "func_detail")
    member = next(o for o in objs if o is not root and o.extra.get("block_of") == root.id)
    with pytest.raises(organize.OrganizeError):
        organize.move_to_world(doc, [member])


def test_multi_copy_staircase_is_one_undo_step():
    doc, stack, (a,) = _doc(1)
    cmd, ids = organize.multi_copy(doc, [a], 4, (64, 0, 16), (0, 0, 15), make_group=True)
    stack.push(cmd)
    assert len(ids) == 4 and all(i in doc for i in ids)
    top = doc.get(ids[-1])
    assert doc.bbox([ids[-1]]).mins[2] == pytest.approx(64)
    assert len({doc.get(i).editor.group_id for i in ids}) == 1
    assert top.is_valid()
    stack.undo()
    assert not any(i in doc for i in ids)
    stack.redo()
    assert all(i in doc for i in ids)


def test_multi_copy_keeps_brush_entities_together():
    doc, stack, (a,) = _doc(1)
    cmd, eid = organize.tie_to_entity(doc, [a], "func_wall")
    stack.push(cmd)
    cmd, ids = organize.multi_copy(doc, [doc.get(eid)], 2, (0, 128, 0))
    stack.push(cmd)
    assert all(isinstance(doc.get(i), Entity) and len(doc.children(i)) == 1 for i in ids)


def test_snap_delta():
    assert organize.snap_delta((3, -5, 64), 16) == (-3, 5, 0)


def test_new_groups_get_vmf_group_blocks():
    doc, stack, (a, b) = _doc(2)
    cmd, gid = organize.group(doc, [a, b])
    stack.push(cmd)
    text = vmf.export_vmf(doc).text
    assert "\tgroup\n" in text
    back, _ = vmf.parse_vmf(text)
    groups = {s.editor.group_id for s in back.solids()}
    assert len(groups) == 1 and None not in groups
    # Wieder exportiert: genau ein group-Block
    assert vmf.export_vmf(back).text.count("\tgroup\n") == 1
