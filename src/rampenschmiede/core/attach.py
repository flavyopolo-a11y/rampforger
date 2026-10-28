"""Zonen sitzen auf ihrem Block: Startzone, Stage- und Zielzone passen sich der Plattform
darunter an und folgen ihr, wenn sie verschoben oder in der Größe geändert wird.

Die Verbindung steht in `Entity.extra["sitzt_auf"]` der Zonen-Wurzel: ID des Blocks und
dessen Hülle beim letzten Anpassen. Nur wenn sich die Hülle des Blocks ändert, wird die Zone
neu angepasst; wer die Zone selbst verschiebt oder größer zieht, behält seine Änderung.
"""
from __future__ import annotations

import math
from typing import Any

from ..i18n import tr
from .blocks import block_info, is_block_root, rebuild
from .commands import Command, MacroCommand, ReplaceObjects, SwapObjects
from .geometry.displacement import is_displacement_solid
from .mathutil import BBox
from .model import Entity, MapDocument, owner_id
from .surf.catalog import Placement

SITS_ON = "sitzt_auf"
ZONE_TEMPLATES = ("zone_start", "zone_ende", "zone_stage")
#: Abstand der Zone zum Rand des Blocks
ZONE_MARGIN = 16
ZONE_MIN = 32


def is_zone_template(key: str) -> bool:
    return key in ZONE_TEMPLATES


def _supports(doc: MapDocument) -> list[tuple[int, BBox]]:
    """Mögliche Blöcke: Welt-Brushes, Brush-Entities und Bausteine, aber keine Trigger."""
    out: dict[int, BBox] = {}
    for s in doc.solids():
        if is_displacement_solid(s) or any(f.material.upper().startswith("TOOLS/TOOLSTRIGGER") for f in s.faces):
            continue
        root = owner_id(s) or s.id
        owner = doc.get(root)
        if isinstance(owner, Entity) and owner.classname.lower().startswith("trigger_"):
            continue
        bb = s.bbox()
        if bb is not None:
            out[root] = bb if root not in out else BBox.union([out[root], bb])  # type: ignore[assignment]
    return list(out.items())


def support_below(doc: MapDocument, x: float, y: float, z: float | None = None, reach: float = 64) -> int | None:
    """Der Block unter dem Punkt: höchste Oberkante unter (bzw. knapp über) `z`, ohne `z` die
    höchste überhaupt. Riesige Böden (über 4096 Units) zählen nicht als Block."""
    best: tuple[float, int] | None = None
    for root, bb in _supports(doc):
        if not (bb.mins[0] < x < bb.maxs[0] and bb.mins[1] < y < bb.maxs[1]):
            continue
        if max(bb.size[0], bb.size[1]) > 4096:
            continue
        top = bb.maxs[2]
        if z is not None and top > z + reach:
            continue
        if best is None or top > best[0]:
            best = (top, root)
    return best[1] if best is not None else None


def fit_on(box: BBox, yaw: float = 0.0, margin: int = ZONE_MARGIN) -> tuple[dict, Placement]:
    """Länge, Breite und Platzierung einer Zone, die auf der Oberseite von `box` sitzt.
    Die Länge läuft in Blickrichtung `yaw` (für Momentum die Startrichtung)."""
    a = math.radians(yaw)
    along_y = abs(math.sin(a)) > abs(math.cos(a))
    sx, sy = (box.size[1], box.size[0]) if along_y else (box.size[0], box.size[1])
    length = max(ZONE_MIN, int(round(sx)) - 2 * margin)
    width = max(ZONE_MIN, int(round(sy)) - 2 * margin)
    x = int(round(box.center[0] - math.cos(a) * length / 2))
    y = int(round(box.center[1] - math.sin(a) * length / 2))
    return {"laenge": length, "breite": width}, Placement(x, y, int(round(box.maxs[2])), yaw)


def link(support_id: int, box: BBox) -> dict[str, Any]:
    return {"id": support_id, "box": [*box.mins, *box.maxs]}


def follow_supports(doc: MapDocument) -> Command | None:
    """Zonen, deren Block sich verändert hat, neu anpassen (wird nach jedem Befehl angehängt)."""
    cmds: list[Command] = []
    for e in list(doc.entities()):
        info = e.extra.get(SITS_ON)
        if not info or not is_block_root(e):
            continue
        support = doc.get(info["id"])
        if support is None:
            # Block gelöscht: Zone bleibt, wo sie ist
            extra = {k: v for k, v in e.extra.items() if k != SITS_ON}
            cmds.append(ReplaceObjects([e.replace(extra=extra)], tr("Zone lösen")))
            continue
        box = doc.bbox([support.id])
        if box is None:
            continue
        now = [*box.mins, *box.maxs]
        if all(abs(a - b) < 1e-6 for a, b in zip(now, info["box"])):
            continue
        bi = block_info(e)
        values, at = fit_on(box, bi["placement"][3] if bi else 0.0)
        new, _gen = rebuild(doc, e, values, at)
        new[0] = new[0].replace(extra={**new[0].extra, SITS_ON: link(support.id, box)})
        cmds.append(SwapObjects([e.id] + [s.id for s in doc.attached([e.id])], new, tr("Zone folgt dem Block")))
    if not cmds:
        return None
    return MacroCommand(cmds, tr("Zone folgt dem Block"))


__all__ = ["SITS_ON", "ZONE_TEMPLATES", "fit_on", "follow_supports", "is_zone_template", "link", "support_below"]
