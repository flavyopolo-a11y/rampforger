"""Sichtgruppen: anlegen, aus-/einblenden, mehrere Gruppen, VMF hin und zurück."""
from rampenschmiede.core import visgroups as vg
from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.io.vmf import export_vmf, parse_vmf
from rampenschmiede.core.model import MapDocument


def _doc(n=3):
    doc = MapDocument()
    stack = CommandStack(doc)
    solids = solids_from_faces(doc, [fs for i in range(n) for fs in primitives.block((i * 128, 0, 0), (i * 128 + 64, 64, 64))])
    stack.push(AddObjects(solids))
    return doc, stack, solids


def test_create_hide_show_and_undo():
    doc, stack, (a, b, c) = _doc()
    cmd, g1 = vg.create(doc, "Dach", [a.id, b.id])
    stack.push(cmd)
    cmd, g2 = vg.create(doc, "Deko", [b.id, c.id])
    stack.push(cmd)
    assert [g.name for g in vg.visgroups(doc)] == ["Dach", "Deko"] and g1 != g2
    assert sorted(vg.members(doc, g1)) == sorted([a.id, b.id])
    stack.push(vg.set_shown(doc, g1, False))
    assert doc.get(a.id).editor.hidden and doc.get(b.id).editor.hidden and not doc.get(c.id).editor.hidden
    stack.push(vg.set_shown(doc, g2, False))
    stack.push(vg.set_shown(doc, g1, True))
    # b steckt noch in der versteckten Gruppe Deko
    assert not doc.get(a.id).editor.hidden and doc.get(b.id).editor.hidden
    stack.undo()
    assert doc.get(a.id).editor.hidden
    stack.push(vg.delete(doc, g2))
    assert [g.id for g in vg.visgroups(doc)] == [g1]
    assert doc.get(c.id).editor.visgroup_ids == () and not doc.get(c.id).editor.hidden


def test_vmf_roundtrip_keeps_groups():
    doc, stack, (a, b, _c) = _doc()
    cmd, gid = vg.create(doc, "Rampen", [a.id])
    stack.push(cmd)
    text = export_vmf(doc).text
    assert '"name" "Rampen"' in text and f'"visgroupid" "{gid}"' in text
    doc2, _ = parse_vmf(text)
    groups = vg.visgroups(doc2)
    assert [(g.id, g.name) for g in groups] == [(gid, "Rampen")]
    assert len(vg.members(doc2, gid)) == 1
