"""Lichter für die Vorschau: Werte wie vrad, Reichweite, Kegel, Sonne, Anzeige-Linien."""
import math

import pytest

from rampenschmiede.core.lights import (
    collect_lights,
    gizmo_segments,
    light_direction,
    nearest_lights,
    parse_color,
    parse_point_light,
    parse_sun,
    sun_angles,
)
from rampenschmiede.core.model import EditorInfo, Entity, MapDocument


def ent(classname, *kvs, eid=1, **extra):
    return Entity(id=eid, classname=classname, keyvalues=(("origin", "0 0 64"), *kvs), **extra)


def test_color_and_brightness():
    assert parse_color("255 128 0 300") == ((1.0, 128 / 255, 0.0), 300.0)
    # Ohne Helligkeit gilt der Standard, Unsinn wird weiß
    assert parse_color("255 255 255")[1] == 200.0
    assert parse_color("kaputt")[0] == (1.0, 1.0, 1.0)


def test_quadratic_light_has_its_brightness_at_100_units():
    light = parse_point_light(ent("light", ("_light", "255 255 255 255")))
    assert light.color == (1.0, 1.0, 1.0)
    assert light.falloff(100) == pytest.approx(1.0)
    assert light.falloff(200) == pytest.approx(0.25)
    # Reichweite: dort ist nur noch 1/255 übrig
    assert light.range() == pytest.approx(math.sqrt(255) * 100, rel=1e-3)


def test_linear_and_constant_falloff():
    lin = parse_point_light(ent("light", ("_light", "255 255 255 255"), ("_quadratic_attn", "0"),
                                ("_linear_attn", "1")))
    assert lin.falloff(100) == pytest.approx(1.0) and lin.falloff(400) == pytest.approx(0.25)
    const = parse_point_light(ent("light", ("_constant_attn", "1"), ("_quadratic_attn", "0")))
    assert const.falloff(10) == const.falloff(5000) == pytest.approx(1.0)


def test_fifty_and_zero_percent_distance():
    light = parse_point_light(ent("light", ("_fifty_percent_distance", "256"), ("_zero_percent_distance", "512")))
    assert light.falloff(256) == pytest.approx(0.5)
    assert light.falloff(600) == 0.0
    assert light.range() == 512


def test_spot_cone_and_direction():
    spot = parse_point_light(ent("light_spot", ("pitch", "-90"), ("angles", "0 0 0"), ("_inner_cone", "20"),
                                 ("_cone", "40")))
    assert spot.is_spot
    assert spot.direction == pytest.approx((0.0, 0.0, -1.0), abs=1e-9)
    assert spot.inner_cos == pytest.approx(math.cos(math.radians(20)))
    assert spot.outer_cos == pytest.approx(math.cos(math.radians(40)))


def test_pitch_key_wins_over_angles():
    e = ent("light_environment", ("angles", "0 90 0"), ("pitch", "-45"))
    d = light_direction(e)
    assert d == pytest.approx((0.0, math.sqrt(0.5), -math.sqrt(0.5)), abs=1e-9)
    assert sun_angles(d) == pytest.approx((-45.0, 90.0))
    # Ohne pitch zählt der erste Wert von angles
    assert light_direction(ent("light_spot", ("angles", "-90 0 0")))[2] == pytest.approx(-1.0)


def test_sun_color_and_ambient():
    sun = parse_sun(ent("light_environment", ("_light", "255 0 0 255"), ("_ambient", "0 0 255 51"),
                        ("pitch", "-60")))
    assert sun.color == (1.0, 0.0, 0.0)
    assert sun.ambient == pytest.approx((0.0, 0.0, 0.2))
    assert sun.direction[2] < -0.8


def test_collect_lights_skips_hidden_and_dark_and_detects_fullbright():
    doc = MapDocument()
    assert collect_lights(doc).fullbright
    doc._insert([
        ent("light", eid=doc.new_id()),
        ent("light", ("targetname", "aus"), ("spawnflags", "1"), eid=doc.new_id()),
        ent("light", eid=doc.new_id(), editor=EditorInfo(color=(1, 1, 1), hidden=True)),
        ent("light_environment", ("pitch", "-50"), eid=doc.new_id()),
        ent("light_environment", ("pitch", "-10"), eid=doc.new_id()),
        ent("info_player_counterterrorist", eid=doc.new_id()),
    ])
    lights = collect_lights(doc)
    assert not lights.fullbright
    assert len(lights.lights) == 1
    # Nur die erste Sonne zählt, wie in vrad
    assert lights.sun is not None and lights.sun.direction[2] == pytest.approx(math.sin(math.radians(-50)))


def test_nearest_lights_prefers_lights_reaching_the_camera():
    far = parse_point_light(ent("light", eid=1))
    lights = []
    for i in range(5):
        e = Entity(id=10 + i, classname="light", keyvalues=(("origin", f"{i * 10000} 0 0"),))
        lights.append(parse_point_light(e))
    chosen = nearest_lights(tuple(lights), (40000.0, 0.0, 0.0), 2)
    assert [li.entity_id for li in chosen] == [14, 13]
    assert nearest_lights((far,), (0, 0, 0), 4) == [far]


def test_gizmo_lines_for_selected_lights():
    doc = MapDocument()
    doc._insert([ent("light", eid=1), ent("light_spot", ("pitch", "-90"), eid=2),
                 ent("light_environment", ("pitch", "-90"), eid=3), ent("info_target", eid=4)])
    assert gizmo_segments(doc, [4]) == []
    point = gizmo_segments(doc, [1])
    radius = parse_point_light(doc.get(1)).range()
    assert len(point) == 3 * 48
    assert all(math.dist(a, (0, 0, 64)) == pytest.approx(radius) for a, _, _ in point)
    spot = gizmo_segments(doc, [2])
    assert any(a == (0.0, 0.0, 64.0) for a, _, _ in spot)  # Kegel-Linien vom Licht aus
    assert all(b[2] <= 64 + 1e-6 for _, b, _ in spot)       # zeigt nach unten
    sun = gizmo_segments(doc, [3])
    assert sun[0][1][2] == pytest.approx(64 - 256)
