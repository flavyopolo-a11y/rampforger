import numpy as np
import pytest
from srctools.filesys import RawFileSystem
from srctools.mdl import Flags, Model

from rampenschmiede.core.materials import MaterialLibrary
from rampenschmiede.core.model import Entity
from rampenschmiede.core.models.library import ModelLibrary, normalize_model
from rampenschmiede.core.models.mdl import ModelError, read_header
from rampenschmiede.core.models.props import (
    allowed_classes,
    angle_matrix,
    best_class,
    class_problem,
    new_prop,
    placed_bbox,
    prop_bbox,
)

from .mdl_builder import write_cube_model, write_material


@pytest.fixture
def game(tmp_path):
    write_material(tmp_path, "models/test/crate_top", (250, 0, 0))
    write_material(tmp_path, "models/test/crate_side", (0, 0, 250))
    return tmp_path


def library(root) -> ModelLibrary:
    return ModelLibrary(MaterialLibrary.for_game(None, [root]))


def test_header_matches_srctools(game):
    """Unser Testmodell ist eine gültige MDL: srctools liest dieselben Metadaten."""
    path = write_cube_model(game)
    ours = read_header(path.read_bytes())
    fs = RawFileSystem(str(game))
    theirs = Model(fs, fs["models/test/crate.mdl"])
    assert theirs.cdmaterials[0] == ours.cdmaterials[0] == "models/test/"
    assert theirs.surfaceprop == ours.surfaceprop == "metal"
    assert ours.textures == ["crate_top", "crate_side"]
    assert ours.skins == [[0, 1], [1, 0]]
    assert ours.static_prop and Flags.static_prop in theirs.flags


def test_cube_geometry(game):
    write_cube_model(game)
    m = library(game).load("models/test/crate.mdl")
    assert m is not None and m.problem == ""
    assert m.triangle_count == 12
    assert m.bounds() == ((-16.0, -16.0, 0.0), (16.0, 16.0, 32.0))
    # Material 0 auf den ersten drei Seiten (oben, +X, +Y)
    g = m.geometry
    top = g.triangles[g.tri_material == 0]
    assert len(top) == 6
    assert np.allclose(g.positions[top[:2]].reshape(-1, 3)[:, 2], 32)
    assert m.materials(0) == ["models/test/crate_top", "models/test/crate_side"]
    assert m.materials(1) == ["models/test/crate_side", "models/test/crate_top"]
    assert m.materials(7) == m.materials(0)
    assert m.has_physics and m.static_prop


@pytest.mark.parametrize("options", [{"fixups": True}, {"wide_groups": True, "groups_per_mesh": 2},
                                     {"groups_per_mesh": 3}])
def test_layout_variants(game, options):
    """Fixup-Tabelle (umsortierte Vertices) und neuere, breitere Strip-Gruppen."""
    write_cube_model(game, **options)
    m = library(game).load("models/test/crate.mdl")
    assert m.problem == "" and m.triangle_count == 12
    g = m.geometry
    tops = g.triangles[g.tri_material == 0]
    face_normals = g.normals[tops[:, 0]]
    assert {tuple(n) for n in face_normals.astype(int)} == {(0, 0, 1), (1, 0, 0), (0, 1, 0)}


def test_missing_vtx_keeps_box(game):
    path = write_cube_model(game)
    path.with_suffix("").with_suffix(".dx90.vtx").unlink()
    m = library(game).load("models/test/crate.mdl")
    assert m.geometry is None and "fehlt" in m.problem
    assert m.bounds() == ((-16, -16, 0), (16, 16, 32))  # aus dem MDL-Kopf


def test_bad_files(game):
    with pytest.raises(ModelError):
        read_header(b"nope" * 200)
    (game / "models").mkdir(exist_ok=True)
    (game / "models" / "broken.mdl").write_bytes(b"IDST" + b"\0" * 500)
    lib = library(game)
    assert lib.load("models/broken.mdl") is None
    assert lib.load("models/none.mdl") is None


def test_index_and_names(game):
    write_cube_model(game)
    write_cube_model(game, name="models/test/Barrel.mdl")
    lib = library(game)
    assert lib.names() == ["models/test/barrel.mdl", "models/test/crate.mdl"]
    assert normalize_model("Models\\Test\\Crate.MDL") == "models/test/crate.mdl"
    assert normalize_model("test/crate") == "models/test/crate.mdl"
    assert lib.exists("MODELS/TEST/CRATE.MDL")


def test_angle_matrix_like_engine():
    m = angle_matrix(0, 90, 0)  # +X des Modells zeigt nach +Y
    assert np.allclose([m[0][0], m[1][0], m[2][0]], [0, 1, 0], atol=1e-9)
    m = angle_matrix(90, 0, 0)  # positiver Nick: Nase nach unten
    assert np.allclose([m[0][0], m[1][0], m[2][0]], [0, 0, -1], atol=1e-9)
    m = angle_matrix(0, 0, 90)  # Rollen: +Y des Modells zeigt nach +Z
    assert np.allclose([m[0][1], m[1][1], m[2][1]], [0, 0, 1], atol=1e-9)


def test_prop_bbox_rotated(game):
    write_cube_model(game, size=(64, 16, 8), lo=(0, -8, 0))
    lib = library(game)
    ent = Entity(1, "prop_static", (("origin", "100 0 0"), ("angles", "0 90 0"), ("model", "models/test/crate.mdl")))
    bb = prop_bbox(ent, lib)
    assert np.allclose(bb.mins, (92, 0, 0)) and np.allclose(bb.maxs, (108, 64, 8))
    assert prop_bbox(Entity(2, "light", (("origin", "0 0 0"),)), lib) is None
    assert placed_bbox(((0, 0, 0), (1, 1, 1)), (0, 0, 0), (0, 0, 0)).maxs == (1, 1, 1)


def test_class_rules(game):
    write_cube_model(game, name="models/test/static.mdl", static=True, physics=False)
    write_cube_model(game, name="models/test/dyn.mdl", static=False, physics=True)
    lib = library(game)
    static, dyn = lib.load("models/test/static.mdl"), lib.load("models/test/dyn.mdl")
    assert best_class(static) == "prop_static" and best_class(dyn) == "prop_dynamic"
    assert "vbsp" in class_problem("prop_static", dyn)
    assert ".phy" in class_problem("prop_physics", static)
    assert allowed_classes(dyn) == {"prop_static": class_problem("prop_static", dyn), "prop_dynamic": "",
                                    "prop_physics": ""}
    ent = new_prop("models/test/dyn.mdl", (1.4, 2.6, -3), dyn, yaw=45)
    assert ent.classname == "prop_dynamic"
    assert ent.get("origin") == "1 3 -3" and ent.get("angles") == "0 45 0"
    assert ent.get("model") == "models/test/dyn.mdl"
