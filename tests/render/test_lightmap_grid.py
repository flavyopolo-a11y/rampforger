"""Lightmap-Raster: Koordinaten wie bei vbsp, Werkzeug-Seiten ohne Lightmap."""
import dataclasses

import numpy as np
import pytest

from rampenschmiede.core.commands import solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.model import MapDocument, TexAxis
from rampenschmiede.render.scene_mesh import (
    FACE_COLUMNS,
    LIGHTMAP_COLUMN,
    build_object_mesh,
    lightmap_coords,
)


def block(material, scale=16):
    solid = solids_from_faces(MapDocument(), primitives.block((0, 0, 0), (64, 64, 64), material))[0]
    return dataclasses.replace(solid, faces=tuple(dataclasses.replace(f, lightmapscale=scale) for f in solid.faces))


def test_coords_use_unit_axes_and_scale():
    (face,) = [f for f in block("TEST/ROT", 8).faces if f.plane.normal[2] > 0.5]
    # Texturskalierung spielt keine Rolle, nur die Richtung der Achse
    face = dataclasses.replace(face, uaxis=TexAxis(2, 0, 0, 16, 0.25), vaxis=TexAxis(0, -1, 0, 0, 4))
    s, t, scale = lightmap_coords(face, np.asarray([(64.0, 32.0, 64.0)]))[0]
    assert (s, t, scale) == pytest.approx((8.0, -4.0, 8.0))


def test_mesh_rows_carry_lightmap():
    rows, _ = build_object_mesh(block("TEST/ROT", 32)).variant(False)
    assert rows.shape[1] == FACE_COLUMNS
    assert np.all(rows[:, LIGHTMAP_COLUMN + 2] == 32)
    # Ecken einer Seite: Abstand 64 Units = 2 Luxel bei Skalierung 32
    span = rows[:6, LIGHTMAP_COLUMN:LIGHTMAP_COLUMN + 2].max(axis=0) - rows[:6, LIGHTMAP_COLUMN:LIGHTMAP_COLUMN + 2].min(axis=0)
    assert span.max() == pytest.approx(2.0)


def test_tool_faces_have_no_lightmap():
    rows, _ = build_object_mesh(block("TOOLS/TOOLSTRIGGER")).variant(True)
    assert np.all(rows[:, LIGHTMAP_COLUMN + 2] == 0)
