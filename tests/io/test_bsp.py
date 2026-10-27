"""BSP öffnen: Brushes aus den Ebenen zurückrechnen, Entities, Trigger, Detail, Props."""
import pytest

from rampenschmiede.core.io import bsp as bsp_io
from rampenschmiede.core.io.bsp import BspError, extract_materials, load_bsp, original_material
from rampenschmiede.core.model import Entity, Solid

from .bsp_builder import build_bsp


@pytest.fixture
def opened(tmp_path):
    return load_bsp(build_bsp(tmp_path / "surf_test.bsp"))


def test_brushes_come_back_with_corners_and_textures(opened):
    doc, report = opened
    assert report.solids == 4 and report.broken == 0
    world = [s for s in doc.solids() if s.parent_id is None]
    floor = next(s for s in world if s.faces[0].material == "DEV/DEV_MEASUREGENERIC01")
    bb = floor.bbox()
    assert (bb.mins, bb.maxs) == ((-512, -512, -64), (512, 512, 0))
    # Bevel-Ebenen sind keine Seiten
    assert len(floor.faces) == 6 and floor.is_valid()
    assert all(float(c).is_integer() for p in floor.vertices() for c in p)
    # Texturachse: BSP speichert Achse / Maßstab, VMF Achse und Maßstab getrennt
    top = next(f for f in floor.faces if f.plane.normal[2] > 0.9)
    assert top.uaxis.vec == (1, 0, 0) and top.uaxis.scale == pytest.approx(4)
    assert top.lightmapscale == 16


def test_clip_brush_and_world_keyvalues(opened):
    doc, _ = opened
    clip = next(s for s in doc.solids() if s.faces[0].material == "TOOLS/TOOLSPLAYERCLIP")
    assert clip.parent_id is None
    assert dict(doc.world_keyvalues)["skyname"] == "sky_day01_05"


def test_detail_brushes_are_grouped_in_func_detail(opened):
    doc, _ = opened
    detail = next(e for e in doc.entities() if e.classname == "func_detail")
    ramp = doc.children(detail.id)
    assert len(ramp) == 1 and ramp[0].is_valid()
    bb = ramp[0].bbox()
    assert (bb.mins, bb.maxs) == ((0, 0, 0), (512, 1024, 256))


def test_brush_entity_keeps_its_brush_and_outputs(opened):
    doc, _ = opened
    tele = next(e for e in doc.entities() if e.classname == "trigger_teleport")
    assert tele.get("target") == "dest" and tele.get("model") == "" and tele.get("classname") == ""
    assert [s.faces[0].material for s in doc.children(tele.id)] == ["TOOLS/TOOLSTRIGGER"]
    out = tele.outputs[0]
    assert (out.output, out.target, out.input, out.parameter, out.delay, out.times) == \
        ("OnStartTouch", "!activator", "AddOutput", "gravity 1", 0.5, 1)


def test_point_entities(opened):
    doc, report = opened
    names = sorted(e.classname for e in doc.entities())
    assert names == ["func_detail", "info_player_counterterrorist", "info_teleport_destination", "light",
                     "trigger_teleport"]
    assert report.entities == 5


def test_static_props_become_entities():
    from types import SimpleNamespace

    from srctools.math import Angle, Vec

    prop = SimpleNamespace(model="models/props/cs_office/plant01.mdl", origin=Vec(32, 48, 0.5),
                           angles=Angle(0, 45, 0), skin=1, solidity=6, min_fade=0.0, max_fade=0.0, scaling=1.0)
    report = bsp_io.BspReport()
    [ent] = bsp_io._static_props(SimpleNamespace(props=[prop]), report)
    assert isinstance(ent, Entity) and ent.classname == "prop_static"
    assert ent.get("origin") == "32 48 0.5" and ent.get("angles") == "0 45 0" and ent.get("skin") == "1"


def test_broken_file_reports_error(tmp_path):
    bad = tmp_path / "kaputt.bsp"
    bad.write_bytes(b"not a bsp at all")
    with pytest.raises(BspError):
        load_bsp(bad)


def test_imported_solids_are_solid_objects(opened):
    doc, _ = opened
    assert all(isinstance(s, Solid) and s.is_valid() for s in doc.solids())


def test_cubemap_patched_materials_get_their_real_names():
    assert original_material("MAPS/SURF_X/CONCRETE/WALL01_-128_256_64") == "CONCRETE/WALL01"
    assert original_material("MAPS/SURF_X/NATURE/BLEND01_WVT_PATCH") == "NATURE/BLEND01"
    assert original_material("MAPS/SURF_X/WATER/WATER01_DEPTH_128") == "WATER/WATER01"
    assert original_material("CONCRETE/WALL01") == "CONCRETE/WALL01"
    # Ohne Suffix bleibt der Name, wie er ist
    assert original_material("MAPS/SURF_X/EIGENES") == "MAPS/SURF_X/EIGENES"


def test_bsp_faces_use_unpatched_material(tmp_path):
    path = build_bsp(tmp_path / "surf_patch.bsp", world_mat="maps/surf_patch/dev/dev_measuregeneric01_0_0_64")
    doc, _ = load_bsp(path)
    mats = {f.material for s in doc.solids() for f in s.faces}
    assert "DEV/DEV_MEASUREGENERIC01" in mats
    assert not any(m.startswith("MAPS/") for m in mats)


def test_packed_materials_are_extracted(tmp_path):
    path = build_bsp(tmp_path / "surf_pack.bsp", pack={
        "materials/eigen/rampe.vmt": b'"LightmappedGeneric" { "$basetexture" "eigen/rampe" }',
        "materials/eigen/rampe.vtf": b"VTF",
        "materials/maps/surf_pack/eigen/rampe_0_0_0.vmt": b"patch",
        "materials/maps/surf_pack/c0_0_0.vtf": b"cubemap",
        "sound/musik.wav": b"RIFF",
    })
    target = tmp_path / "aus"
    assert extract_materials(path, target) == 2
    assert (target / "materials/eigen/rampe.vmt").read_bytes().startswith(b'"LightmappedGeneric"')
    assert not (target / "materials/maps").exists() and not (target / "sound").exists()
    # Ohne Pakfile: nichts
    assert extract_materials(build_bsp(tmp_path / "leer.bsp"), tmp_path / "leer") == 0
