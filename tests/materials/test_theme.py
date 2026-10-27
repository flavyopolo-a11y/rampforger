"""Map-Thema: Rampen- und Wandmaterialien, Playerclip-Standard."""
from rampenschmiede.core.blocks import block_info, build_block, is_clip_member
from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.io import rsmap
from rampenschmiede.core.materials.theme import (
    Theme,
    apply_theme,
    block_defaults,
    get_theme,
    set_theme,
)
from rampenschmiede.core.model import MapDocument
from rampenschmiede.core.surf.catalog import CATALOG

THEME = Theme(ramp="R/SURF", ramp_side="R/SEITE", wall="W/WAND", collision="clip")


def setup():
    doc = MapDocument()
    stack = CommandStack(doc)
    ramp, _ = build_block(doc, "gerade", {"laenge": 256, "kollision": "detail"})
    bhop, _ = build_block(doc, "bhop", {"anzahl": 2})
    zone, _ = build_block(doc, "zone_start")
    floor = solids_from_faces(doc, primitives.block((0, 0, -64), (512, 512, 0)))[0]
    sky = solids_from_faces(doc, primitives.block((0, 0, 900), (512, 512, 1000), "TOOLS/TOOLSSKYBOX"))[0]
    stack.push(AddObjects([*ramp, *bhop, *zone, floor, sky]))
    return doc, stack, ramp[0], bhop[0], zone[0], floor, sky


def test_theme_roundtrip(tmp_path):
    doc = MapDocument()
    assert not get_theme(doc).is_set()
    set_theme(doc, THEME)
    rsmap.save(doc, tmp_path / "a.rsmap")
    assert get_theme(rsmap.load(tmp_path / "a.rsmap")) == THEME


def test_new_blocks_take_theme_defaults():
    doc = MapDocument()
    assert block_defaults(doc, CATALOG["gerade"]) == {"kollision": "clip"}
    set_theme(doc, Theme(ramp="A/B", ramp_side="C/D", wall="E/F", collision="detail"))
    assert block_defaults(doc, CATALOG["kurve"]) == {"kollision": "detail", "mat_surf": "A/B", "mat_seite": "C/D"}
    assert block_defaults(doc, CATALOG["bhop"]) == {"mat_seite": "E/F"}
    assert block_defaults(doc, CATALOG["teleporter"]) == {}


def test_apply_theme_to_whole_map_and_undo():
    doc, stack, ramp, bhop, zone, floor, sky = setup()
    stack.push(apply_theme(doc, THEME))
    values = block_info(doc.get(ramp.id))["values"]
    assert (values["mat_surf"], values["mat_seite"], values["kollision"]) == ("R/SURF", "R/SEITE", "clip")
    assert any(is_clip_member(s) for s in doc.solids())  # Playerclip jetzt da
    assert block_info(doc.get(bhop.id))["values"]["mat_seite"] == "W/WAND"
    assert {f.material for f in doc.get(floor.id).faces} == {"W/WAND"}
    assert {f.material for f in doc.get(sky.id).faces} == {"TOOLS/TOOLSSKYBOX"}
    assert {f.material for s in doc.children(zone.id) for f in s.faces} == {"TOOLS/TOOLSTRIGGER"}
    stack.undo()
    assert block_info(doc.get(ramp.id))["values"]["kollision"] == "detail"
    assert doc.get(floor.id).faces == floor.faces


def test_apply_theme_to_selection_only():
    doc, stack, ramp, _bhop, _zone, floor, _sky = setup()
    stack.push(apply_theme(doc, THEME, [floor.id]))
    assert {f.material for f in doc.get(floor.id).faces} == {"W/WAND"}
    assert block_info(doc.get(ramp.id))["values"]["mat_surf"] != "R/SURF"
