"""Rampen malen: aus einem gezogenen Strich (Anfang, Ende) Regler und Platzierung einer
Vorlage bestimmen.

Gerade Vorlagen (mit Länge) laufen genau vom Anfang zum Ende. Kurven bekommen den Radius,
mit dem ihr Bogen am Ende des Strichs ankommt. Alles andere übernimmt nur die Richtung.
"""
from __future__ import annotations

import math

from .catalog import Placement, Template

MIN_STROKE = 16.0


def _clamp(template: Template, key: str, value: float) -> float:
    p = next(p for p in template.params if p.key == key)
    return min(max(value, p.minimum), p.maximum)


def fit_stroke(template: Template, values: dict, start: tuple[float, float, float], end: tuple[float, float],
               snap=round) -> tuple[dict, Placement]:
    """Werte und Platzierung, damit die Vorlage den Strich von `start` nach `end` nachzeichnet.
    `start` hat die Höhe, `end` nur x und y. Ein zu kurzer Strich setzt die Vorlage nur ab."""
    x, y, z = start
    dx, dy = end[0] - x, end[1] - y
    dist = math.hypot(dx, dy)
    keys = {p.key for p in template.params}
    out = dict(values)
    if dist < MIN_STROKE:
        return out, Placement(x, y, z, 0.0)
    direction = math.degrees(math.atan2(dy, dx))
    yaw = direction
    if "laenge" in keys:
        out["laenge"] = int(_clamp(template, "laenge", snap(dist)))
    elif "radius" in keys and "bogen" in keys and template.key != "s_kurve":
        bend = float(template.values(values)["bogen"])
        sign = 1 if template.values(values).get("richtung", "links") == "links" else -1
        half = math.radians(bend) / 2
        if bend < 350 and math.sin(half) > 0.05:
            out["radius"] = int(_clamp(template, "radius", snap(dist / (2 * math.sin(half)))))
            yaw = direction - sign * bend / 2
        else:
            out["radius"] = int(_clamp(template, "radius", snap(dist)))
    return out, Placement(x, y, z, round(yaw % 360, 3))


__all__ = ["MIN_STROKE", "fit_stroke"]
