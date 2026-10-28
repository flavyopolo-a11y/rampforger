"""Texturkoordinaten und Textur-Ebenen in den Meshes der 3D-Ansicht."""
import pytest

from rampenschmiede.core.commands import solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.materials import MaterialLibrary
from rampenschmiede.core.model import MapDocument, TexAxis
from rampenschmiede.render.scene_mesh import FACE_COLUMNS, SceneMesh, _uv, build_object_mesh
from rampenschmiede.render.textures import LAYER_SIZE, TextureAtlas

from ..materials.fakegame import make_game


@pytest.fixture
def atlas(tmp_path):
    return TextureAtlas(MaterialLibrary.for_game(make_game(tmp_path)))


def block(material, doc=None):
    doc = doc or MapDocument()
    return solids_from_faces(doc, primitives.block((0, 0, 0), (64, 64, 64), material))[0]


def test_uv_follows_source_formula():
    (face,) = [f for f in block("TEST/ROT").faces if f.plane.normal[2] > 0.5]
    face = face.__class__(face.points, face.material, TexAxis(1, 0, 0, 16, 0.5), TexAxis(0, -1, 0, 0, 0.25))
    u, v = _uv(face, (64, 32, 64), (64, 32))
    assert u == pytest.approx((64 / 0.5 + 16) / 64)
    assert v == pytest.approx((-32 / 0.25) / 32)


def test_layers_are_shared_per_material(atlas):
    a = atlas.slot("test/rot")
    assert a.layer == 1 and (a.width, a.height) == (64, 32)
    assert atlas.slot("TEST/ROT") is a
    assert atlas.slot("test/gruen").layer == 2
    assert atlas.slot("gibt/esnicht") is None
    assert atlas.layer_count == 3 and len(atlas.layer_data(2)) == LAYER_SIZE * LAYER_SIZE * 4


def test_mesh_carries_layer_and_falls_back_to_color(atlas):
    mesh = build_object_mesh(block("TEST/ROT"), atlas)
    assert mesh.tris.shape[1] == 12 and set(mesh.tris[:, 11]) == {1.0}
    plain = build_object_mesh(block("TOOLS/TOOLSNODRAW"), atlas)
    assert set(plain.tris[:, 11]) == {0.0}


def test_new_library_rebuilds_meshes(atlas, tmp_path):
    doc = MapDocument()
    doc._insert([block("LOSE/BLAU", doc)])
    scene = SceneMesh(doc, atlas)
    assert scene.arrays().faces.shape[1] == FACE_COLUMNS and scene.arrays().faces[0, 11] == 1.0
    atlas.set_library(None)
    assert scene.arrays().faces[0, 11] == 0.0
