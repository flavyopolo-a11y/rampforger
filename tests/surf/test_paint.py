"""Rampen malen: Strich -> Regler und Platzierung."""
import math

import pytest

from rampenschmiede.core.surf.catalog import CATALOG
from rampenschmiede.core.surf.paint import fit_stroke
from rampenschmiede.core.surf.sweep import arc_joints


def test_straight_ramp_follows_stroke():
    t = CATALOG["gerade"]
    values, at = fit_stroke(t, {}, (100, 50, 32), (100, 1074))
    assert values["laenge"] == 1024
    assert (at.x, at.y, at.z) == (100, 50, 32) and at.yaw == pytest.approx(90)


def test_short_stroke_keeps_values():
    t = CATALOG["gerade"]
    values, at = fit_stroke(t, {"laenge": 512}, (0, 0, 0), (4, 4))
    assert values == {"laenge": 512} and at.yaw == 0


@pytest.mark.parametrize("richtung", ["links", "rechts"])
def test_curve_ends_at_stroke_end(richtung):
    t = CATALOG["kurve"]
    end = (1000.0, 600.0)
    values, at = fit_stroke(t, {"richtung": richtung}, (0, 0, 0), end, snap=lambda v: v)
    v = t.values(values)
    sign = 1 if richtung == "links" else -1
    joints = arc_joints(v["radius"], sign * v["bogen"], x=at.x, y=at.y, yaw=at.yaw)
    assert math.hypot(joints[-1].x - end[0], joints[-1].y - end[1]) < 1.0


def test_other_templates_take_direction_only():
    t = CATALOG["pyramide"]
    values, at = fit_stroke(t, {}, (0, 0, 0), (-300, 0))
    assert values == {} and at.yaw == pytest.approx(180)


def test_straight_ramp_snaps_to_axis():
    t = CATALOG["gerade"]
    # leicht schräger Strich: Rampe läuft trotzdem genau nach +Y, Länge entlang der Achse
    values, at = fit_stroke(t, {}, (0, 0, 0), (130, 1020), snap=lambda v: round(v / 64) * 64)
    assert at.yaw == 90 and values["laenge"] == 1024
    values, at = fit_stroke(t, {}, (0, 0, 0), (-900, -100))
    assert at.yaw == 180
    # frei (Umschalttaste): 15°-Schritte
    _values, at = fit_stroke(t, {}, (0, 0, 0), (700, 700), axis_step=15.0)
    assert at.yaw == 45


def test_curve_is_not_forced_onto_axis():
    t = CATALOG["kurve"]
    _values, at = fit_stroke(t, {}, (0, 0, 0), (1000.0, 600.0), snap=lambda v: v)
    assert at.yaw % 90 != 0
