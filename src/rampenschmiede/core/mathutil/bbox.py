"""Achsenparallele Bounding-Box."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .vec import Point


@dataclass(frozen=True, slots=True)
class BBox:
    mins: Point
    maxs: Point

    @staticmethod
    def from_points(points: Iterable[Point]) -> "BBox | None":
        pts = list(points)
        if not pts:
            return None
        xs, ys, zs = zip(*pts)
        return BBox((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))

    @staticmethod
    def union(boxes: Iterable["BBox | None"]) -> "BBox | None":
        result: BBox | None = None
        for b in boxes:
            if b is None:
                continue
            if result is None:
                result = b
            else:
                result = BBox(
                    tuple(min(a, c) for a, c in zip(result.mins, b.mins)),  # type: ignore[arg-type]
                    tuple(max(a, c) for a, c in zip(result.maxs, b.maxs)),  # type: ignore[arg-type]
                )
        return result

    @property
    def center(self) -> Point:
        return tuple((a + b) / 2 for a, b in zip(self.mins, self.maxs))  # type: ignore[return-value]

    @property
    def size(self) -> Point:
        return tuple(b - a for a, b in zip(self.mins, self.maxs))  # type: ignore[return-value]

    def contains(self, p: Point, eps: float = 0.0) -> bool:
        return all(self.mins[i] - eps <= p[i] <= self.maxs[i] + eps for i in range(3))

    def intersects(self, other: "BBox") -> bool:
        return all(self.mins[i] <= other.maxs[i] and other.mins[i] <= self.maxs[i] for i in range(3))
