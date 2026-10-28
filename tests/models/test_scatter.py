"""Props streuen: Kits finden Modelle des Spiels, Streuen auf Boden und Gelände, Abstand, Hänge."""
import math
import random

import numpy as np
import pytest

from rampenschmiede.core.blocks import insert_block
from rampenschmiede.core.commands import solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.model import MapDocument
from rampenschmiede.core.models.props import angle_matrix, entity_angles
from rampenschmiede.core.models.scatter import (
    KITS,
    KITS_BY_KEY,
    STYLE_KITS,
    Ground,
    ScatterSettings,
    aligned_angles,
    kit_models,
    props_in_circle,
    scatter,
)
from rampenschmiede.core.surf.catalog import Placement


def test_kits_match_by_pattern_and_skip_gibs():
    names = ["models/props_foliage/tree_pine04.mdl", "models/props_foliage/tree_gib01.mdl",
             "models/props_c17/oildrum001.mdl", "models/props_wasteland/rockgranite02a.mdl",
             "models/props/de_inferno/cactus.mdl", "models/props_foliage/bush2.mdl"]
    assert kit_models(KITS_BY_KEY["wald"], names) == ["models/props_foliage/tree_pine04.mdl",
                                                      "models/props_foliage/bush2.mdl"]
    assert kit_models(KITS_BY_KEY["industrie"], names) == ["models/props_c17/oildrum001.mdl"]
    assert kit_models(KITS_BY_KEY["felsen"], names) == ["models/props_wasteland/rockgranite02a.mdl"]
    assert KITS_BY_KEY["felsen"].align and not KITS_BY_KEY["wald"].align
    assert set(STYLE_KITS.values()) <= {k.key for k in KITS}


def _floor(doc, top=0, size=1024):
    return solids_from_faces(doc, primitives.block((-size // 2, -size // 2, top - 16), (size // 2, size // 2, top)))


def test_scatter_on_floor_keeps_spacing_and_is_repeatable():
    doc = MapDocument()
    ground = Ground(_floor(doc, top=64))
    s = ScatterSettings(radius=256, count=8, spacing=64)
    props = scatter(doc, ground, (0, 0, 64), ["models/a.mdl", "models/b.mdl"], None, s, random.Random(3))
    assert 4 <= len(props) <= 8
    pts = [p.origin for p in props]
    assert all(z == 62 for _, _, z in pts)  # 2 Units eingesunken
    assert all(math.hypot(x, y) <= 256 + 1 for x, y, _ in pts)
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            assert math.hypot(a[0] - b[0], a[1] - b[1]) >= 64 - 1
    assert {p.get("model") for p in props} <= {"models/a.mdl", "models/b.mdl"}
    again = scatter(doc, ground, (0, 0, 64), ["models/a.mdl", "models/b.mdl"], None, s, random.Random(3))
    assert [p.origin for p in again] == pts
    doc._insert(props)
    # Neben schon gesetzten Props wird es enger
    more = scatter(doc, ground, (0, 0, 64), ["models/a.mdl"], None, ScatterSettings(radius=64, count=5, spacing=200),
                   random.Random(1))
    assert more == []
    assert set(props_in_circle(doc, (0, 0, 0), 300)) == {p.id for p in props}
    assert props_in_circle(doc, (0, 0, 0), 300, ["models/a.mdl"]) == [p.id for p in props
                                                                       if p.get("model") == "models/a.mdl"]


def test_steep_and_tool_surfaces_stay_free():
    doc = MapDocument()
    ramp = solids_from_faces(doc, primitives.wedge((-512, -512, 0), (512, 512, 1024)))  # ~45°
    assert scatter(doc, Ground(ramp), (0, 0, 512), ["models/a.mdl"], None,
                   ScatterSettings(radius=200, count=5, spacing=0, max_slope=35), random.Random(0)) == []
    clip = solids_from_faces(doc, primitives.block((-512, -512, 0), (512, 512, 16), "TOOLS/TOOLSPLAYERCLIP"))
    assert Ground(clip).height(0, 0, 100, 200) is None


def test_scatter_on_terrain_follows_the_hill_and_aligns():
    doc = MapDocument()
    hill, _ = insert_block(doc, "gelaende_huegel", None, Placement(-512, 0, 0, 0))
    ground = Ground(hill + _floor(doc, top=-1000), terrain_only=True)
    assert len(ground.solids) == 1
    top = ground.height(0, 0, 2000, 4000)
    assert top == pytest.approx(16 + 192, abs=1)
    s = ScatterSettings(radius=300, count=6, spacing=32, max_slope=60, align=True, sink=0)
    props = scatter(doc, ground, (0, 0, 200), ["models/rock.mdl"], None, s, random.Random(5))
    assert props
    for p in props:
        x, y, z = p.origin
        assert z == pytest.approx(ground.height(x, y, 2000, 4000), abs=1)
        up = np.asarray(angle_matrix(*entity_angles(p))) @ (0, 0, 1)
        n = ground.normal(x, y, z)
        assert up @ np.asarray(n) > 0.98


def test_aligned_angles_point_the_model_up_along_the_normal():
    for n in [(0.3, 0.2, 0.93), (-0.5, 0.1, 0.86), (0.6, -0.7, 0.4)]:
        n = np.asarray(n) / np.linalg.norm(n)
        for yaw in (0, 40, 200):
            m = np.asarray(angle_matrix(*aligned_angles(tuple(n), yaw)))
            assert np.allclose(m @ (0, 0, 1), n, atol=1e-3)
