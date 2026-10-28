"""Stützen unter Rampen: senkrechte Pfeiler von der Unterseite einer Rampe bis zum Boden.

Eingeschaltet über `Entity.extra["stuetzen"]` der Rampen-Wurzel (Abstand, Dicke). Die Pfeiler
sind Brushes der Rampe selbst (func_detail, `extra["stuetze"]`), wandern also mit, werden mit
ausgewählt und gelöscht. Nach jeder Änderung an der Rampe (Regler, Verschieben, Drehen) baut
`follow_pillars` sie neu: Der Weg der Rampe wird aus der Mitte ihrer Teile abgelesen, in
gleichmäßigem Abstand abgetastet, und jeder Pfeiler reicht bis zum höchsten Brush darunter.
"""
from __future__ import annotations

import json
import math
from typing import Iterable

from .blocks import block_info, is_block_root
from .commands import AddObjects, Command, MacroCommand, RemoveObjects, ReplaceObjects
from .geometry import primitives
from .geometry.brush import ray_intersect_solid
from .geometry.displacement import is_displacement_solid
from .model import EditorInfo, Entity, MapDocument, Solid, owner_id

CONFIG = "stuetzen"
PILLAR = "stuetze"
DEFAULT_CONFIG = {"abstand": 512, "dicke": 32}
#: Ohne Boden darunter reichen Stützen so weit
MAX_DROP = 4096
MIN_HEIGHT = 16
#: Teile der Rampe, die weiter auseinanderliegen, gehören zu verschiedenen Ästen
BREAK = 96.0
PILLAR_COLOR = (150, 150, 160)


def has_pillars(root: Entity | None) -> bool:
    return isinstance(root, Entity) and CONFIG in root.extra


def _ramp_solids(doc: MapDocument, root_id: int) -> list[Solid]:
    """Sichtbare Teile der Rampe; ohne solche (reine Kollision) die Playerclip-Hülle."""
    visible = [s for s in doc.children(root_id) if PILLAR not in s.extra]
    return visible or [s for s in doc.solids() if owner_id(s) == root_id and s.parent_id is None]


def _spines(parts: list[Solid]) -> list[list[tuple[float, float]]]:
    """Weg(e) der Rampe in der Draufsicht: durch die Mitten ihrer Teile (in Bau-Reihenfolge),
    an den Enden um die halbe Teil-Länge verlängert. Große Sprünge trennen Äste."""
    cents: list[tuple[float, float]] = []
    clouds: list[list[tuple[float, float]]] = []
    for s in sorted(parts, key=lambda s: s.id):
        pts = [(p[0], p[1]) for p in s.vertices()]
        if pts:
            cents.append((sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)))
            clouds.append(pts)
    n = len(cents)
    if n == 0:
        return []

    def direction(i: int) -> tuple[float, float]:
        if n == 1:
            # Ein Teil: Längsachse aus der Kovarianz
            cx, cy = cents[0]
            pts = clouds[0]
            sxx = sum((p[0] - cx) ** 2 for p in pts)
            syy = sum((p[1] - cy) ** 2 for p in pts)
            sxy = sum((p[0] - cx) * (p[1] - cy) for p in pts)
            a = 0.5 * math.atan2(2 * sxy, sxx - syy)
            return math.cos(a), math.sin(a)
        a, b = cents[max(0, i - 1)], cents[min(n - 1, i + 1)]
        d = (b[0] - a[0], b[1] - a[1])
        length = math.hypot(*d) or 1.0
        return d[0] / length, d[1] / length

    dirs = [direction(i) for i in range(n)]
    halves = []
    for i in range(n):
        proj = [(p[0] - cents[i][0]) * dirs[i][0] + (p[1] - cents[i][1]) * dirs[i][1] for p in clouds[i]]
        halves.append((max(proj) - min(proj)) / 2)

    lines: list[list[tuple[float, float]]] = []
    first = 0
    for i in range(1, n + 1):
        if i < n and math.dist(cents[i], cents[i - 1]) <= halves[i] + halves[i - 1] + BREAK:
            continue
        k, m = first, i - 1
        start = (cents[k][0] - dirs[k][0] * halves[k], cents[k][1] - dirs[k][1] * halves[k])
        end = (cents[m][0] + dirs[m][0] * halves[m], cents[m][1] + dirs[m][1] * halves[m])
        lines.append([start, *cents[k:m + 1], end])
        first = i
    return lines


