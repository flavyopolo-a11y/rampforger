"""Lichter der Map für die Vorschau: Farbe, Helligkeit, Abfall, Kegel und Sonnenrichtung aus
den Keyvalues von light, light_spot und light_environment, so gerechnet wie vrad.

- Helligkeit: `_light` = "R G B Helligkeit"; vrad rechnet Farbe/255 · Helligkeit/255.
- Abfall: `_constant_attn`, `_linear_attn`, `_quadratic_attn` (Standard nur quadratisch).
  vrad skaliert so, dass das Licht in 100 Units Abstand die angegebene Helligkeit hat:
  I(d) = I · (c + 100·l + 10000·q) / (c + l·d + q·d²).
- `_fifty_percent_distance` / `_zero_percent_distance`: halbe Helligkeit bei der ersten,
  danach Ausblenden bis null bei der zweiten.
- Spot: `_inner_cone` und `_cone` sind halbe Öffnungswinkel, `_exponent` bündelt.
- Richtung: `pitch` (wenn gesetzt) sonst der erste Wert von `angles`; negativ = nach unten,
  wie in Hammer. Die Sonne leuchtet in diese Richtung.

Schatten gibt es in der Vorschau nicht (dafür braucht es vrad).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .mathutil import Point
from .model import Entity, MapDocument

RGB = tuple[float, float, float]

POINT_CLASSES = {"light", "light_spot"}
SUN_CLASS = "light_environment"
LIGHT_CLASSES = POINT_CLASSES | {SUN_CLASS}
#: Spawnflag „Initially dark“ von light und light_spot
INITIALLY_DARK = 1
#: Ab dieser Resthelligkeit (0..1) zählt ein Licht in der Vorschau nicht mehr
CUTOFF = 1.0 / 255.0
#: Obergrenze für die Reichweite, damit ein falscher Wert nicht alles flutet
MAX_RANGE = 32768.0
DEFAULT_LIGHT = "255 255 255 200"


@dataclass(frozen=True)
class PointLight:
    entity_id: int
    position: Point
    color: RGB                  # Farbe 0..1 mal Helligkeit (vrad-Maßstab, 1 = weiß bei 100 Units)
    attn: tuple[float, float, float]   # c, l, q nach Skalierung: I(d) = color / (c + l·d + q·d²)
    fifty: float = 0.0          # halbe Helligkeit (0 = nicht gesetzt)
    zero: float = 0.0           # null ab hier (0 = nicht gesetzt)
    direction: Point | None = None     # nur Spot
    inner_cos: float = 1.0
    outer_cos: float = 1.0
    exponent: float = 1.0

    @property
    def is_spot(self) -> bool:
        return self.direction is not None

    def falloff(self, d: float) -> float:
        """Anteil der Helligkeit in d Units Abstand (ohne Kegel)."""
        if self.fifty > 0:
            k = 1.0 / (1.0 + (d / self.fifty) ** 2)
            if self.zero > self.fifty:
                k *= _smooth_fade(d, self.fifty, self.zero)
            return k
        c, lin, q = self.attn
        den = c + lin * d + q * d * d
        return 1.0 / den if den > 1e-9 else 1.0

    def range(self) -> float:
        """Abstand, ab dem das Licht praktisch nichts mehr beiträgt."""
        if self.fifty > 0 and self.zero > self.fifty:
            return min(self.zero, MAX_RANGE)
        peak = max(self.color) or 0.0
        if peak <= 0:
            return 0.0
        lo, hi = 0.0, MAX_RANGE
        if peak * self.falloff(hi) > CUTOFF:
            return MAX_RANGE
        for _ in range(40):
            mid = (lo + hi) / 2
            if peak * self.falloff(mid) > CUTOFF:
                lo = mid
            else:
                hi = mid
        return hi

    def half_distance(self) -> float:
        """Abstand mit halber Helligkeit gegenüber 100 Units (für die Anzeige)."""
        if self.fifty > 0:
            return self.fifty
        ref = self.falloff(100.0)
        lo, hi = 0.0, MAX_RANGE
        if self.falloff(hi) > ref / 2:
            return MAX_RANGE
        for _ in range(40):
            mid = (lo + hi) / 2
            if self.falloff(mid) > ref / 2:
                lo = mid
            else:
                hi = mid
        return hi


@dataclass(frozen=True)
class Sun:
    entity_id: int
    position: Point
    direction: Point            # Richtung, in die das Licht fällt
    color: RGB
    ambient: RGB


@dataclass(frozen=True)
class LightSet:
    lights: tuple[PointLight, ...] = ()
    sun: Sun | None = None
    #: Keine einzige Lichtquelle in der Map: das Spiel zeigt sie dann voll hell (fullbright)
    fullbright: bool = True


def _smooth_fade(d: float, start: float, end: float) -> float:
    if d <= start:
        return 1.0
    if d >= end:
        return 0.0
    t = (d - start) / (end - start)
    return 1.0 - t * t * (3 - 2 * t)


def _kv(ent: Entity, key: str, default: str = "") -> str:
    low = key.lower()
    for k, v in ent.keyvalues:
        if k.lower() == low:
            return v
    return default


def _float(text: str, default: float = 0.0) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def parse_color(text: str, default_brightness: float = 200.0) -> tuple[RGB, float]:
    """"R G B Helligkeit" -> (Farbe 0..1, Helligkeit). Fehlt die Helligkeit, gilt der Standard."""
    parts = (text or "").split()
    nums = [_float(p, -1.0) for p in parts]
    if len(nums) < 3 or any(n < 0 for n in nums[:3]):
        nums = [255.0, 255.0, 255.0, default_brightness]
    rgb = (min(nums[0], 255.0) / 255.0, min(nums[1], 255.0) / 255.0, min(nums[2], 255.0) / 255.0)
    brightness = nums[3] if len(nums) > 3 and nums[3] >= 0 else default_brightness
    return rgb, brightness


def format_color(rgb: tuple[int, int, int], brightness: float) -> str:
    return f"{rgb[0]} {rgb[1]} {rgb[2]} {brightness:g}"


def light_direction(ent: Entity) -> Point:
    """Leuchtrichtung aus pitch/angles (pitch negativ = nach unten)."""
    angles = [_float(a) for a in _kv(ent, "angles", "0 0 0").split()[:3]]
    angles += [0.0] * (3 - len(angles))
    pitch_raw = _kv(ent, "pitch")
    pitch = _float(pitch_raw, angles[0]) if pitch_raw.strip() else angles[0]
    yaw = angles[1]
    p, y = math.radians(pitch), math.radians(yaw)
    return (math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p))


def _scaled(rgb: RGB, brightness: float) -> RGB:
    k = brightness / 255.0
    return (rgb[0] * k, rgb[1] * k, rgb[2] * k)


def parse_point_light(ent: Entity) -> PointLight | None:
    if ent.classname.lower() not in POINT_CLASSES or ent.origin is None:
        return None
    if int(_float(_kv(ent, "spawnflags"), 0)) & INITIALLY_DARK and _kv(ent, "targetname"):
        return None
    rgb, brightness = parse_color(_kv(ent, "_light", DEFAULT_LIGHT))
    c = _float(_kv(ent, "_constant_attn"), 0.0)
    lin = _float(_kv(ent, "_linear_attn"), 0.0)
    q = _float(_kv(ent, "_quadratic_attn"), 0.0)
    if c <= 0 and lin <= 0 and q <= 0:
        q = 1.0  # vrad: ohne Angaben quadratisch
    scale = c + 100.0 * lin + 10000.0 * q
    attn = (c / scale, lin / scale, q / scale)
    fifty = max(0.0, _float(_kv(ent, "_fifty_percent_distance"), 0.0))
    zero = max(0.0, _float(_kv(ent, "_zero_percent_distance"), 0.0))
    color = _scaled(rgb, brightness)
    if ent.classname.lower() != "light_spot":
        return PointLight(ent.id, ent.origin, color, attn, fifty, zero)
    outer = min(max(_float(_kv(ent, "_cone"), 45.0), 0.5), 89.0)
    inner = min(max(_float(_kv(ent, "_inner_cone"), 30.0), 0.0), outer)
    exponent = max(_float(_kv(ent, "_exponent"), 1.0), 0.0) or 1.0
    return PointLight(ent.id, ent.origin, color, attn, fifty, zero, light_direction(ent),
                      math.cos(math.radians(inner)), math.cos(math.radians(outer)), exponent)


def parse_sun(ent: Entity) -> Sun | None:
    if ent.classname.lower() != SUN_CLASS:
        return None
    rgb, brightness = parse_color(_kv(ent, "_light", "255 255 255 200"))
    amb_rgb, amb_brightness = parse_color(_kv(ent, "_ambient", "255 255 255 20"), 20.0)
    return Sun(ent.id, ent.origin or (0.0, 0.0, 0.0), light_direction(ent),
               _scaled(rgb, brightness), _scaled(amb_rgb, amb_brightness))


def collect_lights(doc: MapDocument, include_hidden: bool = False) -> LightSet:
    """Alle Lichter der Map; ausgeblendete zählen nicht (wie beim Ausblenden in Hammer)."""
    lights: list[PointLight] = []
    sun: Sun | None = None
    any_source = False
    for ent in doc.entities():
        cls = ent.classname.lower()
        if cls not in LIGHT_CLASSES:
            continue
        any_source = True
        if ent.editor.hidden and not include_hidden:
            continue
        if cls == SUN_CLASS:
            if sun is None:  # vrad nimmt nur eine Sonne
                sun = parse_sun(ent)
        else:
            light = parse_point_light(ent)
            if light is not None:
                lights.append(light)
    return LightSet(tuple(lights), sun, fullbright=not any_source)


def nearest_lights(lights: tuple[PointLight, ...], eye: Point, limit: int) -> list[PointLight]:
    """Die Lichter, die für die Kamera am meisten zählen: zuerst die, in deren Reichweite sie steht."""
    if len(lights) <= limit:
        return list(lights)

    def gap(light: PointLight) -> float:
        d = math.dist(light.position, eye)
        return max(0.0, d - light.range())

    return sorted(lights, key=lambda li: (gap(li), math.dist(li.position, eye)))[:limit]


def sun_angles(direction: Point) -> tuple[float, float]:
    """(pitch, yaw) in Grad für eine Leuchtrichtung, Gegenstück zu light_direction."""
    x, y, z = direction
    pitch = math.degrees(math.atan2(z, math.hypot(x, y)))
    yaw = math.degrees(math.atan2(y, x)) % 360.0
    return pitch, yaw


# ---- Anzeige in den Ansichten --------------------------------------------------------------
Segment = tuple[Point, Point, RGB]
#: Länge des Sonnenpfeils und größte Länge eines Spot-Kegels in der Anzeige
SUN_ARROW = 256.0
MAX_CONE = 2048.0
CIRCLE_STEPS = 48


def _display_color(color: RGB) -> RGB:
    peak = max(color) or 1.0
    return (color[0] / peak, color[1] / peak, color[2] / peak)


def _basis(n: Point) -> tuple[Point, Point]:
    """Zwei Einheitsvektoren senkrecht zu n und zueinander."""
    ref = (0.0, 0.0, 1.0) if abs(n[2]) < 0.9 else (1.0, 0.0, 0.0)
    u = _cross(n, ref)
    lu = math.sqrt(sum(c * c for c in u))
    u = (u[0] / lu, u[1] / lu, u[2] / lu)
    return u, _cross(n, u)


def _cross(a: Point, b: Point) -> Point:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _circle(center: Point, u: Point, v: Point, radius: float, color: RGB) -> list[Segment]:
    pts = []
    for i in range(CIRCLE_STEPS + 1):
        a = 2 * math.pi * i / CIRCLE_STEPS
        ca, sa = math.cos(a) * radius, math.sin(a) * radius
        pts.append(tuple(center[k] + u[k] * ca + v[k] * sa for k in range(3)))
    return [(pts[i], pts[i + 1], color) for i in range(CIRCLE_STEPS)]  # type: ignore[misc]


def _sphere(center: Point, radius: float, color: RGB) -> list[Segment]:
    x, y, z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    return _circle(center, x, y, radius, color) + _circle(center, x, z, radius, color) + \
        _circle(center, y, z, radius, color)


def _dim(color: RGB, k: float = 0.55) -> RGB:
    return (color[0] * k, color[1] * k, color[2] * k)


def gizmo_segments(doc: MapDocument, ids) -> list[Segment]:
    """Linien für gewählte Lichter: Reichweite (Kugel), Kegel beim Spot, Pfeil bei der Sonne."""
    segs: list[Segment] = []
    for i in ids:
        ent = doc.get(i)
        if not isinstance(ent, Entity) or ent.classname.lower() not in LIGHT_CLASSES:
            continue
        if ent.classname.lower() == SUN_CLASS:
            sun = parse_sun(ent)
            if sun is None:
                continue
            color = _display_color(sun.color)
            o, d = sun.position, sun.direction
            tip = tuple(o[k] + d[k] * SUN_ARROW for k in range(3))
            segs.append((o, tip, color))  # type: ignore[arg-type]
            u, v = _basis(d)
            for side in (u, v, tuple(-c for c in u), tuple(-c for c in v)):
                back = tuple(tip[k] - d[k] * 40 + side[k] * 16 for k in range(3))
                segs.append((tip, back, color))  # type: ignore[arg-type]
            continue
        light = parse_point_light(ent)
        if light is None:
            continue
        color = _display_color(light.color)
        reach = light.range()
        if not light.is_spot:
            segs += _sphere(light.position, reach, _dim(color))
            if light.fifty > 0:
                segs += _sphere(light.position, light.fifty, color)
            continue
        o, d = light.position, light.direction
        assert d is not None
        length = min(reach, MAX_CONE)
        u, v = _basis(d)
        for cos_a, c in ((light.outer_cos, color), (light.inner_cos, _dim(color))):
            sin_a = math.sqrt(max(0.0, 1 - cos_a * cos_a))
            center = tuple(o[k] + d[k] * length * cos_a for k in range(3))
            radius = length * sin_a
            segs += _circle(center, u, v, radius, c)  # type: ignore[arg-type]
            if c is color:
                for j in range(8):
                    a = 2 * math.pi * j / 8
                    rim = tuple(center[k] + (u[k] * math.cos(a) + v[k] * math.sin(a)) * radius for k in range(3))
                    segs.append((o, rim, color))  # type: ignore[arg-type]
    return segs


__all__ = [
    "CUTOFF", "LIGHT_CLASSES", "LightSet", "PointLight", "Sun", "collect_lights", "format_color", "gizmo_segments",
    "light_direction", "nearest_lights", "parse_color", "parse_point_light", "parse_sun", "sun_angles",
]
