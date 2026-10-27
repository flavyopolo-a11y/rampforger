"""VMF-Import/Export: verlustfreier Roundtrip und gültige Dateien für die Compiler."""
from pathlib import Path

import pytest
from srctools.keyvalues import Keyvalues
from srctools.vmf import VMF

from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.io import rsmap
from rampenschmiede.core.io.vmf import (
    VmfError,
    export_vmf,
    format_axis,
    format_plane,
    kv_to_raw,
    load_vmf,
    parse_axis,
    parse_plane,
    parse_vmf,
    save_vmf,
)
from rampenschmiede.core.model import Entity, MapDocument, Output, Solid

FIXTURE = Path(__file__).parent.parent / "fixtures" / "beispiel.vmf"


def tree(text: str):
    """Die Datei als roher Baum, so wie die Compiler sie lesen."""
    return [kv_to_raw(kv) for kv in Keyvalues.parse(text, allow_escapes=False)]


def test_fixture_import_counts():
    doc, report = load_vmf(FIXTURE)
    assert report.solids == 3
    assert report.entities == 4
    assert report.warnings == []
    assert all(s.is_valid() for s in doc.solids())


def test_roundtrip_is_lossless():
    text = FIXTURE.read_text(encoding="utf-8")
    doc, _ = parse_vmf(text)
    assert tree(export_vmf(doc).text) == tree(text)


def test_roundtrip_through_project_file(tmp_path):
    """VMF -> .rsmap -> laden -> VMF darf ebenfalls nichts verlieren."""
    text = FIXTURE.read_text(encoding="utf-8")
    doc, _ = parse_vmf(text)
    path = tmp_path / "map.rsmap"
    rsmap.save(doc, path)
    again = rsmap.load(path)
    assert tree(export_vmf(again).text) == tree(text)


def test_imported_details():
    doc, _ = load_vmf(FIXTURE)
    world = sorted((s for s in doc.solids() if s.parent_id is None), key=lambda s: s.vmf_id)
    block, hidden = world
    assert block.vmf_id == 2
    assert block.editor.color == (0, 180, 255)
    assert block.editor.group_id == 40
    assert block.editor.visgroup_ids == (3,)
    assert "raw" in block.faces[0].extra  # dispinfo bleibt erhalten
    assert block.faces[0].extra["raw"][0][0] == "dispinfo"
    assert hidden.editor.hidden
    assert hidden.faces[0].uaxis.offset == 16 and hidden.faces[0].uaxis.scale == 0.5
    assert hidden.faces[0].lightmapscale == 32
    assert doc.world_get("skyname") == "sky_day01_01"

    ents = {e.classname: e for e in doc.entities()}
    light = ents["light"]
    assert light.editor.hidden and light.get("_light") == "255 240 200 300"
    relay = ents["logic_relay"]
    assert relay.outputs[0] == Output("OnTrigger", "door_*", "Open", "", 0.0, -1)
    assert relay.outputs[1].parameter == "Hallo, Welt"
    assert relay.outputs[1].delay == 1.5 and relay.outputs[1].times == 1
    assert relay.outputs[2] == Output("OnSpawn", "relay_reset", "Trigger", "", 0.25, 1)
    trigger = ents["trigger_teleport"]
    children = doc.children(trigger.id)
    assert len(children) == 1 and children[0].faces[0].material == "TOOLS/TOOLSTRIGGER"


def test_srctools_reads_export():
    doc, _ = load_vmf(FIXTURE)
    vmf = VMF.parse(Keyvalues.parse(export_vmf(doc).text))
    assert len(vmf.brushes) == 2
    assert {e["classname"] for e in vmf.entities} == {
        "info_player_counterterrorist", "logic_relay", "light", "trigger_teleport",
    }


def _new_doc() -> MapDocument:
    doc = MapDocument()
    stack = CommandStack(doc)
    solids = solids_from_faces(doc, primitives.block((0, 0, 0), (128, 128, 16)))
    solids += solids_from_faces(doc, primitives.wedge((0, 0, 16), (128, 256, 128), "TOOLS/TOOLSPLAYERCLIP"))
    ent = Entity(id=doc.new_id(), classname="info_player_counterterrorist",
                 keyvalues=(("origin", "64 64 32"), ("angles", "0 0 0")))
    stack.push(AddObjects([*solids, ent]))
    return doc