def _samples(line: list[tuple[float, float]], spacing: float) -> list[tuple[float, float]]:
    """Punkte im Abstand `spacing`, gleichmäßig verteilt, ein halber Abstand vom Rand."""
    lengths = [math.dist(line[i], line[i + 1]) for i in range(len(line) - 1)]
    total = sum(lengths)
    if total < 1:
        return []
    count = max(1, int(total // spacing))
    step = total / count
    out = []
    for k in range(count):
        target = step * (k + 0.5)
        for i, seg in enumerate(lengths):
            if target <= seg or i == len(lengths) - 1:
                t = target / seg if seg > 0 else 0.0
                a, b = line[i], line[i + 1]
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                break
            target -= seg
    return out


def _underside(parts: Iterable[Solid], x: float, y: float) -> float | None:
    """Tiefster Punkt der Rampe senkrecht über (x, y)."""
    best = None
    for s in parts:
        bb = s.bbox()
        if bb is None or not (bb.mins[0] <= x <= bb.maxs[0] and bb.mins[1] <= y <= bb.maxs[1]):
            continue
        t = ray_intersect_solid(s, (x, y, bb.mins[2] - 1), (0.0, 0.0, 1.0))
        if t is not None:
            z = bb.mins[2] - 1 + t
            best = z if best is None else min(best, z)
    return best


def _ground(doc: MapDocument, own: set[int], x: float, y: float, below: float) -> float | None:
    """Oberkante des höchsten Brushes unter (x, y, below), ohne Trigger und die Rampe selbst."""
    best = None
    for s in doc.solids():
        if s.id in own or is_displacement_solid(s) or PILLAR in s.extra:
            continue
        bb = s.bbox()
        if bb is None or bb.maxs[2] > below + 1e-6 or not (bb.mins[0] <= x <= bb.maxs[0] and bb.mins[1] <= y <= bb.maxs[1]):
            continue
        if any("WATER" in f.material.upper() for f in s.faces):
            continue  # Stützen stehen auf dem Grund, nicht auf dem Wasser
        if any(f.material.upper() in ("TOOLS/TOOLSTRIGGER", "TOOLS/TOOLSSKYBOX") for f in s.faces) and bb.maxs[2] > bb.mins[2] + 64:
            continue  # Trigger und Skybox-Wände tragen nichts; ein Skybox-Boden schon (dünn)
        parent = doc.get(s.parent_id) if s.parent_id is not None else None
        if isinstance(parent, Entity) and parent.classname.lower().startswith("trigger_"):
            continue
        t = ray_intersect_solid(s, (x, y, below), (0.0, 0.0, -1.0))
        if t is not None:
            z = below - t
            best = z if best is None else max(best, z)
    return best


def _material(parts: list[Solid]) -> str:
    """Seiten-Material der Rampe (Werkzeug-Texturen wie Nodraw zählen nicht)."""
    counts: dict[str, int] = {}
    for s in parts:
        for f in s.faces:
            m = f.material.upper()
            if not m.startswith("TOOLS/"):
                # Steile und senkrechte Seiten zählen mehr als die Surf-Fläche
                counts[m] = counts.get(m, 0) + (2 if abs(f.plane.normal[2]) < 0.3 else 1)
    return max(counts, key=lambda m: counts[m]) if counts else "DEV/DEV_MEASUREGENERIC01B"


def pillar_faces(doc: MapDocument, root_id: int, spacing: float, size: float) -> list[tuple]:
    parts = _ramp_solids(doc, root_id)
    if not parts:
        return []
    own = {s.id for s in parts}
    material = _material(parts)
    half = size / 2
    out = []
    for line in _spines(parts):
        for x, y in _samples(line, spacing):
            gx, gy = round(x), round(y)
            top = _underside(parts, gx, gy)
            if top is None:
                continue
            corners = [_underside(parts, gx + dx, gy + dy) for dx in (-half, half) for dy in (-half, half)]
            top = min([top, *[c for c in corners if c is not None]])
            ground = _ground(doc, own, gx, gy, top - 1)
            bottom = ground if ground is not None else top - MAX_DROP
            top_i, bottom_i = int(math.floor(top)), int(math.floor(bottom))
            if top_i - bottom_i < MIN_HEIGHT:
                continue
            out += primitives.block((gx - half, gy - half, bottom_i), (gx + half, gy + half, top_i), material)
    return out


def _signature(root: Entity, cfg: dict) -> str:
    info = block_info(root) or {}
    return json.dumps([info.get("values"), info.get("placement"), cfg.get("abstand"), cfg.get("dicke")],
                      sort_keys=True, default=str)


def set_pillars(doc: MapDocument, root_ids: Iterable[int], on: bool, spacing: int = 512,
                size: int = 32) -> Command | None:
    """Stützen für Rampen ein- oder ausschalten (die Pfeiler baut danach `follow_pillars`)."""
    cmds: list[Command] = []
    for rid in root_ids:
        root = doc.get(rid)
        if not isinstance(root, Entity) or not is_block_root(root):
            continue
        if on:
            extra = {**root.extra, CONFIG: {"abstand": spacing, "dicke": size}}
        else:
            extra = {k: v for k, v in root.extra.items() if k != CONFIG}
            old = [s.id for s in doc.children(rid) if PILLAR in s.extra]
            if old:
                cmds.append(RemoveObjects(old))
        if extra != root.extra:
            cmds.append(ReplaceObjects([root.replace(extra=extra)]))
    return MacroCommand(cmds, "Stützen an" if on else "Stützen aus") if cmds else None


def follow_pillars(doc: MapDocument) -> Command | None:
    """Stützen der Rampen neu bauen, deren Form oder Lage sich geändert hat."""
    cmds: list[Command] = []
    for root in list(doc.entities()):
        cfg = root.extra.get(CONFIG)
        if not cfg or not is_block_root(root):
            continue
        existing = [s for s in doc.children(root.id) if PILLAR in s.extra]
        sig = _signature(root, cfg)
        if existing and cfg.get("sig") == sig:
            continue
        faces = pillar_faces(doc, root.id, float(cfg.get("abstand", 512)), float(cfg.get("dicke", 32)))
        if not existing and not faces and cfg.get("sig") == sig:
            continue
        new = [Solid(id=doc.new_id(), faces=f, parent_id=root.id, editor=EditorInfo(color=PILLAR_COLOR),
                     extra={PILLAR: True}) for f in faces]
        if existing:
            cmds.append(RemoveObjects([s.id for s in existing]))
        if new:
            cmds.append(AddObjects(new))
        cmds.append(ReplaceObjects([root.replace(extra={**root.extra, CONFIG: {**cfg, "sig": sig}})]))
    return MacroCommand(cmds, "Stützen anpassen") if cmds else None


__all__ = ["CONFIG", "DEFAULT_CONFIG", "PILLAR", "follow_pillars", "has_pillars", "pillar_faces", "set_pillars"]
