"""Instanzen: Datei finden, Lage und Drehung, Namen-Präfix, Variablen, verschachtelt."""
import pytest

from rampenschmiede.core.commands import solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.instances import (
    collapse_instances,
    instance_bbox,
    load_map,
    matrix_angles,
    resolve,
)
from rampenschmiede.core.io import rsmap
from rampenschmiede.core.model import Entity, MapDocument, Output
from rampenschmiede.core.models.props import angle_matrix


def _content(tmp_path, name="raum.rsmap", nested=None):
    doc = MapDocument()
    (block,) = solids_from_faces(doc, primitives.block((0, 0, 0), (128, 64, 32)))
    doc._insert([block])
    doc._insert([
        Entity(id=doc.new_id(), classname="light", keyvalues=(("origin", "64 0 16"), ("targetname", "lampe"),
                                                              ("_light", "$farbe 200"))),
        Entity(id=doc.new_id(), classname="func_button", keyvalues=(("origin", "0 0 0"), ("angles", "0 0 0")),
               outputs=(Output("OnPressed", "lampe", "Toggle"), Output("OnPressed", "!player", "Kill"),
                        Output("OnPressed", "@global", "Trigger"))),
    ])
    if nested:
        doc._insert([Entity(id=doc.new_id(), classname="func_instance",
                            keyvalues=(("origin", "0 0 256"), ("file", nested), ("targetname", "innen")))])
    path = tmp_path / name
    rsmap.save(doc, path)
    return path


def test_matrix_angles_inverts_angle_matrix():
    for a in ((0, 90, 0), (30, 45, 10), (0, 270, 0), (-20, 10, 5)):
        back = matrix_angles(angle_matrix(*a))
        flat = [v for row in angle_matrix(*back) for v in row]
        assert flat == pytest.approx([v for row in angle_matrix(*a) for v in row], abs=1e-6)


def test_resolve_next_to_map_and_in_instances_folder(tmp_path):
    p = _content(tmp_path)
    (tmp_path / "instances").mkdir()
    q = _content(tmp_path / "instances", "tuer.rsmap")
    assert resolve("raum.rsmap", tmp_path) == p
    assert resolve("tuer", tmp_path) == q  # Endung darf fehlen
    assert resolve("fehlt.vmf", tmp_path) is None


def test_collapse_moves_rotates_and_prefixes(tmp_path):
    _content(tmp_path)
    doc = MapDocument()
    inst = Entity(id=doc.new_id(), classname="func_instance",
                  keyvalues=(("origin", "512 0 0"), ("angles", "0 90 0"), ("targetname", "raum1"),
                             ("file", "raum.rsmap"), ("replace01", "$farbe 255 0 0")))
    doc._insert([inst])
    out, problems = collapse_instances(doc, tmp_path)
    assert not problems and inst.id not in out and inst.id in doc
    (block,) = list(out.solids())
    bb = block.bbox()
    assert bb.mins == (448.0, 0.0, 0.0) and bb.maxs == (512.0, 128.0, 32.0)  # um 90° gedreht
    light = next(e for e in out.entities() if e.classname == "light")
    assert light.get("targetname") == "raum1-lampe" and light.get("_light") == "255 0 0 200"
    assert light.origin == (512.0, 64.0, 16.0)
    button = next(e for e in out.entities() if e.classname == "func_button")
    assert [o.target for o in button.outputs] == ["raum1-lampe", "!player", "@global"]
    assert button.get("angles") == "0 90 0"
    assert instance_bbox(inst, load_map(tmp_path / "raum.rsmap")).maxs == (512.0, 128.0, 32.0)


def test_nested_and_missing(tmp_path):
    _content(tmp_path, "innen.rsmap")
    _content(tmp_path, "aussen.rsmap", nested="innen.rsmap")
    doc = MapDocument()
    doc._insert([Entity(id=doc.new_id(), classname="func_instance",
                        keyvalues=(("origin", "0 0 0"), ("file", "aussen.rsmap"), ("fixup_style", "2"))),
                 Entity(id=doc.new_id(), classname="func_instance",
                        keyvalues=(("origin", "0 0 0"), ("file", "weg.vmf"), ("targetname", "kaputt")))])
    out, problems = collapse_instances(doc, tmp_path)
    assert len(list(out.solids())) == 2
    assert not any(e.classname == "func_instance" for e in out.entities())
    names = sorted(e.get("targetname") for e in out.entities() if e.classname == "light")
    assert names == ["innen-lampe", "lampe"]
    assert len(problems) == 1 and "kaputt" in problems[0]
