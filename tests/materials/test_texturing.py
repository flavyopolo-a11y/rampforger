"""Face-Editor-Funktionen und Material anwenden."""
import dataclasses

import pytest

from rampenschmiede.core.blocks import block_info, build_block, is_clip_member
from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.materials.apply import apply_to_objects, edit_faces, replace_material
from rampenschmiede.core.materials.texturing import align_face, align_world, justify, set_values
from rampenschmiede.core.model import Face, MapDocument, TexAxis


def texel(face: Face, p):
    u, v = face.uaxis, face.vaxis
    return (sum(a * b for a, b in zip(p, u.vec)) / u.scale + u.offset,
            sum(a * b for a, b in zip(p, v.vec)) / v.scale + v.offset)


def top_face(solid):
    return next((i, f) for i, f in enumerate(solid.faces) if f.plane.normal[2] > 0.5)


@pytest.fixture
def world():
    doc = MapDocument()
    stack = CommandStack(doc)
    solid = solids_from_faces(doc, primitives.block((0, 0, 0), (128, 64, 32)))[0]
    stack.push(AddObjects([solid]))
    return doc, stack, solid


def test_set_values_and_rotation_keep_axes_in_plane(world):
    _doc, _stack, solid = world
    _i, f = top_face(solid)
    g = set_values(f, shift=(8, None), scale=(0.5, None), rotation=90, lightmapscale=32)
    assert (g.uaxis.offset, g.uaxis.scale, g.vaxis.scale, g.rotation, g.lightmapscale) == (8, 0.5, 0.25, 90, 32)
    assert g.uaxis.vec == pytest.approx((0, 1, 0)) and g.vaxis.vec == pytest.approx((1, 0, 0))
    back = set_values(g, rotation=0)
    assert back.uaxis.vec == pytest.approx(f.uaxis.vec) and back.vaxis.vec == pytest.approx(f.vaxis.vec)


def test_align_face_runs_down_the_slope():
    doc = MapDocument()
    solid = solids_from_faces(doc, primitives.wedge((0, 0, 0), (128, 128, 128)))[0]
    slope = next(f for f in solid.faces if 0.1 < abs(f.plane.normal[2]) < 0.9)
    g = align_face(slope)
    n = slope.plane.normal
    assert abs(sum(a * b for a, b in zip(g.uaxis.vec, n))) < 1e-6
    assert abs(sum(a * b for a, b in zip(g.vaxis.vec, n))) < 1e-6
    assert g.uaxis.z == pytest.approx(0) and g.vaxis.z < 0
    assert align_world(g).uaxis.vec == slope.uaxis.vec


@pytest.mark.parametrize("mode", ["fit", "left", "right", "top", "bottom", "center"])
def test_justify_puts_edges_where_wanted(world, mode):
    _doc, _stack, solid = world
    i, f = top_face(solid)
    poly = solid.polygons()[i]
    g = justify(f, poly, (64, 64), mode)
    us = [texel(g, p)[0] for p in poly]
    vs = [texel(g, p)[1] for p in poly]

    def at(value, target):
        return (value - target) % 64 == pytest.approx(0, abs=1e-3) or (value - target) % 64 == pytest.approx(64, abs=1e-3)

    if mode == "fit":
        assert max(us) - min(us) == pytest.approx(64) and max(vs) - min(vs) == pytest.approx(64)
        assert at(min(us), 0) and at(min(vs), 0)
    elif mode == "left":
        assert at(min(us), 0)
    elif mode == "right":
        assert at(max(us), 64)
    elif mode == "top":
        assert at(min(vs), 0)
    elif mode == "bottom":
        assert at(max(vs), 64)
    else:
        assert at((min(us) + max(us)) / 2, 32) and at((min(vs) + max(vs)) / 2, 32)


def test_apply_to_brush_and_undo(world):
    doc, stack, solid = world
    stack.push(apply_to_objects(doc, [solid.id], "brick/wall"))
    assert {f.material for f in doc.get(solid.id).faces} == {"BRICK/WALL"}
    stack.undo()
    assert doc.get(solid.id).faces == solid.faces


def test_edit_single_face(world):
    doc, stack, solid = world
    i, _f = top_face(solid)
    stack.push(edit_faces(doc, [(solid.id, i)], lambda f: dataclasses.replace(f, material="X/Y")))
    mats = [f.material for f in doc.get(solid.id).faces]
    assert mats[i] == "X/Y" and mats.count("X/Y") == 1


def ramp(doc, stack):
    objs, _gen = build_block(doc, "gerade", {"laenge": 256})
    stack.push(AddObjects(objs))
    return objs[0]


def test_apply_to_block_sets_its_material_sliders():
    doc = MapDocument()
    stack = CommandStack(doc)
    root = ramp(doc, stack)
    stack.push(apply_to_objects(doc, [root.id], "ramp/blau"))
    values = block_info(doc.get(root.id))["values"]
    assert values["mat_surf"] == values["mat_seite"] == "RAMP/BLAU"
    kids = doc.children(root.id)
    assert {f.material for s in kids for f in s.faces} <= {"RAMP/BLAU", "TOOLS/TOOLSNODRAW"}
    clips = [s for s in doc.solids() if is_clip_member(s)]
    assert clips and all(f.material == "TOOLS/TOOLSPLAYERCLIP" for s in clips for f in s.faces)


def test_face_of_block_changes_only_its_role():
    doc = MapDocument()
    stack = CommandStack(doc)
    root = ramp(doc, stack)
    kid = doc.children(root.id)[0]
    surf_i = next(i for i, f in enumerate(kid.faces) if f.material == "DEV/DEV_MEASUREGENERIC01B")
    stack.push(edit_faces(doc, [(kid.id, surf_i)], lambda f: dataclasses.replace(f, material="SURF/ROT")))
    values = block_info(doc.get(root.id))["values"]
    assert values["mat_surf"] == "SURF/ROT" and values["mat_seite"] == "DEV/DEV_MEASUREGENERIC01"


def test_replace_material_everywhere(world):
    doc, stack, solid = world
    root = ramp(doc, stack)
    stack.push(replace_material(doc, "dev/dev_measuregeneric01b", "neu/mat"))
    assert all(f.material == "NEU/MAT" for f in doc.get(solid.id).faces)
    assert block_info(doc.get(root.id))["values"]["mat_surf"] == "NEU/MAT"
    stack.undo()
    assert doc.get(solid.id).faces == solid.faces


def test_nothing_to_do_gives_none(world):
    doc, _stack, solid = world
    assert apply_to_objects(doc, [], "a/b") is None
    assert edit_faces(doc, [], lambda f: f) is None
    assert TexAxis(1, 0, 0).scale == 0.25
