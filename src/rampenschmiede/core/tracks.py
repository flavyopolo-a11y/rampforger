"""Pfade aus path_track- bzw. path_corner-Punkten, die der Reihe nach aufeinander zeigen
(für Züge, bewegliche Plattformen, Kameras). Wie das Pfad-Werkzeug in Hammer, nur dass die
Namen und Verweise gleich stimmen."""
from __future__ import annotations

from typing import Sequence

from .model import Entity, MapDocument
from .model.objects import EditorInfo

P3 = tuple[float, float, float]
PATH_CLASSES = ("path_track", "path_corner")
#: Farbe der Pfad-Punkte im Editor (wie in Hammer hellgrün)
PATH_COLOR = (120, 230, 140)


def free_base(doc: MapDocument, base: str, count: int) -> str:
    """Namensstamm, unter dem `base_1` … `base_count` alle noch frei sind."""
    used = {e.get("targetname").lower() for e in doc.entities()}
    stem, n = base, 1
    while any(f"{stem}_{i}".lower() in used for i in range(1, count + 1)):
        n += 1
        stem = f"{base}{n}"
    return stem


def _fmt(v: float) -> str:
    r = round(v, 2)
    return str(int(r)) if r == int(r) else f"{r:g}"


def path_entities(doc: MapDocument, points: Sequence[P3], classname: str = "path_track", base: str = "pfad",
                  closed: bool = False, speed: int = 0) -> list[Entity]:
    """Je Punkt eine Entity `<stamm>_<n>`, jede zeigt mit `target` auf die nächste; geschlossen
    zeigt die letzte wieder auf die erste. `speed` > 0 setzt die Geschwindigkeit der Züge."""
    if len(points) < 2:
        return []
    stem = free_base(doc, base, len(points))
    names = [f"{stem}_{i + 1}" for i in range(len(points))]
    out = []
    for i, p in enumerate(points):
        kvs = [("targetname", names[i]), ("origin", " ".join(_fmt(c) for c in p))]
        nxt = i + 1 if i + 1 < len(points) else (0 if closed else None)
        if nxt is not None:
            kvs.append(("target", names[nxt]))
        if speed > 0 and classname == "path_track":
            kvs.append(("speed", str(speed)))
        out.append(Entity(id=doc.new_id(), classname=classname, keyvalues=tuple(kvs),
                          editor=EditorInfo(color=PATH_COLOR)))
    return out


def path_segments(doc: MapDocument) -> list[tuple[P3, P3]]:
    """Verbindungen aller Pfad-Punkte (target, bei path_track auch altpath) für die Ansichten."""
    by_name: dict[str, Entity] = {}
    nodes = [e for e in doc.entities() if e.classname.lower() in PATH_CLASSES]
    for e in nodes:
        if e.get("targetname"):
            by_name.setdefault(e.get("targetname").lower(), e)
    segs = []
    for e in nodes:
        a = e.origin
        if a is None:
            continue
        for key in ("target", "altpath"):
            t = by_name.get(e.get(key).lower()) if e.get(key) else None
            if t is not None and t.origin is not None and t.id != e.id:
                segs.append((a, t.origin))
    return segs


__all__ = ["PATH_CLASSES", "PATH_COLOR", "free_base", "path_entities", "path_segments"]
