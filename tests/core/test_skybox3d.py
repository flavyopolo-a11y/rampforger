import pytest

from rampenschmiede.core.commands import CommandStack
from rampenschmiede.core.cordon import apply_cordon
from rampenschmiede.core.mathutil import BBox
from rampenschmiede.core.model import Entity, MapDocument, Solid
from rampenschmiede.core.skybox3d import (
    SCALE,
    STYLE_BY_KEY,
    STYLES,
    layout,
    main_bounds,
    remove_command,
    skybox_command,
    skybox_ids,
)
from rampenschmiede.core.templates.starter import grow_hull, starter_room
from rampenschmiede.core.validation.problems import find_problems
from rampenschmiede.core.validation.seal import check_seal


def _starter():
    doc = MapDocument()
    doc._insert(starter_room(doc, "css"))
    return doc


@pytest.mark.parametrize("style", [s.key for s in STYLES])
def test_skybox_is_sealed_valid_and_maps_the_world(style):
    doc = _starter()
    before = main_bounds(doc)
    stack = CommandStack(doc)
    cmd, objs = skybox_command(doc, STYLE_BY_KEY[style], "NATURE/GRASS", "NATURE/ROCK")
    stack.push(cmd)
    cam = next(o for o in objs if isinstance(o, Entity))
    assert cam.classname == "sky_camera" and cam.get("scale") == str(SCALE)
    lay = layout(doc)
    inner = lay.inner
    # Kamera im freien Raum, Raum außerhalb der Map, Map-Grenzen unverändert
    assert inner.contains(cam.origin) and cam.origin[2] > lay.ground_top
    assert not inner.intersects(before) and main_bounds(doc) == before
    assert not any(s.bbox().contains(cam.origin, -0.5) for s in doc.solids())
    # Die Map (verkleinert) liegt über dem Boden in der Mitte des Raums
    lo = tuple(cam.origin[i] + before.mins[i] / SCALE for i in range(3))
    hi = tuple(cam.origin[i] + before.maxs[i] / SCALE for i in range(3))
    assert inner.contains(lo) and inner.contains(hi) and lo[2] >= lay.ground_top - 1
    assert check_seal(doc).sealed
    assert not [p for p in find_problems(doc) if p.area == "Brushes"]
    assert grow_hull(doc) is None  # die mitwachsende Hülle bleibt, wie sie ist
    if style != "leer":
        assert sum(1 for o in objs if isinstance(o, Solid)) > 6 + 1 + 5


def test_new_skybox_replaces_old_and_can_be_removed():
    doc = _starter()
    stack = CommandStack(doc)
    stack.push(skybox_command(doc, STYLE_BY_KEY["berge"], "A", "B")[0])
    first = set(skybox_ids(doc))
    stack.push(skybox_command(doc, STYLE_BY_KEY["stadt"], "A", "B")[0])
    second = set(skybox_ids(doc))
    assert first and second and not first & second and not any(i in doc for i in first)
    assert sum(1 for e in doc.entities() if e.classname == "sky_camera") == 1
    stack.push(remove_command(doc))
    assert not skybox_ids(doc) and remove_command(doc) is None
    stack.undo()
    assert set(skybox_ids(doc)) == second


def test_cordon_keeps_the_skybox():
    doc = _starter()
    CommandStack(doc).push(skybox_command(doc, STYLE_BY_KEY["berge"], "A", "B")[0])
    res = apply_cordon(doc, BBox((-2560, -2560, 0), (-1536, -1536, 512)))
    assert set(skybox_ids(doc)) <= {o.id for o in res.doc.objects()}
    assert check_seal(res.doc).sealed
