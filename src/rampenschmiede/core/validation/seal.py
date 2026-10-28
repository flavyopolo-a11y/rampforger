"""Schnelle Dicht-Prüfung: Sind alle Punkt-Entities von Welt-Brushes umschlossen?

Das ist eine Vorhersage dessen, was vbsp als Leck meldet, ohne zu kompilieren:
Die Map wird in ein Würfelraster zerlegt, dann wird von außen geflutet. Erreicht die
Flut eine Entity, ist die Map undicht, und der Weg der Flut ist die Leck-Spur.

Grenzen: Die Zellen sind ab großen Maps gröber als 8 Units. Ein Brush belegt jede Zelle,
die er berührt, sehr schmale Spalte (kleiner als eine Zelle) werden daher übersehen.
Was die Prüfung als undicht meldet, ist dagegen praktisch immer wirklich undicht.
Maßgeblich bleibt vbsp.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from ..geometry.displacement import is_displacement_solid
from ..mathutil import BBox, Point
from ..model import Entity, MapDocument, Solid

#: Seiten mit diesen Materialien machen einen Brush nicht dicht (Clips, Trigger, Hint, ...)
NON_SEALING = frozenset({
    "TOOLS/TOOLSCLIP", "TOOLS/TOOLSPLAYERCLIP", "TOOLS/TOOLSNPCCLIP", "TOOLS/TOOLSHINT",
    "TOOLS/TOOLSSKIP", "TOOLS/TOOLSTRIGGER", "TOOLS/TOOLSFOG", "TOOLS/TOOLSAREAPORTAL",
    "TOOLS/TOOLSOCCLUDER", "TOOLS/TOOLSBLOCK_LOS", "TOOLS/TOOLSINVISIBLELADDER",
})
MIN_CELL = 8.0
MAX_CELLS = 2_000_000


@dataclass
class SealResult:
    sealed: bool
    #: Entity, deren Leck gefunden wurde (die erste, nach Weglänge)
    entity_id: int | None = None
    #: Weg von der Entity nach außen, für die Anzeige als Leck-Spur
    path: list[Point] = field(default_factory=list)
    leaking_ids: list[int] = field(default_factory=list)
    checked: int = 0
    cell_size: float = 0.0

    @property
    def unknown(self) -> bool:
        return self.checked == 0


def seals(solid: Solid) -> bool:
    """Ein Welt-Brush dichtet ab, wenn nicht alle Seiten Werkzeug-Texturen ohne Wandwirkung tragen."""
    if solid.parent_id is not None:  # func_detail und andere Brush-Entities dichten nie
        return False
    if any(f.extra.get("raw") for f in solid.faces) and is_displacement_solid(solid):
        return False  # Gelände (Displacements) dichtet in vbsp nicht ab
    # Eine Wasser-Seite macht in vbsp den ganzen Brush zu Wasser (auch mit Nodraw ringsum)
    if any("WATER" in f.material.upper() for f in solid.faces):
        return False
    return any(f.material.upper() not in NON_SEALING for f in solid.faces)


SPAWNS = frozenset({"info_player_start", "info_player_counterterrorist", "info_player_terrorist",
                    "info_player_deathmatch", "info_player_teamspawn"})


def _entity_points(doc: MapDocument) -> list[tuple[int, Point]]:
    parents = {s.parent_id for s in doc.solids() if s.parent_id is not None}
    pts = []
    for e in doc.entities():
        o = e.origin
        if o is not None and e.id not in parents:
            pts.append((e.id, o))
    return pts


def check_seal(doc: MapDocument, max_cells: int = MAX_CELLS) -> SealResult:
    points = _entity_points(doc)
    if not points:
        return SealResult(sealed=True)
    solids = [s for s in doc.solids() if seals(s) and s.is_valid()]
    boxes = [s.bbox() for s in solids]
    bounds = BBox.union([b for b in boxes if b is not None] + [BBox(p, p) for _, p in points])
    assert bounds is not None
    extent = [bounds.maxs[i] - bounds.mins[i] for i in range(3)]
    volume = max(1.0, (extent[0] + 1) * (extent[1] + 1) * (extent[2] + 1))
    cell = max(MIN_CELL, (volume / max_cells) ** (1 / 3))
    cell = 2 ** math.ceil(math.log2(cell))  # Zweierpotenz: Rasterkanten fallen auf Brush-Kanten
    pad = 2
    origin = np.array([math.floor(bounds.mins[i] / cell) - pad for i in range(3)], dtype=np.int64)
    top = np.array([math.ceil(bounds.maxs[i] / cell) + pad for i in range(3)], dtype=np.int64)
    shape = tuple(int(v) for v in (top - origin))
    solid = np.zeros(shape, dtype=bool)
    h = cell / 2

    for s, box in zip(solids, boxes):
        if box is None:
            continue
        lo = [max(0, int(math.floor(box.mins[i] / cell)) - int(origin[i])) for i in range(3)]
        hi = [min(shape[i], int(math.ceil(box.maxs[i] / cell)) - int(origin[i])) for i in range(3)]
        if any(hi[i] <= lo[i] for i in range(3)):
            continue
        centers = [(np.arange(lo[i], hi[i]) + origin[i]) * cell + h for i in range(3)]
        cx, cy, cz = np.meshgrid(*centers, indexing="ij")
        inside = np.ones(cx.shape, dtype=bool)
        for f in s.faces:
            n, d = f.plane.normal, f.plane.dist
            # Zelle ganz vor der Ebene (außerhalb des Brushes)? Dann gehört sie nicht dazu.
            reach = (abs(n[0]) + abs(n[1]) + abs(n[2])) * h
            # Zellen, die den Brush nur an einer Fläche berühren, gelten nicht als belegt
            inside &= (n[0] * cx + n[1] * cy + n[2] * cz - d) < reach - 1e-6
        solid[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]] |= inside

    empty = ~solid
    dist = np.full(shape, -1, dtype=np.int32)
    frontier = np.zeros(shape, dtype=bool)
    frontier[0, :, :] = frontier[-1, :, :] = True
    frontier[:, 0, :] = frontier[:, -1, :] = True
    frontier[:, :, 0] = frontier[:, :, -1] = True
    frontier &= empty
    dist[frontier] = 0
    reached = frontier.copy()

    cells = {}
    for eid, p in points:
        idx = tuple(int(math.floor(p[i] / cell)) - int(origin[i]) for i in range(3))
        # Steht die Entity knapp über einem Boden, der ihre grobe Zelle belegt: Zelle darüber
        for up in (1, 2):
            if empty[idx] or idx[2] + up >= shape[2]:
                break
            above = (idx[0], idx[1], idx[2] + up)
            if empty[above] and (idx[2] + up + int(origin[2])) * cell - p[2] < 64:
                idx = above
                break
        cells[eid] = idx
    targets = [idx for idx in cells.values() if empty[idx]]
    step = 0
    while frontier.any():
        if targets and all(reached[t] for t in targets):
            break
        grown = np.zeros(shape, dtype=bool)
        grown[1:] |= frontier[:-1]
        grown[:-1] |= frontier[1:]
        grown[:, 1:] |= frontier[:, :-1]
        grown[:, :-1] |= frontier[:, 1:]
        grown[:, :, 1:] |= frontier[:, :, :-1]
        grown[:, :, :-1] |= frontier[:, :, 1:]
        frontier = grown & empty & ~reached
        step += 1
        dist[frontier] = step
        reached |= frontier

    result = SealResult(sealed=True, checked=len(points), cell_size=cell)
    def is_spawn(eid: int) -> bool:
        e = doc.get(eid)
        return isinstance(e, Entity) and e.classname in SPAWNS

    # Spawns zuerst: Ein offener Spawn ist das, was man beim Testen sofort merkt
    leaking = [(not is_spawn(eid), int(dist[idx]), eid) for eid, idx in cells.items() if empty[idx] and reached[idx]]
    if not leaking:
        return result
    leaking.sort()
    result.sealed = False
    result.leaking_ids = [eid for *_, eid in leaking]
    result.entity_id = leaking[0][2]
    result.path = _trace(dist, cells[result.entity_id], origin, cell, dict(points)[result.entity_id])
    return result


def _trace(dist: np.ndarray, start: tuple[int, int, int], origin: np.ndarray, cell: float, first: Point) -> list[Point]:
    """Von der Entity-Zelle immer zur Nachbarzelle mit kleinerem Abstand, bis nach außen."""
    shape = dist.shape
    cur = start
    cells = [cur]
    while dist[cur] > 0:
        best = None
        for axis in range(3):
            for delta in (-1, 1):
                nb = list(cur)
                nb[axis] += delta
                if 0 <= nb[axis] < shape[axis] and dist[tuple(nb)] == dist[cur] - 1:
                    best = tuple(nb)
                    break
            if best:
                break
        if best is None:
            break
        cur = best  # type: ignore[assignment]
        cells.append(cur)
    pts = [first] + [tuple(float((c[i] + origin[i]) * cell + cell / 2) for i in range(3)) for c in cells[1:]]
    return _simplify(pts)  # type: ignore[arg-type]


def _simplify(points: list[Point]) -> list[Point]:
    """Punkte auf geraden Strecken weglassen."""
    if len(points) < 3:
        return points
    out = [points[0]]
    for i in range(1, len(points) - 1):
        a, b, c = out[-1], points[i], points[i + 1]
        d1 = tuple(b[k] - a[k] for k in range(3))
        d2 = tuple(c[k] - b[k] for k in range(3))
        cross = (d1[1] * d2[2] - d1[2] * d2[1], d1[2] * d2[0] - d1[0] * d2[2], d1[0] * d2[1] - d1[1] * d2[0])
        if any(abs(x) > 1e-6 for x in cross):
            out.append(b)
    out.append(points[-1])
    return out


def describe(doc: MapDocument, result: SealResult) -> str:
    if result.unknown:
        return "Keine Entities: Dichtheit nicht prüfbar"
    if result.sealed:
        return "Map ist dicht"
    ent = doc.get(result.entity_id) if result.entity_id is not None else None
    name = ent.classname if isinstance(ent, Entity) else "Entity"
    more = len(result.leaking_ids) - 1
    extra = f" (und {more} weitere)" if more > 0 else ""
    return f"Leck: {name}{extra} ist nicht umschlossen"
