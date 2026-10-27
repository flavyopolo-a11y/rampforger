import json

import pytest

from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.io import rsmap
from rampenschmiede.core.model import Entity, MapDocument, Output


def build_doc():
    doc = MapDocument()
    stack = CommandStack(doc)
    objs = []
    for faces in primitives.block((0, 0, 0), (512, 512, 16)) + primitives.arch((0, 0, 16), (256, 256, 64), 6):
        objs += solids_from_faces(doc, [faces])
    ent = Entity(id=doc.new_id(), classname="info_player_counterterrorist",
                 keyvalues=(("origin", "64 64 32"), ("angles", "0 90 0")),
                 outputs=(Output("OnTrigger", "door", "Open", "", 0.5, 1),))
    stack.push(AddObjects(objs + [ent]))
    doc.editor.grid_size = 32
    return doc


def test_roundtrip_identical(tmp_path):
    doc = build_doc()
    path = tmp_path / "test.rsmap"
    rsmap.save(doc, path)
    loaded = rsmap.load(path)
    assert rsmap.to_dict(loaded) == rsmap.to_dict(doc)
    assert loaded.editor.grid_size == 32
    # Neue IDs kollidieren nicht mit geladenen
    assert loaded.new_id() > max(o.id for o in loaded.objects())


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    doc = build_doc()
    path = tmp_path / "a.rsmap"
    rsmap.save(doc, path)
    rsmap.save(doc, path)
    assert [p.name for p in tmp_path.iterdir()] == ["a.rsmap"]


def test_rejects_foreign_file(tmp_path):
    p = tmp_path / "x.rsmap"
    p.write_text(json.dumps({"hello": 1}))
    with pytest.raises(rsmap.ProjectFormatError):
        rsmap.load(p)


def test_rejects_newer_schema(tmp_path):
    p = tmp_path / "x.rsmap"
    p.write_text(json.dumps({"format": rsmap.FORMAT_NAME, "schema_version": 999}))
    with pytest.raises(rsmap.ProjectFormatError):
        rsmap.load(p)


def test_extra_data_survives(tmp_path):
    doc = MapDocument()
    (faces,) = primitives.block((0, 0, 0), (8, 8, 8))
    from rampenschmiede.core.model import Solid
    doc._insert([Solid(id=1, faces=faces, extra={"vmf": [["unbekannt", "wert"]]})])
    rsmap.save(doc, tmp_path / "e.rsmap")
    assert rsmap.load(tmp_path / "e.rsmap").get(1).extra == {"vmf": [["unbekannt", "wert"]]}
