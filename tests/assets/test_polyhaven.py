"""Poly Haven: Liste, Dateien, Umwandlung in Source-Material und Skybox."""
import io

from PIL import Image
from srctools import vmt, vtf

from rampenschmiede.core.assets.convert import (
    equirect_faces,
    face_directions,
    skybox_from_panorama,
    surfaceprop_for,
    texture_material,
)
from rampenschmiede.core.assets.polyhaven import USER_AGENT, PolyHaven, sky_url, texture_urls
from rampenschmiede.core.commands import AddObjects, SetWorldKeyvalues
from rampenschmiede.core.decals import make_overlay
from rampenschmiede.core.materials.authoring import used_materials
from rampenschmiede.core.model import MapDocument

from .fake_polyhaven import FakeNet, panorama


def test_list_categories_and_cache(tmp_path):
    net = FakeNet()
    ph = PolyHaven(tmp_path, net)
    assets = ph.assets("textures")
    assert [a.id for a in assets] == ["red_brick_03", "rocky_ground"]
    assert assets[0].matches("brick red") and not assets[0].matches("rock")
    assert ph.categories("textures")[0] in ("rock", "brick", "wall") and "all" not in ph.categories("textures")
    url = assets[0].thumbnail
    ph.download(url)
    ph.download(url)
    assert net.calls.count(url) == 1  # zweites Mal aus dem Zwischenspeicher
    assert "Rampenschmiede" in USER_AGENT


def test_pick_files(tmp_path):
    ph = PolyHaven(tmp_path, FakeNet())
    diffuse, normal = texture_urls(ph.files("red_brick_03"))
    assert diffuse.endswith("diff_1k.jpg") and normal.endswith("nor_dx_1k.jpg")
    assert sky_url(ph.files("moonless_golf")).endswith("moonless_golf.jpg")
    assert texture_urls({}) == (None, None) and sky_url({}) is None


def test_texture_material_with_bumpmap(tmp_path):
    net = FakeNet()
    name = texture_material(tmp_path, "red_brick_03", net.data["https://dl.polyhaven.org/red_brick_03_diff_1k.jpg"],
                            net.data["https://dl.polyhaven.org/red_brick_03_nor_dx_1k.jpg"], surfaceprop_for(["brick"]))
    assert name == "rampenschmiede/frei/red_brick_03"
    folder = tmp_path / "materials" / "rampenschmiede" / "frei"
    mat = vmt.Material.parse((folder / "red_brick_03.vmt").read_text().splitlines())
    assert mat.shader.lower() == "lightmappedgeneric"
    assert mat.get("$bumpmap") == name + "_normal" and mat.get("$surfaceprop") == "brick"
    with open(folder / "red_brick_03_normal.vtf", "rb") as f:
        assert vtf.VTFFlags.NORMAL in vtf.VTF.read(f).flags
    assert (folder / "LIZENZ.txt").read_text().startswith("Diese Dateien stammen von Poly Haven")


def test_face_directions_match_their_axes():
    axes = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
    for face, axis in enumerate(axes):
        d = face_directions(face, 4)
        center = (d[1, 1] + d[2, 2]) / 2
        assert [round(c) for c in center] == list(axis)


def test_panorama_to_skybox_orientation():
    faces = equirect_faces(Image.open(io.BytesIO(panorama())), 32)
    px = [f.getpixel((16, 16)) for f in faces]
    rt, lf, bk, ft, up, dn = px
    assert rt[0] > 200 and rt[1] < 60       # Blick +X: rote Mitte des Bildes
    assert bk[1] > 200 and bk[0] < 60       # +Y liegt im Bild links von der Mitte: grün
    assert up == (255, 255, 255) or min(up) > 230
    assert max(dn) < 30


def test_skybox_files_and_packing(tmp_path):
    sky = skybox_from_panorama(tmp_path, "moonless_golf", panorama(), 64)
    assert sky == "rs_moonless_golf"
    for s in ("rt", "lf", "bk", "ft", "up", "dn"):
        assert (tmp_path / "materials" / "skybox" / f"{sky}{s}.vtf").is_file()
        text = (tmp_path / "materials" / "skybox" / f"{sky}{s}.vmt").read_text()
        assert "UnlitGeneric" in text and f"skybox/{sky}{s}" in text
    doc = MapDocument()
    SetWorldKeyvalues((("skyname", sky),)).do(doc)
    ov = make_overlay(doc, (0, 0, 0), (0, 0, 1), "rampenschmiede/frei/red_brick_03", 64, 64)
    AddObjects([ov]).do(doc)
    used = used_materials(doc)
    assert f"skybox/{sky}up" in used and "rampenschmiede/frei/red_brick_03" in {u.lower() for u in used}
