import re

from rampenschmiede.core.decals import (
    basis,
    make_decal,
    make_overlay,
    overlay_corners,
    overlay_sides,
    sticker_bbox,
)
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.io.vmf import export_vmf
from rampenschmiede.core.model import MapDocument, Solid


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def test_basis_is_right_handed_and_upright_on_walls():
    for n in ((0, 0, 1), (0, 0, -1), (1, 0, 0), (0, -1, 0), (0.6, 0, 0.8)):
        u, v = basis(n)
        c = _cross(u, v)
        assert all(abs(c[i] - n[i] / sum(x * x for x in n) ** 0.5) < 1e-6 for i in range(3))
    u, v = basis((1, 0, 0))
    assert abs(u[2]) < 1e-9 and v == (0.0, 0.0, 1.0)


def _two_floor_brushes(doc):
    a = Solid(id=doc.new_id(), faces=primitives.block((0, 0, -16), (128, 256, 0))[0])
    b = Solid(id=doc.new_id(), faces=primitives.block((128, 0, -16), (256, 256, 0))[0])
    doc._insert([a, b])
    return a, b


def test_overlay_spans_coplanar_faces_and_follows_its_origin_on_export():
    doc = MapDocument()
    a, b = _two_floor_brushes(doc)
    ov = make_overlay(doc, (128, 128, 0), (0, 0, 1), "overlays/road", 128, 64)
    doc._insert([ov])
    n, pts = overlay_corners(ov)
    assert n == (0.0, 0.0, 1.0) and {p[2] for p in pts} == {0.0}
    assert sorted(overlay_sides(doc, ov)) == sorted([(a.id, i) for i, f in enumerate(a.faces) if f.plane.normal[2] > 0.9]
                                                    + [(b.id, i) for i, f in enumerate(b.faces) if f.plane.normal[2] > 0.9])
    bb = sticker_bbox(ov)
    assert bb.mins[0] == 64 and bb.maxs[0] == 192 and bb.mins[1] == 96 and bb.maxs[1] == 160
    text = export_vmf(doc).text
    sides = re.search(r'"sides" "([0-9 ]+)"', text).group(1).split()
    top_ids = set()
    for sid, plane in re.findall(r'"id" "(\d+)"\s*"plane" "([^"]+)"', text):
        zs = [float(p.split()[2]) for p in re.findall(r"\(([^)]+)\)", plane)]
        if zs == [0.0, 0.0, 0.0]:
            top_ids.add(sid)
    assert len(sides) == 2 and set(sides) <= top_ids
    # Verschoben: die Basis wandert mit, und auf der neuen Stelle liegt nur noch Brush b darunter
    moved = ov.replace(keyvalues=tuple((k, "220 128 0" if k == "origin" else v) for k, v in ov.keyvalues))
    doc._replace([moved])
    assert [sid for sid, _ in overlay_sides(doc, moved)] == [b.id]
    text = export_vmf(doc).text
    assert '"BasisOrigin" "220 128 0"' in text


def test_decal_keeps_texture_and_preview_size():
    doc = MapDocument()
    d = make_decal(doc, (10.4, 0, 33), (0, -1, 0), "DECALS/Lambdaspray_2a", (128, 64))
    assert d.get("texture") == "decals/lambdaspray_2a" and d.get("origin") == "10 0 33"
    bb = sticker_bbox(d)
    assert bb.size[0] == 128 and bb.size[2] == 64 and bb.size[1] == 2


def test_problems_report_overlay_in_the_air():
    from rampenschmiede.core.validation.problems import find_problems

    doc = MapDocument()
    _two_floor_brushes(doc)
    ok = make_overlay(doc, (64, 64, 0), (0, 0, 1), "overlays/road", 64, 64)
    air = make_overlay(doc, (64, 64, 300), (0, 0, 1), "overlays/road", 64, 64)
    doc._insert([ok, air])
    hits = [p for p in find_problems(doc) if p.area == "Aufkleber"]
    assert len(hits) == 1 and hits[0].ids == (air.id,) and hits[0].text.startswith("Overlays ohne Fläche darunter: 1.")
