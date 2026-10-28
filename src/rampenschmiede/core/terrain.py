"""Gelände bearbeiten: Brushes in Displacements umwandeln und mit dem Pinsel formen.

Die Rechnungen je Fläche stehen in `geometry.displacement`. Hier geht es um ganze Brushes und
die Map: welche Seite Gelände wird, welche Brushes ein Pinselstrich trifft, Nähte schließen.
Displacements müssen Welt-Brushes sein (vbsp nimmt sie in func_detail nicht an).
"""
from __future__ import annotations

from typing import Iterable

import numpy as np

from ..i18n import tr
from .geometry.displacement import (
    POWERS,
    brush_stroke,
    face_displacement,
    is_displacement_solid,
    make_displacement,
    set_surface,
    sew,
    surfaces,
    with_displacement,
)
from .mathutil import Point
from .model import MapDocument, Solid, owner_id

#: Anzeige der Power-Stufen: Felder je Kante
POWER_LABELS = {2: tr("4 × 4 Felder"), 3: tr("8 × 8 Felder"), 4: tr("16 × 16 Felder")}


class TerrainError(ValueError):
    pass


def top_face(solid: Solid) -> int | None:
    """Die Seite, die Gelände wird: die am meisten nach oben zeigende viereckige Seite."""
    polys = solid.polygons()
    best = None
    for k, (face, poly) in enumerate(zip(solid.faces, polys)):
        if poly is None or len(poly) != 4:
            continue
        nz = face.plane.normal[2]
        if best is None or nz > best[0]:
            best = (nz, k)
    return best[1] if best is not None else None


def convert(doc: MapDocument, solid: Solid, power: int = 3) -> Solid:
    """Oberseite eines Welt-Brushes in flaches Gelände umwandeln."""
    if power not in POWERS:
        raise TerrainError(tr('Power {0} gibt es nicht (2, 3 oder 4)').format(power))
    if owner_id(solid) is not None:
        raise TerrainError(tr("Gelände geht nur aus Welt-Brushes, nicht aus Bausteinen oder func_detail"))
    k = top_face(solid)
    if k is None:
        raise TerrainError(tr("Der Brush hat keine viereckige Seite"))
    if face_displacement(solid.faces[k]) is not None:
        return solid
    return make_displacement(solid, k, power)


def flatten(solid: Solid) -> Solid:
    """Displacements eines Brushes wieder entfernen (normale Seiten)."""
    return solid.replace(faces=tuple(with_displacement(f, None) for f in solid.faces))


def terrain_solids(doc: MapDocument, visible: Iterable[Solid] | None = None) -> list[Solid]:
    return [s for s in (visible if visible is not None else doc.solids()) if is_displacement_solid(s)]


def stroke(solids: Iterable[Solid], center: Point, radius: float, strength: float, mode: str,
           ignore_axis: int | None = None, seed: int = 0) -> list[Solid]:
    """Einen Pinselschritt auf alle getroffenen Displacements anwenden. Gehoben wird entlang der
    Seiten-Normale. `ignore_axis`: diese Achse zählt beim Abstand nicht (Malen von oben in 2D)."""
    c = np.asarray(center, dtype=np.float64)
    out = []
    for solid in solids:
        bb = solid.bbox()
        if bb is None:
            continue
        near = all(bb.mins[i] - radius <= c[i] <= bb.maxs[i] + radius for i in range(3) if i != ignore_axis)
        if not near:
            continue
        changed = solid
        for k, surf in enumerate(surfaces(solid)):
            disp = brush_stroke(surf, center, radius, strength, mode, up=tuple(surf.normal),
                                seed=seed + k, ignore_axis=ignore_axis)
            if disp is not None:
                changed = set_surface(changed, surf, disp)
        if changed is not solid:
            out.append(changed)
    return out


def sew_all(doc: MapDocument, solids: Iterable[Solid] | None = None) -> list[Solid]:
    """Nähte aller Displacements (oder der angegebenen samt Nachbarn) schließen."""
    pool = terrain_solids(doc)
    if solids is not None:
        ids = {s.id for s in solids}
        latest = {s.id: s for s in solids}
        pool = [latest.get(s.id, s) for s in pool]
        boxes = [s.bbox() for s in pool if s.id in ids]
        boxes = [b for b in boxes if b is not None]

        def touches(s: Solid) -> bool:
            bb = s.bbox()
            return bb is not None and any(all(bb.mins[i] - 1 <= b.maxs[i] and b.mins[i] <= bb.maxs[i] + 1
                                              for i in range(3)) for b in boxes)
        pool = [s for s in pool if s.id in ids or touches(s)]
    return sew(pool)


__all__ = ["POWER_LABELS", "TerrainError", "convert", "flatten", "sew_all", "stroke", "terrain_solids", "top_face"]
