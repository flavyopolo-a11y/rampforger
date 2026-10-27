"""Materialien aus VPKs und Ordnern lesen."""
from rampenschmiede.core.materials import PREVIEW_SIZE, MaterialLibrary, normalize

from .fakegame import make_game, vmt_text, vtf_bytes


def test_normalize():
    assert normalize("materials\\Dev/Foo.VMT") == "dev/foo"
    assert normalize("TOOLS/TOOLSNODRAW") == "tools/toolsnodraw"


def test_index_lists_vpk_and_loose_materials(tmp_path):
    lib = MaterialLibrary.for_game(make_game(tmp_path))
    assert lib.names() == ["lose/blau", "test/flicken", "test/gruen", "test/rot"]
    assert lib.exists("TEST/ROT") and not lib.exists("test/fehlt")


def test_material_info_and_patch(tmp_path):
    lib = MaterialLibrary.for_game(make_game(tmp_path))
    rot = lib.material("Test/Rot")
    assert rot.basetexture == "test/rot" and rot.keywords == ("surf", "rot") and not rot.translucent
    assert lib.material("test/gruen").translucent
    patched = lib.material("test/flicken")
    assert patched.basetexture == "test/rot" and patched.surfaceprop == "metal"
    assert lib.material("test/fehlt") is None


def test_texture_is_rgba_and_shrunk(tmp_path):
    lib = MaterialLibrary.for_game(make_game(tmp_path))
    img = lib.texture("test/rot")
    assert (img.width, img.height, img.source_width, img.source_height) == (64, 32, 64, 32)
    assert img.rgba[:4] == bytes((255, 0, 0, 255)) and len(img.rgba) == 64 * 32 * 4
    big = lib.texture("test/gruen")
    assert max(big.width, big.height) <= PREVIEW_SIZE and (big.source_width, big.source_height) == (512, 512)
    assert big.rgba[1] == 255
    assert lib.texture("lose/blau").rgba[2] == 255


def test_extra_folder_overrides_game(tmp_path):
    own = tmp_path / "eigene"
    (own / "materials" / "test").mkdir(parents=True)
    (own / "materials" / "test" / "rot.vmt").write_text(vmt_text("test/eigen"), encoding="utf-8")
    (own / "materials" / "test" / "eigen.vtf").write_bytes(vtf_bytes((10, 20, 30, 255)))
    lib = MaterialLibrary.for_game(make_game(tmp_path), [own])
    assert lib.material("test/rot").basetexture == "test/eigen"
    assert lib.texture("test/rot").rgba[:3] == bytes((10, 20, 30))


def test_missing_game_gives_empty_library(tmp_path):
    lib = MaterialLibrary.for_game(tmp_path / "gibtsnicht")
    assert lib.names() == [] and lib.material("dev/x") is None and lib.texture("dev/x") is None