def test_export_new_document_is_valid_and_reimports():
    doc = _new_doc()
    result = export_vmf(doc)
    vmf = VMF.parse(Keyvalues.parse(result.text))
    assert len(vmf.brushes) == 2
    assert vmf.spawn["classname"] == "worldspawn"
    # Alle IDs eindeutig
    ids = [b.id for b in vmf.brushes] + [e.id for e in vmf.entities] + [vmf.spawn.id]
    assert len(ids) == len(set(ids))
    side_ids = [s.id for b in vmf.brushes for s in b.sides]
    assert len(side_ids) == len(set(side_ids)) == result.side_count
    # Zuordnung VMF-ID -> Objekt
    assert set(result.solid_ids.values()) == {s.id for s in doc.solids()}
    again, report = parse_vmf(result.text)
    assert report.solids == 2 and report.entities == 1
    for a, b in zip(sorted(doc.solids(), key=lambda s: s.id), sorted(again.solids(), key=lambda s: s.id)):
        assert [f.points for f in a.faces] == [f.points for f in b.faces]
        assert [f.material for f in a.faces] == [f.material for f in b.faces]


def test_new_objects_do_not_steal_imported_ids():
    doc, _ = load_vmf(FIXTURE)
    stack = CommandStack(doc)
    # Neues Objekt und eine Kopie eines importierten (gleiche VMF-ID) kommen dazu
    new = solids_from_faces(doc, primitives.block((512, 0, 0), (576, 64, 64)))
    old = next(s for s in doc.solids() if s.vmf_id == 2)
    copy = old.replace(id=doc.new_id())
    stack.push(AddObjects([*new, copy]))
    result = export_vmf(doc)
    assert result.solid_ids[2] == old.id
    vmf = VMF.parse(Keyvalues.parse(result.text))
    ids = [b.id for b in vmf.brushes] + [e.id for e in vmf.entities] + [vmf.spawn.id]
    for ent in vmf.entities:
        ids += [b.id for b in ent.solids]
    assert len(ids) == len(set(ids))
    side_ids = [s.id for b in vmf.brushes for s in b.sides]
    assert len(side_ids) == len(set(side_ids))


def test_save_uses_crlf(tmp_path):
    doc = _new_doc()
    path = tmp_path / "test.vmf"
    save_vmf(doc, path)
    data = path.read_bytes()
    assert b"\r\n" in data and b"\r\r" not in data
    assert not (tmp_path / "test.vmf.tmp").exists()


def test_cp1252_fallback(tmp_path):
    text = FIXTURE.read_text(encoding="utf-8").replace("relay_reset", "relay_ä")
    path = tmp_path / "alt.vmf"
    path.write_bytes(text.encode("cp1252"))
    doc, _ = load_vmf(path)
    assert any(e.get("targetname") == "relay_ä" for e in doc.entities())


def test_rejects_garbage():
    with pytest.raises(VmfError):
        parse_vmf("entity\n{\n\"classname\" \"light\"\n}\n")
    with pytest.raises(VmfError):
        parse_vmf("world\n{\n")
    with pytest.raises(VmfError):
        parse_plane("(0 0 0) (1 1 1)")
    with pytest.raises(VmfError):
        parse_axis("[1 0 0] 0.25")


@pytest.mark.parametrize("text", [
    "(-64 64 64) (64 64 64) (64 -64 64)",
    "(0.5 -1.25 3) (1e-05 2 3) (100000 0 -7)",
])
def test_plane_format_roundtrip(text):
    assert parse_plane(format_plane(parse_plane(text))) == parse_plane(text)


def test_axis_format_roundtrip():
    a = parse_axis("[0.707107 0.707107 0 -12.5] 0.375")
    assert parse_axis(format_axis(a)) == a


def test_solid_hidden_inside_visible_entity_roundtrip():
    doc = _new_doc()
    stack = CommandStack(doc)
    solid = next(iter(doc.solids()))
    ent = Entity(id=doc.new_id(), classname="func_detail")
    stack.push(AddObjects([ent]))
    from rampenschmiede.core.commands import ReplaceObjects
    stack.push(ReplaceObjects([solid.replace(parent_id=ent.id, editor=solid.editor.__class__(hidden=True))]))
    again, _ = parse_vmf(export_vmf(doc).text)
    child = next(s for s in again.solids() if s.parent_id is not None)
    assert child.editor.hidden
    assert isinstance(again.get(child.parent_id), Entity)
    assert not again.get(child.parent_id).editor.hidden
    assert isinstance(child, Solid)


def test_new_output_with_comma_uses_escape():
    doc = MapDocument()
    stack = CommandStack(doc)
    ent = Entity(id=doc.new_id(), classname="logic_relay", keyvalues=(("origin", "0 0 0"),),
                 outputs=(Output("OnTrigger", "msg", "SetText", "a, b", 0.0, -1),
                          Output("OnTrigger", "door", "Open")))
    stack.push(AddObjects([ent]))
    text = export_vmf(doc).text
    assert "msg\x1bSetText\x1ba, b\x1b0\x1b-1" in text
    assert '"door,Open,,0,-1"' in text
    again, _ = parse_vmf(text)
    assert next(again.entities()).outputs == ent.outputs
