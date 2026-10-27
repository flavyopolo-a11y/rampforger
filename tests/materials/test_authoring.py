"""Eigene Texturen: Import, Farb-Texturen und Packen in die BSP."""
from PIL import Image

from rampenschmiede.core.compile import CompileSettings, ToolStep, WriteStep, build_plan
from rampenschmiede.core.compile.plan import CopyFilesStep
from rampenschmiede.core.materials import MaterialLibrary
from rampenschmiede.core.materials.authoring import (
    bspzip_list,
    import_image,
    pack_list,
    ramp_material,
    safe_name,
    wall_material,
)
from rampenschmiede.core.profiles import GameProfile

from .fakegame import make_game


def test_import_png_makes_power_of_two_vtf(tmp_path):
    src = tmp_path / "Mein Bild!.png"
    Image.new("RGB", (300, 100), (10, 200, 30)).save(src)
    own = tmp_path / "eigene"
    name = import_image(own, src)
    assert name == "rampenschmiede/mein_bild"
    lib = MaterialLibrary.for_game(None, [own])
    tex = lib.texture(name)
    assert (tex.source_width, tex.source_height) == (256, 64)
    assert tex.rgba[1] > 180
    assert lib.material(name).basetexture == name


def test_import_tga_with_alpha_sets_alphatest(tmp_path):
    src = tmp_path / "gitter.tga"
    Image.new("RGBA", (64, 64), (255, 255, 255, 0)).save(src)
    own = tmp_path / "eigene"
    name = import_image(own, src)
    assert MaterialLibrary.for_game(None, [own]).material(name).translucent


def test_color_textures(tmp_path):
    own = tmp_path / "eigene"
    wall = wall_material(own, (40, 120, 220))
    ramp = ramp_material(own, (200, 60, 30), (255, 255, 255))
    assert wall == "rampenschmiede/wand_2878dc" and ramp == "rampenschmiede/rampe_c83c1e_ffffff"
    lib = MaterialLibrary.for_game(None, [own])
    assert lib.texture(ramp).source_width == 512
    assert lib.material(ramp).surfaceprop == "metal"


def test_pack_list_only_own_materials(tmp_path):
    own = tmp_path / "eigene"
    ramp = ramp_material(own, (1, 2, 3), (4, 5, 6))
    lib = MaterialLibrary.for_game(make_game(tmp_path), [own])
    files = pack_list(lib, [ramp.upper(), "TEST/ROT", "DEV/GIBTSNICHT"])
    assert [inner for inner, _ in files] == [f"materials/{ramp}.vmt", f"materials/{ramp}.vtf"]
    assert all((own / inner).is_file() for inner, _ in files)
    assert bspzip_list(files).splitlines()[0] == f"materials/{ramp}.vmt"


def _profile(tmp_path, with_bspzip):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    if with_bspzip:
        (bin_dir / "bspzip.exe").write_text("")
    return GameProfile(key="css", name="css", game_dir=str(tmp_path / "spiel"), bin_dir=str(bin_dir))


def test_plan_packs_with_bspzip_after_vrad(tmp_path):
    settings = CompileSettings(launch_game=False)
    plan = build_plan(_profile(tmp_path, True), tmp_path / "k" / "m.vmf", settings,
                      pack_files=[("materials/a.vmt", "/x/a.vmt")])
    labels = [s.label for s in plan.steps]
    assert labels.index("Packliste") < labels.index("BSPZIP") < labels.index("Kopieren")
    zip_step = next(s for s in plan.steps if isinstance(s, ToolStep) and s.tool == "bspzip")
    assert zip_step.args[0] == "-addlist" and zip_step.env["VPROJECT"].endswith("spiel")
    listing = next(s for s in plan.steps if isinstance(s, WriteStep))
    assert listing.text == "materials/a.vmt\n/x/a.vmt\n"


def test_plan_without_bspzip_copies_into_game(tmp_path):
    plan = build_plan(_profile(tmp_path, False), tmp_path / "k" / "m.vmf", CompileSettings(launch_game=False),
                      pack_files=[("materials/a.vmt", "/x/a.vmt")])
    step = next(s for s in plan.steps if isinstance(s, CopyFilesStep))
    assert step.files[0][1].endswith("materials/a.vmt") and plan.notes


def test_safe_name():
    assert safe_name("Ä b/c") == "b_c" and safe_name("!!") == "textur"
