"""Ebene in Hessescher Normalform: Punkte x mit dot(normal, x) == dist liegen auf der Ebene."""
from __future__ import annotations

from dataclasses import dataclass

from .vec import EPSILON, Point, cross, dot, normalize, sub


@dataclass(frozen=True, slots=True)
class Plane:
    normal: Point
    dist: float

    @staticmethod
    def from_vmf_points(p1: Point, p2: Point, p3: Point) -> "Plane":
        """Ebene aus drei VMF-Punkten. In VMF sind die Punkte von außen gesehen im
        Uhrzeigersinn angegeben; die Normale zeigt nach außen."""
        n = normalize(cross(sub(p3, p1), sub(p2, p1)))
        return Plane(n, dot(n, p1))

    def distance(self, p: Point) -> float:
        """Vorzeichenbehafteter Abstand; positiv heißt außerhalb des Brushes."""
        return dot(self.normal, p) - self.dist

    def is_valid(self) -> bool:
        return abs(dot(self.normal, self.normal) - 1.0) < 1e-3

    def same_as(self, other: "Plane", eps: float = EPSILON * 100) -> bool:
        return (
            abs(self.dist - other.dist) < eps
            and abs(self.normal[0] - other.normal[0]) < eps
            and abs(self.normal[1] - other.normal[1]) < eps
            and abs(self.normal[2] - other.normal[2]) < eps
        )
