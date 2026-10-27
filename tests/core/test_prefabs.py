"""Eigene Prefabs: speichern, auflisten, einsetzen."""
from rampenschmiede.core.blocks import MEMBER_KEY, block_info, build_block
from rampenschmiede.core.commands import AddObjects, CommandStack
from rampenschmiede.core.model import Entity, MapDocument, Solid
from rampenschmiede.core.prefabs import (
    list_prefabs,
    load_prefab,
    make_prefab,
    place_prefab,
    save_prefab,
)
from rampenschmiede.core.surf.catalog import Placement

from ..helpers import doc_with_block


def test_prefab_roundtrip_keeps_blocks_and_anchor(tmp_path):
    doc = MapDocument()
    stack = CommandStack(doc)
    objs, _ = build_block(doc, "kurve", {"bogen": 20}, Placement(1000, 2000, 64, 0))
    stack.push(AddObjects(objs))
    data = make_prefab(doc, [objs[0].id], "Meine Kurve")
    path = save_prefab(data, tmp_path)
    assert path.name == "Meine Kurve.json"
    assert list_prefabs(tmp_path) == [("Meine Kurve", path)]

    loaded = load_prefab(path)
    new, roots = place_prefab(doc, loaded, (0, 0, 0))
    stack.push(AddObjects(new))
    (root,) = roots
    ent = doc.get(root)
    assert isinstance(ent, Entity) and block_info(ent)["values"]["bogen"] == 20
    # Anker: Mitte unten der Auswahl liegt jetzt im Nullpunkt
    bb = doc.bbox([root])
    assert abs(bb.center[0]) <= 1 and abs(bb.center[1]) <= 1 and bb.mins[2] == 0
    assert len([s for s in doc.solids() if s.extra.get(MEMBER_KEY) == root]) == 8
    # Platzierung des Bausteins ist mitgewandert: Neu bauen ergibt dieselbe Lage
    placement = block_info(ent)["placement"]
    assert placement[2] == 0


def test_plain_brush_prefab_and_broken_files(tmp_path):
    doc, _stack, s = doc_with_block((0, 0, 0), (64, 64, 64))
    save_prefab(make_prefab(doc, [s.id], "Kiste/1"), tmp_path)
    (tmp_path / "kaputt.json").write_text("{", encoding="utf-8")
    (tmp_path / "fremd.json").write_text('{"format": "x"}', encoding="utf-8")
    (name, path), = list_prefabs(tmp_path)
    assert name == "Kiste/1" and path.name == "Kiste_1.json"
    new, roots = place_prefab(doc, load_prefab(path), (128, 0, 0))
    assert len(new) == 1 and isinstance(new[0], Solid) and new[0].id != s.id
    assert new[0].bbox().mins == (96.0, -32.0, 0.0)
