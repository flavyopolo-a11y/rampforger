"""Objekte im Dokument: Faces, Brushes (Solid) und Entities.

Objekte werden nach dem Einfügen ins Dokument nicht mehr verändert. Eine Bearbeitung
erzeugt eine Kopie mit derselben ID und ersetzt das alte Objekt über ein Command
(Copy-on-Write). Dadurch speichert Undo einfach das alte Objekt.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from ..mathutil import BBox, Plane, Point, is_integer_point


@dataclass(frozen=True, slots=True)
class TexAxis:
    """Eine Texturachse wie in VMF: "[x y z offset] scale"."""

    x: float
    y: float
    z: float
    offset: float = 0.0
    scale: float = 0.25

    @property
    def vec(self) -> Point:
        return (self.x, self.y, self.z)

    def with_vec(self, v: Point) -> "TexAxis":
        return TexAxis(v[0], v[1], v[2], self.offset, self.scale)


def default_tex_axes(normal: Point) -> tuple[TexAxis, TexAxis]:
    """Weltausrichtung wie Hammer: die dominante Achse der Normale bestimmt die Projektion."""
    ax, ay, az = (abs(c) for c in normal)
    if az >= ax and az >= ay:
        return TexAxis(1, 0, 0), TexAxis(0, -1, 0)
    if ax >= ay:
        return TexAxis(0, 1, 0), TexAxis(0, 0, -1)
    return TexAxis(1, 0, 0), TexAxis(0, 0, -1)


DEFAULT_MATERIAL = "DEV/DEV_MEASUREGENERIC01B"


@dataclass(frozen=True, slots=True)
class Face:
    """Eine Seite eines Brushes. Die Ebene ist über drei Punkte definiert (VMF-Konvention:
    von außen gesehen im Uhrzeigersinn)."""

    points: tuple[Point, Point, Point]
    material: str = DEFAULT_MATERIAL
    uaxis: TexAxis = TexAxis(1, 0, 0)
    vaxis: TexAxis = TexAxis(0, -1, 0)
    rotation: float = 0.0
    lightmapscale: int = 16
    smoothing_groups: int = 0
    vmf_id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def plane(self) -> Plane:
        return Plane.from_vmf_points(*self.points)

    def has_integer_points(self) -> bool:
        return all(is_integer_point(p) for p in self.points)


@dataclass(frozen=True, slots=True)
class EditorInfo:
    color: tuple[int, int, int] = (0, 180, 255)
    group_id: int | None = None
    visgroup_ids: tuple[int, ...] = ()
    hidden: bool = False
    locked: bool = False


@dataclass(frozen=True)
class Solid:
    """Ein konvexer Brush: Schnitt der Halbräume seiner Faces."""

    id: int
    faces: tuple[Face, ...]
    parent_id: int | None = None  # None = Welt, sonst ID der Brush-Entity
    editor: EditorInfo = EditorInfo()
    vmf_id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    # Abgeleitete Geometrie wird bei Bedarf berechnet und am Objekt zwischengespeichert.
    # Da Solids unveränderlich sind, bleibt der Cache gültig.
    def polygons(self) -> list[list[Point] | None]:
        cache = self.__dict__.get("_polys")
        if cache is None:
            from ..geometry.brush import solid_polygons

            cache = solid_polygons(self.faces)
            object.__setattr__(self, "_polys", cache)
        return cache

    def vertices(self) -> list[Point]:
        seen: dict[Point, None] = {}
        for poly in self.polygons():
            if poly:
                for p in poly:
                    seen.setdefault(p, None)
        return list(seen)

    def bbox(self) -> BBox | None:
        cache = self.__dict__.get("_bbox")
        if cache is None:
            cache = BBox.from_points(self.vertices())
            object.__setattr__(self, "_bbox", cache)
        return cache

    def is_valid(self) -> bool:
        from ..geometry.brush import is_valid_solid

        return is_valid_solid(self)

    def replace(self, **changes: Any) -> "Solid":
        return dataclasses.replace(self, **changes)


@dataclass(frozen=True)
class Output:
    """Eine I/O-Verbindung. Wird ab Etappe 5 vollständig bearbeitbar."""

    output: str
    target: str
    input: str
    parameter: str = ""
    delay: float = 0.0
    times: int = -1


@dataclass(frozen=True)
class Entity:
    id: int
    classname: str
    keyvalues: tuple[tuple[str, str], ...] = ()
    outputs: tuple[Output, ...] = ()
    editor: EditorInfo = EditorInfo(color=(220, 30, 220))
    vmf_id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    def get(self, key: str, default: str = "") -> str:
        for k, v in self.keyvalues:
            if k == key:
                return v
        return default

    def with_keyvalue(self, key: str, value: str) -> "Entity":
        kvs = list(self.keyvalues)
        for i, (k, _) in enumerate(kvs):
            if k == key:
                kvs[i] = (key, value)
                break
        else:
            kvs.append((key, value))
        return dataclasses.replace(self, keyvalues=tuple(kvs))

    @property
    def origin(self) -> Point | None:
        raw = self.get("origin")
        if not raw:
            return None
        try:
            x, y, z = (float(c) for c in raw.split())
        except ValueError:
            return None
        return (x, y, z)

    def replace(self, **changes: Any) -> "Entity":
        return dataclasses.replace(self, **changes)


MapObject = Solid | Entity
