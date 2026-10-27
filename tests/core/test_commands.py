from rampenschmiede.core.commands import (
    AddObjects,
    CommandStack,
    MacroCommand,
    RemoveObjects,
    ReplaceObjects,
    solids_from_faces,
)
from rampenschmiede.core.geometry import primitives, transform
from rampenschmiede.core.io import rsmap
from rampenschmiede.core.model import ChangeSet, Entity, MapDocument

from ..helpers import doc_with_block


def snapshot(doc):
    return rsmap.to_dict(doc)["objects"]


def test_add_undo_redo():
    doc, stack, s = doc_with_block()
    assert len(doc) == 1
    stack.undo()
    assert len(doc) == 0
    stack.redo()
    assert doc.get(s.id) == s


def test_fifty_steps_undo_and_redo_restore_state():
    doc = MapDocument()
    stack = CommandStack(doc)
    states = [snapshot(doc)]
    for i in range(50):
        if i % 3 == 2 and len(doc):
            obj = next(doc.solids())
            stack.push(ReplaceObjects([transform.translate(obj, (16, 0, 0))], "Verschieben"))
        elif i % 7 == 6 and len(doc):
            stack.push(RemoveObjects([next(doc.solids()).id]))
        else:
            solids = solids_from_faces(doc, primitives.block((i * 64, 0, 0), (i * 64 + 32, 32, 32)))
            stack.push(AddObjects(solids))
        states.append(snapshot(doc))
    assert len(stack) == 50
    for i in range(50, 0, -1):
        assert snapshot(doc) == states[i]
        stack.undo()
    assert snapshot(doc) == states[0]
    for i in range(1, 51):
        stack.redo()
        assert snapshot(doc) == states[i]


def test_drag_merges_into_one_step():
    doc, stack, s = doc_with_block()
    key = object()
    cur = s
    for _ in range(10):
        cur = transform.translate(cur, (1, 0, 0))
        stack.push(ReplaceObjects([cur], "Verschieben", merge_key=key))
    assert len(stack) == 2
    assert doc.get(s.id).bbox().mins == (10, 0, 0)
    stack.undo()
    assert doc.get(s.id).bbox().mins == (0, 0, 0)


def test_end_merge_starts_new_step():
    doc, stack, s = doc_with_block()
    key = "drag"
    stack.push(ReplaceObjects([transform.translate(s, (1, 0, 0))], merge_key=key))
    stack.end_merge()
    stack.push(ReplaceObjects([transform.translate(doc.get(s.id), (1, 0, 0))], merge_key=key))
    assert len(stack) == 3


def test_remove_entity_removes_its_brushes():
    doc = MapDocument()
    stack = CommandStack(doc)
    ent = Entity(id=doc.new_id(), classname="func_detail")
    brushes = solids_from_faces(doc, primitives.block((0, 0, 0), (32, 32, 32)), parent_id=ent.id)
    stack.push(AddObjects([ent, *brushes]))
    stack.push(RemoveObjects([ent.id]))
    assert len(doc) == 0
    stack.undo()
    assert len(doc) == 2


def test_macro_is_one_step():
    doc = MapDocument()
    stack = CommandStack(doc)
    parts = solids_from_faces(doc, primitives.stairs((0, 0, 0), (64, 128, 64), steps=4))
    stack.push(MacroCommand([AddObjects([p]) for p in parts], "Treppe"))
    assert len(stack) == 1 and len(doc) == 4
    stack.undo()
    assert len(doc) == 0


def test_listeners_get_changesets():
    doc = MapDocument()
    stack = CommandStack(doc)
    seen: list[ChangeSet] = []
    doc.subscribe(seen.append)
    solids = solids_from_faces(doc, primitives.block((0, 0, 0), (8, 8, 8)))
    stack.push(AddObjects(solids))
    stack.undo()
    assert seen[0].added == {solids[0].id}
    assert seen[1].removed == {solids[0].id}


def test_clean_state():
    doc, stack, s = doc_with_block()
    stack.set_clean()
    assert stack.is_clean()
    stack.push(ReplaceObjects([transform.translate(s, (8, 0, 0))]))
    assert not stack.is_clean()
    stack.undo()
    assert stack.is_clean()
