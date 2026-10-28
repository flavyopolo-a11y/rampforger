"""Probleme suchen: jede Prüfung meldet, springt zu den Objekten und repariert, wo es geht."""
import dataclasses

from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.geometry.vertex_edit import off_grid
from rampenschmiede.core.model import Entity, MapDocument, Output
from rampenschmiede.core.templates import starter_room
from rampenschmiede.core.validation.problems import ERROR, WARNING, find_problems, fix_all


def _doc(*objs_fn):
    doc = MapDocument()
    stack = CommandStack(doc)
    stack.push(AddObjects(starter_room(doc)))
    return doc, stack


def _add(doc, stack, objs):
    stack.push(AddObjects(list(objs)))
    return objs


def _areas(problems):
    return [(p.level, p.area) for p in problems]


def test_starter_room_only_misses_the_end_zone():
    doc, _ = _doc()
    assert [p.text for p in find_problems(doc)] == ["Hauptstrecke: Zielzone fehlt"]


def test_no_spawn_is_an_error():
    doc = MapDocument()
    assert (ERROR, "Spawns") in _areas(find_problems(doc))


def test_spawn_stuck_in_brush():
    doc, stack = _doc()
    spawn = next(e for e in doc.entities() if e.classname.startswith("info_player"))
    o = spawn.origin
    box = solids_from_faces(doc, primitives.block((o[0] - 64, o[1] - 64, o[2]), (o[0] + 64, o[1] + 64, o[2] + 32)))
    _add(doc, stack, box)
    probs = [p for p in find_problems(doc) if p.area == "Spawns"]
    assert probs and probs[0].level == ERROR and box[0].id in probs[0].ids
    # Auf dem Boden stehen ist kein Problem
    stack.undo()
    assert not [p for p in find_problems(doc) if p.area == "Spawns"]


def test_teleporter_checks_and_flag_fix():
    doc, stack = _doc()
    tele = Entity(id=doc.new_id(), classname="trigger_teleport", keyvalues=(("target", "nirgends"),))
    brush = solids_from_faces(doc, primitives.block((256, 256, 64), (320, 320, 128), "TOOLS/TOOLSTRIGGER"),
                              parent_id=tele.id)
    _add(doc, stack, [tele, *brush])
    probs = [p for p in find_problems(doc) if p.area == "Teleporter"]
    assert any("gibt es nicht" in p.text for p in probs)
    flag = next(p for p in probs if p.fix is not None)
    stack.push(flag.fix(doc))
    assert doc.get(tele.id).get("spawnflags") == "1"
    assert not any(p.fix for p in find_problems(doc) if p.area == "Teleporter")


def test_io_target_and_empty_brush_entity():
    doc, stack = _doc()
    relay = Entity(id=doc.new_id(), classname="logic_relay", keyvalues=(("origin", "0 0 64"),),
                   outputs=(Output("OnTrigger", "fehlt", "Open"), Output("OnTrigger", "!activator", "Kill")))
    empty = Entity(id=doc.new_id(), classname="trigger_multiple")
    _add(doc, stack, [relay, empty])
    probs = find_problems(doc)
    assert sum("„fehlt“" in p.text for p in probs) == 1
    leer = next(p for p in probs if "ohne Brushes" in p.text)
    stack.push(fix_all(doc, [leer]))
    assert empty.id not in doc


def test_invalid_and_duplicate_brushes_are_fixable():
    doc, stack = _doc()
    a = solids_from_faces(doc, primitives.block((0, 0, 64), (64, 64, 128)))[0]
    b = a.replace(id=doc.new_id())
    broken = a.replace(id=doc.new_id(), faces=a.faces[:3])
    _add(doc, stack, [a, b, broken])
    probs = find_problems(doc)
    assert (ERROR, "Brushes") in _areas(probs) and (WARNING, "Brushes") in _areas(probs)
    stack.push(fix_all(doc, probs))
    assert broken.id not in doc and b.id not in doc and a.id in doc
    assert not [p for p in find_problems(doc) if p.area == "Brushes"]


def test_flat_ramp_and_off_grid_ramp():
    doc, stack = _doc()
    # Keil mit 45° (zu flach) und einer mit 60°, dessen Ecken nicht auf ganzen Units liegen
    flat = solids_from_faces(doc, primitives.wedge((0, 0, 64), (256, 256, 320)))[0]
    steep = solids_from_faces(doc, primitives.wedge((512, 0, 64), (640, 128, 286)))[0]
    shifted = dataclasses.replace(steep, faces=tuple(
        dataclasses.replace(f, points=tuple((x + 0.4, y, z) for x, y, z in f.points)) for f in steep.faces))
    _add(doc, stack, [flat, shifted])
    assert off_grid(shifted)
    probs = [p for p in find_problems(doc) if p.area == "Rampen"]
    texts = " ".join(p.text for p in probs)
    assert "zu flach" in texts and "Rampbug" in texts
    bug = next(p for p in probs if p.fix is not None)
    stack.push(bug.fix(doc))
    assert not off_grid(doc.get(shifted.id))


def test_limits_outside_map():
    doc, stack = _doc()
    far = solids_from_faces(doc, primitives.block((16000, 0, 0), (16500, 64, 64)))
    _add(doc, stack, far)
    assert any(p.area == "Grenzen" and far[0].id in p.ids for p in find_problems(doc))


class _Lib:
    def __init__(self, known):
        self.known = {k.upper() for k in known}

    def exists(self, name):
        return name.upper() in self.known


def test_missing_texture_is_replaced_with_default():
    doc, stack = _doc()
    s = solids_from_faces(doc, primitives.block((0, 0, 64), (64, 64, 128), "GIBTS/NICHT"))[0]
    _add(doc, stack, [s])
    lib = _Lib({f.material for o in doc.solids() for f in o.faces if o.id != s.id})
    probs = [p for p in find_problems(doc, materials=lib) if p.area == "Texturen"]
    assert len(probs) == 1 and probs[0].ids == (s.id,)
    stack.push(probs[0].fix(doc))
    assert all(f.material != "GIBTS/NICHT" for f in doc.get(s.id).faces)


