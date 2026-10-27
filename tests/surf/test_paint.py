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
