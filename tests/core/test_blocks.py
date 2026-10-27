"""Bausteine: Regler ändern, Undo, Transformationen, Kopieren, Speichern."""
from rampenschmiede.core.blocks import (
    MEMBER_KEY,
    PLAYERCLIP,
    block_info,
    build_block,
    change_block,
    clone_objects,
    dissolve,
    transform_command,
)
from rampenschmiede.core.commands import AddObjects, CommandStack, RemoveObjects
from rampenschmiede.core.geometry import transform
from rampenschmiede.core.io import rsmap, vmf
from rampenschmiede.core.model import Entity, MapDocument, Solid
from rampenschmiede.core.surf.catalog import ORIGIN, Placement


def make(template="kurve", values=None, at=ORIGIN):
    doc = MapDocument()
    stack = CommandStack(doc)
    objs, gen = build_block(doc, template, values or {"bogen": 30}, at)
    stack.push(AddObjects(objs))
    return doc, stack, objs[0], gen


def state(doc):
    return rsmap.to_dict(doc)["objects"]


def parts(doc, root_id):
    kids = doc.children(root_id)
    clips = [s for s in doc.solids() if s.extra.get(MEMBER_KEY) == root_id]
    return kids, clips


def test_block_has_visual_func_brush_and_clip_collision():
    doc, _, root, gen = make()
    assert root.classname == "func_brush" and root.get("Solidity") == "1"
    kids, clips = parts(doc, root.id)
    assert len(kids) == len(clips) == len(gen.face_sets) == 12  # 30° in 2,5°-Schritten
    assert all(f.material == PLAYERCLIP for c in clips for f in c.faces)
    assert all(c.parent_id is None for c in clips)
    assert [c.vertices() for c in clips] == [k.vertices() for k in kids]


def test_detail_variant_has_no_clips():
    doc, _, root, _ = make(values={"bogen": 30, "kollision": "detail"})
    assert root.classname == "func_detail"
    assert parts(doc, root.id)[1] == []


def test_change_block_regenerates_and_undo_restores():
    doc, stack, root, _ = make()
    before = state(doc)
    cmd, gen = change_block(doc, root.id, {"bogen": 60})
    stack.push(cmd)
    assert root.id in doc
    assert block_info(doc.get(root.id))["values"]["bogen"] == 60
    assert len(parts(doc, root.id)[0]) == 24
    stack.undo()
    assert state(doc) == before
    stack.redo()
    assert len(parts(doc, root.id)[0]) == 24


def test_slider_drag_is_one_undo_step():
    doc, stack, root, _ = make()
    before = state(doc)
    key = object()
    for bend in (35, 40, 45, 50):
        stack.push(change_block(doc, root.id, {"bogen": bend}, merge_key=key)[0])
    assert len(stack) == 2
    stack.undo()
    assert state(doc) == before


def test_delete_root_removes_clips_too():
    doc, stack, root, _ = make()
    stack.push(RemoveObjects([root.id]))
    assert len(doc) == 0
    stack.undo()
    assert len(parts(doc, root.id)[1]) == 12


def _apply(doc, stack, fn, description="T"):
    root_ids = [o.id for o in doc.entities()]
    originals = [doc.get(i) for i in root_ids] + doc.attached(root_ids)
    stack.push(transform_command(doc, originals, fn, description))


def test_move_keeps_block_and_matches_regeneration():
    doc, stack, root, _ = make()
    _apply(doc, stack, lambda o: transform.translate(o, (64, -32, 16)))
    moved = doc.get(root.id)
    assert block_info(moved)["placement"][:3] == [64, -32, 16]
    kids = sorted(v for k in parts(doc, root.id)[0] for v in k.vertices())
    fresh_doc = MapDocument()
    objs, _ = build_block(fresh_doc, "kurve", block_info(moved)["values"], Placement(64, -32, 16, 0))
    fresh = sorted(v for o in objs[1:] if isinstance(o, Solid) and o.parent_id for v in o.vertices())
    assert kids == fresh


def test_rotate_regenerates_with_integer_vertices():
    doc, stack, root, _ = make()
    _apply(doc, stack, lambda o: transform.rotate(o, (0, 0, 0), 2, 37))
    info = block_info(doc.get(root.id))
    assert info["placement"][3] == 37
    for s in doc.solids():
        assert s.is_valid()
        assert all(float(c).is_integer() for p in s.vertices() for c in p)
    stack.undo()
    assert block_info(doc.get(root.id))["placement"][3] == 0


