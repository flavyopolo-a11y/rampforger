"""Rampen malen: aus einem gezogenen Strich (Anfang, Ende) Regler und Platzierung einer
Vorlage bestimmen.

Gerade Vorlagen (mit Länge) laufen genau vom Anfang zum Ende. Kurven bekommen den Radius,
mit dem ihr Bogen am Ende des Strichs ankommt. Alles andere übernimmt nur die Richtung.

Gerade Vorlagen rasten mit `axis_step` (Standard 90°) auf die Achsen ein: Dann liegen Anfang,
Ende und Kanten auf dem Raster. Kurven dürfen jede Richtung haben, ihre Segmente liegen ohnehin
schräg.
"""
from __future__ import annotations

import math

from .catalog import Placement, Template

MIN_STROKE = 16.0
#: Gerade Rampen laufen beim Malen nur entlang der Achsen (Raster)
AXIS_STEP = 90.0


def is_straight(template: Template) -> bool:
    """Vorlagen, die geradeaus entlang ihrer Länge laufen (Rampen, Banane, Welle, Rinnen …)."""
    return any(p.key == "laenge" for p in template.params)


def _clamp(template: Template, key: str, value: float) -> float:
    p = next(p for p in template.params if p.key == key)
    return min(max(value, p.minimum), p.maximum)


def fit_stroke(template: Template, values: dict, start: tuple[float, float, float], end: tuple[float, float],
               snap=round, axis_step: float | None = AXIS_STEP) -> tuple[dict, Placement]:
    """Werte und Platzierung, damit die Vorlage den Strich von `start` nach `end` nachzeichnet.
    `start` hat die Höhe, `end` nur x und y. Ein zu kurzer Strich setzt die Vorlage nur ab.
    `axis_step`: Raster für die Richtung gerader Vorlagen (None = frei)."""
    x, y, z = start
    dx, dy = end[0] - x, end[1] - y
    dist = math.hypot(dx, dy)
    keys = {p.key for p in template.params}
    out = dict(values)
    if dist < MIN_STROKE:
        return out, Placement(x, y, z, 0.0)
    direction = math.degrees(math.atan2(dy, dx))
    if axis_step and is_straight(template):
        direction = round(direction / axis_step) * axis_step
        a = math.radians(direction)
        dist = max(dx * math.cos(a) + dy * math.sin(a), MIN_STROKE)  # Länge entlang der Achse
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


__all__ = ["AXIS_STEP", "MIN_STROKE", "fit_stroke", "is_straight"]
