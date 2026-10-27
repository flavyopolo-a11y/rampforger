"""Himmel aus der Material-Bibliothek und die Licht-Vorschau im Shader."""
import numpy as np
import pytest
from srctools.vpk import VPK

from rampenschmiede.core.commands import solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.lights import collect_lights
from rampenschmiede.core.materials import MaterialLibrary
from rampenschmiede.core.model import Entity, MapDocument
from rampenschmiede.render.camera import Camera3D
from rampenschmiede.render.scene_mesh import MARKER_LAYER, SceneMesh, build_object_mesh
from rampenschmiede.render.sky import SKY_SUFFIXES, SkyCache, SkyImages, available_skies, load_sky

from ..materials.fakegame import make_game, vmt_text, vtf_bytes

#: Farbe je Seite in der Reihenfolge der Shader-Ebenen (rt, lf, bk, ft, up, dn)
SIDE_COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255)]


@pytest.fixture
def sky_lib(tmp_path):
    game = make_game(tmp_path)
    pak = VPK(game / "pak02_dir.vpk", mode="w")
    for suffix, color in zip(SKY_SUFFIXES, SIDE_COLORS):
        size = (4, 4) if suffix == "dn" else (64, 64)  # Platzhalter unten wie bei vielen Himmeln
        pak.add_file("materials/skybox/testskyrt.vmt".replace("rt", suffix),
                     vmt_text(f"skybox/testsky{suffix}", "UnlitGeneric").encode())
        pak.add_file(f"materials/skybox/testsky{suffix}.vtf", vtf_bytes((*color, 255), size))
    # Unvollständiger Himmel: nur oben
    pak.add_file("materials/skybox/kaputtup.vmt", vmt_text("skybox/kaputtup", "UnlitGeneric").encode())
    pak.write_dirfile()
    return MaterialLibrary.for_game(game)


def test_available_skies_need_all_sides(sky_lib):
    assert available_skies(sky_lib) == ["testsky"]
    assert available_skies(None) == []


def test_load_sky_fills_missing_bottom(sky_lib):
    sky = load_sky(sky_lib, "testsky")
    assert sky is not None and len(sky.layers) == 6
    assert sky.layers[0][:3] == bytes((255, 0, 0))
    # Unten fehlt (4×4-Platzhalter): Farbe vom unteren Rand der Seiten
    assert len(sky.layers[5]) == sky.size * sky.size * 4
    assert load_sky(sky_lib, "gibtsnicht") is None


def test_sky_cache_loads_once_per_name(sky_lib):
    cache = SkyCache()
    first = cache.get(sky_lib, "testsky")
    assert cache.get(sky_lib, "TESTSKY") is first and cache.generation == 1
    assert cache.get(sky_lib, "anderer") is None and cache.generation == 2


def _block(doc, mins, maxs, material):
    return solids_from_faces(doc, primitives.block(mins, maxs, material))[0]


def test_skybox_faces_and_entities_are_marked_in_mesh():
    doc = MapDocument()
    sky = build_object_mesh(_block(doc, (0, 0, 0), (64, 64, 64), "TOOLS/TOOLSSKYBOX"))
    assert set(sky.tris[:, 11]) == {-1.0}
    light = build_object_mesh(Entity(id=5, classname="light", keyvalues=(("origin", "0 0 0"),
                                                                       ("_light", "255 0 0 200"))))
    assert set(light.tris[:, 11]) == {MARKER_LAYER}
    assert tuple(light.tris[0, 6:9]) == (1.0, 0.0, 0.0)  # Kästchen in Lichtfarbe


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


def _shot(gl, cam, doc, mode, lights=None, sky=None):
    ctx, renderer = gl
    renderer.sync(SceneMesh(doc).arrays())
    fbo = ctx.simple_framebuffer((64, 64))
    renderer.draw_3d(fbo, cam, 64, 64, mode, lights=lights, sky=sky)
    return np.frombuffer(fbo.read(components=3), dtype=np.uint8).reshape(64, 64, 3)


def test_light_preview_brightens_near_the_light(gl):
    doc = MapDocument()
    doc._insert([_block(doc, (-2048, -2048, -16), (2048, 2048, 0), "DEV/DEV_MEASUREGENERIC01B")])
    doc._insert([Entity(id=doc.new_id(), classname="light",
                        keyvalues=(("origin", "300 0 48"), ("_light", "255 255 255 300")))])
    cam = Camera3D(np.array([0.0, 0.0, 1200.0]), yaw=0, pitch=-89.9)
    img = _shot(gl, cam, doc, "lit", collect_lights(doc)).astype(int).sum(axis=2)
    # Beim Licht ist der Boden hell, am Bildrand weit weg davon dunkel
    row, col = np.unravel_index(np.argmax(img), img.shape)
    assert img[row, col] > 300
    far = img[:, :6].max()
    assert far < 30
    # Ohne Lichter: voll hell wie im Spiel
    flat = _shot(gl, cam, doc, "lit", collect_lights(MapDocument())).astype(int).sum(axis=2)
    assert flat[:, :6].min() > 300


def test_sky_background_matches_engine_sides(gl):
    sky = SkyImages("t", tuple(bytes((*c, 255)) * 256 for c in SIDE_COLORS), 16)
    cam = Camera3D(np.array([0.0, 0.0, 0.0]), pitch=0)
    seen = {}
    for name, yaw, pitch in (("+X", 0, 0), ("+Y", 90, 0), ("-X", 180, 0), ("-Y", 270, 0), ("oben", 0, 89),
                             ("unten", 0, -89)):
        cam.yaw, cam.pitch = yaw, pitch
        seen[name] = tuple(int(c) for c in _shot(gl, cam, MapDocument(), "textured", sky=sky)[32, 32])
    # rt = +X, lf = -X, bk = +Y, ft = -Y (Skybox-Tabelle der Engine)
    assert seen == {"+X": SIDE_COLORS[0], "-X": SIDE_COLORS[1], "+Y": SIDE_COLORS[2], "-Y": SIDE_COLORS[3],
                    "oben": SIDE_COLORS[4], "unten": SIDE_COLORS[5]}