def test_mirror_turns_block_into_plain_brushes():
    doc, stack, root, _ = make()
    _apply(doc, stack, lambda o: transform.mirror(o, (0, 0, 0), 0))
    assert block_info(doc.get(root.id)) is None
    # Die Kollision gehört weiter dazu (wird mit ausgewählt und gelöscht)
    assert len(doc.attached([root.id])) == 24


def test_dissolve_frees_clips():
    doc, stack, root, _ = make()
    stack.push(dissolve(doc, [root.id]))
    assert block_info(doc.get(root.id)) is None
    assert len(doc.attached([root.id])) == 12  # nur noch die sichtbaren Kinder


def test_clone_remaps_membership():
    doc, _, root, _ = make()
    objs = [root] + doc.attached([root.id])
    clones, roots = clone_objects(doc, objs)
    (new_root,) = roots
    assert all(o.id not in {x.id for x in objs} for o in clones)
    clips = [c for c in clones if isinstance(c, Solid) and MEMBER_KEY in c.extra]
    assert len(clips) == 12 and all(c.extra[MEMBER_KEY] == new_root for c in clips)


def test_block_survives_rsmap_roundtrip(tmp_path):
    doc, _, root, _ = make()
    path = tmp_path / "rampe.rsmap"
    rsmap.save(doc, path)
    again = rsmap.load(path)
    assert block_info(again.get(root.id)) == block_info(root)
    assert len(again.attached([root.id])) == 24
    cmd, _ = change_block(again, root.id, {"bogen": 45})
    CommandStack(again).push(cmd)
    assert len(again.children(root.id)) == 18


def test_vmf_export_has_clip_world_brushes_and_func_brush():
    doc, _, root, _ = make()
    text = vmf.export_vmf(doc).text
    assert text.count('"material" "TOOLS/TOOLSPLAYERCLIP"') == sum(len(c.faces) for c in parts(doc, root.id)[1])
    assert '"classname" "func_brush"' in text and '"Solidity" "1"' in text
    assert isinstance(root, Entity)


def test_bhop_blocks_are_detail_platforms_in_a_row():
    doc = MapDocument()
    objs, _ = build_block(doc, "bhop", {"anzahl": 4, "groesse": 64, "abstand": 128, "stufe": 16}, Placement(0, 0, 0, 90))
    root, *blocks = objs
    assert root.classname == "func_detail" and len(blocks) == 4
    tops = [b.bbox() for b in blocks]
    assert [round(b.center[1]) for b in tops] == [32, 224, 416, 608]
    assert [b.maxs[2] for b in tops] == [16, 32, 48, 64]
    assert not any(MEMBER_KEY in b.extra for b in blocks)


def test_booster_pushes_along_block_direction():
    doc = MapDocument()
    objs, _ = build_block(doc, "booster", {"tempo": 1200, "schub_neigung": 30}, Placement(0, 0, 0, 90))
    root = objs[0]
    assert root.classname == "trigger_push"
    assert root.get("pushdir") == "-30 90 0" and root.get("speed") == "1200"
    assert all(f.material == "TOOLS/TOOLSTRIGGER" for s in objs[1:] for f in s.faces)
    # Drehen des Bausteins dreht die Schubrichtung mit
    stack = CommandStack(doc)
    stack.push(AddObjects(objs))
    _apply(doc, stack, lambda o: transform.rotate(o, (0, 0, 0), 2, 90))
    assert doc.get(root.id).get("pushdir") == "-30 180 0"


def test_teleporter_gets_unique_destination():
    from rampenschmiede.core.blocks import insert_block

    doc = MapDocument()
    stack = CommandStack(doc)
    for _ in range(2):
        objs, _ = insert_block(doc, "teleporter", None, Placement(0, 0, 0, 0))
        stack.push(AddObjects(objs))
    triggers = [e for e in doc.entities() if e.classname == "trigger_teleport"]
    dests = [e for e in doc.entities() if e.classname == "info_teleport_destination"]
    assert sorted(t.get("target") for t in triggers) == sorted(d.get("targetname") for d in dests) == ["ziel", "ziel_2"]
