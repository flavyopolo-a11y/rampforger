"""Eingepasste Rampen-Textur: quer genau einmal, längs ohne Sprung über die Segmente."""
import pytest

from rampenschmiede.core.geometry.brush import solid_polygons
from rampenschmiede.core.materials.sizes import set_size_lookup
from rampenschmiede.core.surf.catalog import SURF_MATERIAL, generate


def _surf(gen):
    out = []
    for faces in gen.face_sets:
        for face, poly in zip(faces, solid_polygons(faces)):
            if face.material == SURF_MATERIAL.default and poly:
                out.append((face, poly))
    return out


def _tex(face, p):
    u = sum(p[i] * face.uaxis.vec[i] for i in range(3)) / face.uaxis.scale + face.uaxis.offset
    v = sum(p[i] * face.vaxis.vec[i] for i in range(3)) / face.vaxis.scale + face.vaxis.offset
    return u, v


@pytest.fixture(autouse=True)
def _sizes():
    set_size_lookup(None)
    yield
    set_size_lookup(None)


def test_straight_ramp_texture_spans_width_once():
    surf = _surf(generate("gerade", {"laenge": 1024}))
    assert len(surf) == 2  # zwei Hänge
    for face, poly in surf:
        n = face.plane.normal
        assert abs(sum(face.vaxis.vec[i] * n[i] for i in range(3))) < 1e-6  # v liegt in der Fläche
        assert face.vaxis.vec[2] < 0  # und zeigt hangabwärts
        vs = [_tex(face, p)[1] for p in poly]
        assert max(vs) - min(vs) == pytest.approx(512, abs=0.5)
        assert min(vs) % 512 == pytest.approx(0, abs=0.5) or min(vs) % 512 == pytest.approx(512, abs=0.5)
        assert face.uaxis.scale == pytest.approx(face.vaxis.scale)  # nicht verzerrt


def test_size_percent_and_texture_lookup():
    set_size_lookup(lambda m: (1024, 256))
    face, poly = _surf(generate("gerade", {"textur_groesse": 200}))[0]
    vs = [_tex(face, p)[1] for p in poly]
    assert max(vs) - min(vs) == pytest.approx(128, abs=0.5)


def _close(a, b, size=512, tol=1.0):
    d = (a - b) % size
    return d < tol or size - d < tol


def test_curve_texture_is_continuous_across_seams():
    gen = generate("kurve", {"bogen": 30})
    segments = []
    for faces in gen.face_sets:
        segments.append([(f, p) for f, p in zip(faces, solid_polygons(faces))
                         if f.material == SURF_MATERIAL.default and p])
    seams = 0
    for here, nxt in zip(segments, segments[1:]):
        for fa, pa in here:
            for fb, pb in nxt:
                if sum(fa.plane.normal[i] * fb.plane.normal[i] for i in range(3)) < 0.9:
                    continue  # anderer Hang
                shared = [p for p in pa if any(max(abs(p[i] - q[i]) for i in range(3)) < 1e-3 for q in pb)]
                if len(shared) < 2:
                    continue
                for p in shared:
                    (ua, va), (ub, vb) = _tex(fa, p), _tex(fb, p)
                    # Facetten-Kurve: Eine ebene Textur kann nicht exakt um die Kurve laufen, an den Enden
                    # der Naht bleibt eine kleine Abweichung (bei 2,5° pro Segment etwa 10 Texel)
                    assert _close(ua, ub, tol=14), (ua, ub)
                    assert _close(va, vb, tol=2), (va, vb)
                seams += 1
    assert seams >= 6


def test_raster_mode_keeps_world_axes():
    face, _ = _surf(generate("gerade", {"textur": "raster"}))[0]
    assert face.uaxis.scale == 0.25 and face.uaxis.offset == 0


def test_shift_moves_texture():
    a, poly = _surf(generate("gerade", {}))[0]
    b, _ = _surf(generate("gerade", {"textur_laengs": 64, "textur_quer": 32}))[0]
    p = poly[0]
    (ua, va), (ub, vb) = _tex(a, p), _tex(b, p)
    assert abs(ub - ua) % 512 == pytest.approx(64 / a.uaxis.scale % 512, abs=0.5)
    assert abs(vb - va) % 512 == pytest.approx(32 / a.vaxis.scale % 512, abs=0.5)
