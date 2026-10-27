"""Material auf Flächen fallen lassen: alle Rampen oder nur eine."""
from rampenschmiede.core.blocks import block_info, build_block
from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.materials.apply import (
    SCOPE_ALL,
    SCOPE_ONE,
    apply_dropped,
    expand_scope,
    face_role,
)
from rampenschmiede.core.materials.theme import get_theme
from rampenschmiede.core.model import MapDocument


def _setup():
    doc = MapDocument()
    stack = CommandStack(doc)
    a, _ = build_block(doc, "gerade", {"laenge": 256})
    b, _ = build_block(doc, "kurve", {})
    bhop, _ = build_block(doc, "bhop", {"anzahl": 2})
    wall = solids_from_faces(doc, primitives.block((0, 0, -64), (512, 512, 0)))[0]
    stack.push(AddObjects([*a, *b, *bhop, wall]))
    return doc, stack, a[0], b[0], bhop[0], wall


def _ref(doc, root, slanted):
    for s in doc.children(root.id):
        for i, f in enumerate(s.faces):
            nz = abs(f.plane.normal[2])
            if (0.05 < nz < 0.95) == slanted:
                return (s.id, i)
    raise AssertionError


def _values(doc, root):
    return block_info(doc.get(root.id))["values"]


def test_face_roles():
    doc, _, a, _, _, wall = _setup()
    assert face_role(doc, _ref(doc, a, True))[1] == "mat_surf"
    assert face_role(doc, _ref(doc, a, False))[1] == "mat_seite"
    assert face_role(doc, (wall.id, 0)) is None


def test_drop_on_surf_applies_to_all_ramps_and_new_ones():
    doc, stack, a, b, bhop, _ = _setup()
    stack.push(apply_dropped(doc, _ref(doc, a, True), "cs/rampe", SCOPE_ALL))
    assert _values(doc, a)["mat_surf"] == "CS/RAMPE" and _values(doc, b)["mat_surf"] == "CS/RAMPE"
    assert _values(doc, a)["mat_seite"] != "CS/RAMPE"
    assert get_theme(doc).ramp == "CS/RAMPE"
    assert _values(doc, bhop).get("mat_seite") != "CS/RAMPE"
    stack.undo()
    assert not get_theme(doc).ramp


def test_drop_only_on_one_ramp():
    doc, stack, a, b, _, _ = _setup()
    stack.push(apply_dropped(doc, _ref(doc, a, False), "cs/seite", SCOPE_ONE))
    assert _values(doc, a)["mat_seite"] == "CS/SEITE"
    assert _values(doc, b).get("mat_seite") != "CS/SEITE"
    assert not get_theme(doc).ramp_side


def test_drop_on_wall_keeps_tool_faces():
    doc, stack, *_, wall = _setup()
    stack.push(apply_dropped(doc, (wall.id, 0), "cs/wand"))
    assert {f.material for f in doc.get(wall.id).faces} == {"CS/WAND"}


def test_expand_scope():
    doc, _, a, b, bhop, wall = _setup()
    assert set(expand_scope(doc, [a.id, wall.id], SCOPE_ALL)) == {a.id, b.id, wall.id}
    assert expand_scope(doc, [a.id], SCOPE_ONE) == [a.id]
    assert set(expand_scope(doc, [bhop.id], SCOPE_ALL)) == {bhop.id}
