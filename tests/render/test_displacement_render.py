"""Gelände in den Ansichten: nur die Displacement-Fläche, Raster in 2D, zweite Textur überblendet."""
import dataclasses

import numpy as np
import pytest

from rampenschmiede.core.commands import solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.geometry.displacement import (
    brush_stroke,
    make_displacement,
    set_surface,
    surfaces,
)
from rampenschmiede.core.materials import MaterialLibrary
from rampenschmiede.core.model import MapDocument
from rampenschmiede.render.camera import Camera3D
from rampenschmiede.render.scene_mesh import FACE_COLUMNS, SceneMesh, build_object_mesh
from rampenschmiede.render.textures import TextureAtlas

from ..models.mdl_builder import write_material

RED, GREEN = (250, 0, 0), (0, 250, 0)


def terrain(doc, material="", power=2, hi=(256, 256, 16)):
    s = solids_from_faces(doc, primitives.block((0, 0, 0), hi, material=material) if material
                          else primitives.block((0, 0, 0), hi))[0]
    top = max(range(6), key=lambda k: s.faces[k].plane.normal[2])
    return make_displacement(s, top, power)


@pytest.fixture
def blend_lib(tmp_path):
    write_material(tmp_path, "nature/blend_a", RED, extra='"$basetexture2" "nature/blend_b"')
    write_material(tmp_path, "nature/blend_b", GREEN)
    return MaterialLibrary.for_game(None, [tmp_path])


def test_only_the_displacement_is_drawn_with_grid_lines():
    doc = MapDocument()
    s = terrain(doc)
    (surf,) = surfaces(s)
    s = set_surface(s, surf, brush_stroke(surf, (128, 128, 16), 100, 40, "heben"))
    mesh = build_object_mesh(s)
    assert mesh.tris.shape == (4 * 4 * 2 * 3, 14)  # Power 2: 4 × 4 Felder, kein Kasten
    assert mesh.tris[:, 2].max() == pytest.approx(56)
    assert mesh.tris[:, 5].min() > 0  # Normalen zeigen nach oben
    assert len(mesh.lines) == 2 * 2 * 5 * 4  # fünf Zeilen und fünf Spalten mit je vier Stücken
    assert len(mesh.edges_3d()) == 2 * 4 * 4  # in 3D nur der Rand
    # Die Hülle umfasst den Hügel, damit Auswahl und Picking ihn treffen
    assert s.bbox().maxs[2] == pytest.approx(56)


def test_blend_material_gets_second_layer_and_alpha(blend_lib):
    atlas = TextureAtlas(blend_lib)
    doc = MapDocument()
    s = terrain(doc, "nature/blend_a")
    (surf,) = surfaces(s)
    s = set_surface(s, surf, dataclasses.replace(surf.disp, alphas=np.full(25, 255.0)))
    tris = build_object_mesh(s, atlas).tris
    assert set(tris[:, 11]) == {float(atlas.slot("nature/blend_a").layer)}
    assert set(tris[:, 12]) == {float(atlas.slot2("nature/blend_a").layer)}
    assert set(tris[:, 13]) == {1.0}
    assert atlas.slot2("nature/blend_b") is None
    doc._insert([s])
    assert SceneMesh(doc, atlas).arrays().faces.shape == (96, FACE_COLUMNS)


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


def test_gl_blends_to_the_second_texture(gl, blend_lib):
    ctx, renderer = gl
    atlas = TextureAtlas(blend_lib)
    doc = MapDocument()
    s = terrain(doc, "nature/blend_a")
    (surf,) = surfaces(s)
    alphas = np.zeros(25)
    alphas[[i * 5 + j for i in range(5) for j in range(3, 5)]] = 255  # Spalten 3 und 4: x ≥ 192
    s = set_surface(s, surf, dataclasses.replace(surf.disp, alphas=alphas))
    doc._insert([s])
    renderer.sync(SceneMesh(doc, atlas).arrays(), atlas)
    fbo = ctx.simple_framebuffer((64, 64))
    cam = Camera3D(np.array([128.0, 128.0, 600.0]), yaw=0, pitch=-89.9)
    renderer.draw_3d(fbo, cam, 64, 64, "textured")
    img = np.frombuffer(fbo.read(components=3), dtype=np.uint8).reshape(64, 64, 3).astype(int)
    # Kamera blickt nach unten, +X zeigt im Bild nach oben: entlang der Mitte rot, dann grün
    line = img[:, 32]
    assert any(p[0] > 150 and p[1] < 40 for p in line)
    assert any(p[1] > 150 and p[0] < 40 for p in line)
