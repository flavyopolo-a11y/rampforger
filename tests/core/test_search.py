"""Suchen und Ersetzen, Gehe zu ID."""
from rampenschmiede.core import search
from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.io import vmf
from rampenschmiede.core.model import Entity, MapDocument, Output


def _doc():
    doc = MapDocument()
    stack = CommandStack(doc)
    a = Entity(id=doc.new_id(), classname="info_teleport_destination", keyvalues=(("targetname", "stage2_dest"),))
    b = Entity(id=doc.new_id(), classname="trigger_teleport", keyvalues=(("target", "stage2_dest"),),
               outputs=(Output("OnStartTouch", "stage2_dest", "Enable"),))
    s1, s2 = solids_from_faces(doc, primitives.block((0, 0, 0), (64, 64, 64), "CONCRETE/A")
                               + primitives.block((128, 0, 0), (192, 64, 64), "CONCRETE/B"))
    stack.push(AddObjects([a, b, s1, s2]))
    return doc, stack, a, b, s1, s2


def test_find_entities_by_field_and_wildcard():
    doc, _, a, b, *_ = _doc()
    assert search.find_entities(doc, "teleport", "klasse") == sorted([a.id, b.id])
    assert search.find_entities(doc, "stage2", "name") == [a.id]
    assert search.find_entities(doc, "stage2_dest", "alle", whole=True) == sorted([a.id, b.id])
    assert search.find_entities(doc, "trigger_*", "klasse") == [b.id]


def test_rename_everywhere_including_io():
    doc, stack, a, b, *_ = _doc()
    ids = search.find_entities(doc, "stage2_dest")
    stack.push(search.replace_in_entities(doc, ids, "stage2", "stage3"))
    assert doc.get(a.id).get("targetname") == "stage3_dest"
    assert doc.get(b.id).get("target") == "stage3_dest"
    assert doc.get(b.id).outputs[0].target == "stage3_dest"
    assert search.replace_in_entities(doc, ids, "gibtsnicht", "x") is None


def test_texture_find_and_replace_with_wildcard_and_scope():
    doc, stack, *_, s1, s2 = _doc()
    assert sorted(search.find_material_users(doc, "concrete/*")) == sorted([s1.id, s2.id])
    stack.push(search.replace_materials(doc, "concrete/*", "brick/c", ids=[s1.id]))
    assert all(f.material == "BRICK/C" for f in doc.get(s1.id).faces)
    assert all(f.material == "CONCRETE/B" for f in doc.get(s2.id).faces)
    assert "BRICK/C" in search.used_materials(doc)


def test_goto_by_exported_id_internal_id_and_name():
    doc, _, a, _b, s1, _ = _doc()
    exported = vmf.export_vmf(doc)
    vmf_id = next(k for k, v in exported.solid_ids.items() if v == s1.id)
    assert search.goto_id(doc, str(vmf_id)) == s1.id
    assert search.goto_id(doc, "stage2_dest") == a.id
    assert search.goto_id(doc, "99999") is None
