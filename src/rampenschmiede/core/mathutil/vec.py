"""Vektorfunktionen auf einfachen Tupeln.

Bewusst ohne eigene Vektorklasse: Tupel sind unveränderlich, hashbar und lassen sich direkt
nach JSON schreiben. Für Massenrechnungen (Renderer, Picking) wird numpy verwendet.
"""
from __future__ import annotations

import math

Point = tuple[float, float, float]

EPSILON = 1e-6


def add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a: Point, f: float) -> Point:
    return (a[0] * f, a[1] * f, a[2] * f)


def dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Point, b: Point) -> Point:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def length(a: Point) -> float:
    return math.sqrt(dot(a, a))


def normalize(a: Point) -> Point:
    n = length(a)
    if n < EPSILON:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def round_point(a: Point) -> tuple[int, int, int]:
    """Rundet auf ganze Units mit floor(x + 0.5). Pythons round() rundet .5 zur geraden
    Zahl, dann würden verschobene Formen je nach Lage um eine Unit wachsen oder schrumpfen."""
    return (math.floor(a[0] + 0.5), math.floor(a[1] + 0.5), math.floor(a[2] + 0.5))


def is_integer_point(a: Point, tol: float = 1e-6) -> bool:
    return all(abs(c - round(c)) <= tol for c in a)
