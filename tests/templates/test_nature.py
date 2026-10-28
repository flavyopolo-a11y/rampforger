from rampenschmiede.core.blocks import insert_block
from rampenschmiede.core.materials.authoring import lava_material
from rampenschmiede.core.model import Entity, MapDocument, Solid
from rampenschmiede.core.surf.nature_templates import DEFAULT_WATER, find_water
from rampenschmiede.core.templates.starter import starter_room
from rampenschmiede.core.validation.seal import check_seal, seals


def _faces_by_dir(solid):
    up = [f.material for f in solid.faces if f.plane.normal[2] > 0.99]
    rest = {f.material for f in solid.faces if f.plane.normal[2] <= 0.99}
    return up, rest


def test_water_is_world_brush_with_water_on_top_only():
    doc = MapDocument()
    objs, _ = insert_block(doc, "wasser", {"laenge": 512, "breite": 256, "tiefe": 96})
    assert len(objs) == 1 and isinstance(objs[0], Solid) and objs[0].parent_id is None
    up, rest = _faces_by_dir(objs[0])
    assert up == [DEFAULT_WATER] and rest == {"TOOLS/TOOLSNODRAW"}
    bb = objs[0].bbox()
    assert bb.size == (512, 256, 96) and not seals(objs[0])


def test_deadly_water_and_lava_bring_a_grouped_hurt_trigger():
    doc = MapDocument()
    objs, _ = insert_block(doc, "wasser", {"todeswasser": True})
    ents = [o for o in objs if isinstance(o, Entity)]
    assert [e.classname for e in ents] == ["trigger_hurt"] and ents[0].get("damage") == "100000"
    top = [o for o in objs if getattr(o, "parent_id", None) is None]  # Gruppen gelten für oberste Objekte
    assert len({o.editor.group_id for o in top}) == 1 and objs[0].editor.group_id is not None
    trig = next(o for o in objs if isinstance(o, Solid) and o.parent_id == ents[0].id)
    assert trig.bbox() == objs[0].bbox()
    objs, _ = insert_block(doc, "lava", {"mat_lava": "LAVA/X", "tiefe": 32})
    lava, ent, trig = objs
    assert {f.material for f in lava.faces} == {"LAVA/X"} and seals(lava)
    # Der Trigger reicht über die Oberfläche: wer darauf steht, stirbt
    assert trig.bbox().maxs[2] == lava.bbox().maxs[2] + 16 and trig.bbox().mins[2] < lava.bbox().maxs[2]


def test_kill_zone_back_to_start_creates_destination_once():
    doc = MapDocument()
    doc._insert(starter_room(doc, "css"))
    objs, _ = insert_block(doc, "killzone", {"art": "zurueck"})
    dest = [o for o in objs if isinstance(o, Entity) and o.classname == "info_teleport_destination"]
    assert objs[0].classname == "trigger_teleport" and objs[0].get("target") == "zurueck" and len(dest) == 1
    zone = next(e for e in doc.entities() if e.get("targetname") == "mod_zone_start")
    zb = doc.bbox([zone.id])
    assert zb.contains(dest[0].origin)
    doc._insert(objs)
    again, _ = insert_block(doc, "killzone", {"art": "zurueck"})
    assert not any(o.classname == "info_teleport_destination" for o in again if isinstance(o, Entity))
    plain, _ = insert_block(doc, "killzone", {})
    assert plain[0].classname == "trigger_hurt"


def test_water_inside_starter_room_keeps_it_sealed():
    doc = MapDocument()
    doc._insert(starter_room(doc, "css"))
    objs, _ = insert_block(doc, "wasser", {"todeswasser": True})
    doc._insert(objs)
    assert check_seal(doc).sealed


class _Lib:
    def __init__(self, mats):
        self.mats = mats

    def exists(self, name):
        return name.lower() in self.mats

    def names(self):
        return list(self.mats)

    def material(self, name):
        from types import SimpleNamespace

        return SimpleNamespace(shader=self.mats[name.lower()])


def test_find_water_falls_back_to_any_water_shader():
    assert find_water(None) == DEFAULT_WATER
    assert find_water(_Lib({DEFAULT_WATER.lower(): "Water"})) == DEFAULT_WATER
    lib = _Lib({"nature/water_dirty": "LightmappedGeneric", "de_aztec/water_aztec": "Water"})
    assert find_water(lib) == "DE_AZTEC/WATER_AZTEC"


def test_lava_texture_glows(tmp_path):
    name = lava_material(tmp_path)
    vmt = (tmp_path / "materials" / f"{name}.vmt").read_text()
    assert '"$selfillum" "1"' in vmt and (tmp_path / "materials" / f"{name}.vtf").is_file()
