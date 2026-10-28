"""Props in den Ansichten: Modell-Dreiecke an Position und Drehung, Texturen je Skin, Ausschnitte."""
import numpy as np
import pytest

from rampenschmiede.core.materials import MaterialLibrary
from rampenschmiede.core.model import Entity, MapDocument
from rampenschmiede.core.models.library import ModelLibrary
from rampenschmiede.render.camera import Camera3D
from rampenschmiede.render.model_preview import render_preview
from rampenschmiede.render.scene_mesh import MARKER_LAYER, SceneMesh, build_object_mesh
from rampenschmiede.render.textures import CUTOUT_ALPHATEST, TextureAtlas

from ..models.mdl_builder import write_cube_model, write_material

RED, BLUE = (250, 0, 0), (0, 0, 250)


@pytest.fixture
def game(tmp_path):
    write_material(tmp_path, "models/test/crate_top", RED)
    write_material(tmp_path, "models/test/crate_side", BLUE)
    write_cube_model(tmp_path)
    lib = MaterialLibrary.for_game(None, [tmp_path])
    return lib, ModelLibrary(lib)


def prop(origin="100 0 0", angles="0 90 0", skin="0", model="models/test/crate.mdl"):
    return Entity(id=7, classname="prop_static",
                  keyvalues=(("origin", origin), ("angles", angles), ("model", model), ("skin", skin)))


def test_prop_mesh_is_placed_and_textured(game):
    lib, models = game
    atlas = TextureAtlas(lib)
    mesh = build_object_mesh(prop(), atlas, models=models)
    assert mesh.tris.shape == (36, 12)
    pos = mesh.tris[:, 0:3]
    # Würfel −16…16 um den Ursprung, um 90° gedreht und nach x = 100 verschoben
    assert np.allclose(pos.min(axis=0), (84, -16, 0)) and np.allclose(pos.max(axis=0), (116, 16, 32))
    layers = set(mesh.tris[:, 11].tolist())
    assert layers == {float(atlas.slot("models/test/crate_top").layer), float(atlas.slot("models/test/crate_side").layer)}
    assert len(mesh.lines) == 24  # zwölf Würfelkanten, Nähte zwischen den Seiten zählen nicht
    assert len(mesh.edges_3d()) == 0


def test_skin_swaps_textures(game):
    lib, models = game
    atlas = TextureAtlas(lib)
    top = float(atlas.slot("models/test/crate_top").layer)
    a = build_object_mesh(prop(skin="0"), atlas, models=models).tris
    b = build_object_mesh(prop(skin="1"), atlas, models=models).tris
    up = a[:, 5] > 0.9  # Dreiecke der Oberseite
    assert set(a[up, 11]) == {top} and top not in set(b[up, 11])


def test_without_models_or_missing_model_a_marker_box(game):
    lib, models = game
    assert set(build_object_mesh(prop()).tris[:, 11]) == {MARKER_LAYER}
    missing = build_object_mesh(prop(model="models/none.mdl"), TextureAtlas(lib), models=models)
    assert set(missing.tris[:, 11]) == {MARKER_LAYER}


def test_scene_rebuilds_when_models_arrive(game):
    lib, models = game
    doc = MapDocument()
    doc._insert([prop()])
    scene = SceneMesh(doc, TextureAtlas(lib))
    assert len(scene.arrays().faces) == 36  # Kästchen: sechs Seiten, je zwei Dreiecke
    scene.set_models(models)
    faces = scene.arrays().faces
    assert len(faces) == 36 and MARKER_LAYER not in set(faces[:, 11])


def test_alphatest_material_gets_cutout_layer(tmp_path):
    write_material(tmp_path, "models/test/leaves", (0, 200, 0), alpha=0, extra='"$alphatest" "1"')
    atlas = TextureAtlas(MaterialLibrary.for_game(None, [tmp_path]))
    slot = atlas.slot("models/test/leaves")
    assert slot.cutout == CUTOUT_ALPHATEST and slot.shader_layer == slot.layer + CUTOUT_ALPHATEST


def test_preview_colors_follow_skin(game):
    lib, models = game
    model = models.load("models/test/crate.mdl")
    img = np.frombuffer(render_preview(model, lib, 64, yaw=30, pitch=80), dtype=np.uint8).reshape(64, 64, 4)
    r, g, b = img[32, 32, :3].astype(int)
    assert r > 150 and b < 60  # von oben: rote Oberseite
    img = np.frombuffer(render_preview(model, lib, 64, yaw=30, pitch=80, skin=1), dtype=np.uint8).reshape(64, 64, 4)
    r, g, b = img[32, 32, :3].astype(int)
    assert b > 150 and r < 60


@pytest.fixture
def gl():
    moderngl = pytest.importorskip("moderngl")
    try:
        ctx = moderngl.create_standalone_context()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"kein OpenGL: {exc}")
    from rampenschmiede.render.gl_renderer import ViewportRenderer

    renderer = ViewportRenderer(ctx)
    yield ctx, renderer
    renderer.release()
    ctx.release()


def _shot(gl, scene, atlas):
    ctx, renderer = gl
    renderer.sync(scene.arrays(), atlas)
    fbo = ctx.simple_framebuffer((64, 64))
    cam = Camera3D(np.array([100.0, 0.0, 400.0]), yaw=0, pitch=-89.9)
    renderer.draw_3d(fbo, cam, 64, 64, "textured")
    return np.frombuffer(fbo.read(components=3), dtype=np.uint8).reshape(64, 64, 3).astype(int)


def test_gl_draws_prop_texture_and_cuts_out_alphatest(gl, tmp_path):
    write_material(tmp_path, "models/test/crate_top", RED, alpha=0, extra='"$alphatest" "1"')
    write_material(tmp_path, "models/test/crate_side", BLUE)
    write_cube_model(tmp_path)
    lib = MaterialLibrary.for_game(None, [tmp_path])
    atlas = TextureAtlas(lib)
    doc = MapDocument()
    doc._insert([prop()])
    scene = SceneMesh(doc, atlas, ModelLibrary(lib))
    img = _shot(gl, scene, atlas)
    r, g, b = img[32, 32]
    # Die Oberseite ist ausgeschnitten: man sieht durch sie auf die blaue Innenseite des Bodens
    assert b > 2 * r and b > 40
