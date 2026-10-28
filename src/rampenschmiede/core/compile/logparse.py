"""Compiler-Ausgabe einordnen: Fehler, Warnungen und Verweise auf Objekte.

vbsp nennt Brushes mit ihrer VMF-ID ("Brush 12: ...") und Entities mit ihrer Position
in der Datei ("Entity 3, Brush 40: ...", 0 ist die Welt). Leaks nennen Klassenname und
Position. Daraus wird ein Verweis, über den der Log-Eintrag zum Objekt springt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Level(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    STEP = "step"  # Kopfzeile eines Schritts (von uns)


@dataclass(frozen=True)
class LogLine:
    text: str
    level: Level = Level.INFO
    brush_id: int | None = None          # VMF-ID eines Brushes
    entity_index: int | None = None      # Position der Entity in der VMF (0 = Welt)
    position: tuple[float, float, float] | None = None
    leak: bool = False

    @property
    def has_target(self) -> bool:
        return self.brush_id is not None or (self.entity_index or 0) > 0 or self.position is not None


_NUM = r"(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
_ENTITY_BRUSH = re.compile(r"\bEntity\s+(\d+),\s*Brush\s+(\d+)", re.I)
_BRUSH = re.compile(r"\b(?:Brush|brush id|solid)\s*#?\s*(\d+)\b", re.I)
_ENTITY_INDEX = re.compile(r"\bEntity\s+(\d+)\b(?!\s*\()", re.I)
_POSITION = re.compile(rf"\(\s*{_NUM}[\s,]+{_NUM}[\s,]+{_NUM}\s*\)")
_LEAK_ENTITY = re.compile(rf"Entity\s+\S+\s*\(\s*{_NUM}[\s,]+{_NUM}[\s,]+{_NUM}\s*\)\s*leaked", re.I)

_ERROR_WORDS = re.compile(
    r"\*\*\*\*\s*leaked\s*\*\*\*\*|\berror\b|\bfatal\b|MAX_MAP_|couldn't open|could not open|"
    r"exceeded|too many|\bfailed\b|can't load|\bcrash",
    re.I,
)
_WARNING_WORDS = re.compile(r"\bwarning\b|not found|\bmissing\b|degenerate|\binvalid\b|mixed face contents", re.I)


def classify(text: str) -> LogLine:
    stripped = text.strip()
    leak = "leaked" in stripped.lower()
    if _ERROR_WORDS.search(stripped) or leak:
        level = Level.ERROR
    elif _WARNING_WORDS.search(stripped):
        level = Level.WARNING
    else:
        level = Level.INFO

    brush = entity = None
    pos = None
    m = _ENTITY_BRUSH.search(stripped)
    if m:
        entity, brush = int(m.group(1)), int(m.group(2))
    else:
        m = _BRUSH.search(stripped)
        if m:
            brush = int(m.group(1))
        m = _ENTITY_INDEX.search(stripped)
        if m:
            entity = int(m.group(1))
    m = _LEAK_ENTITY.search(stripped) or _POSITION.search(stripped)
    if m:
        pos = (float(m.group(1)), float(m.group(2)), float(m.group(3)))
    if level is Level.INFO:
        # Verweise in reinen Infozeilen sind meist Statistik, keine Probleme
        brush = entity = None
        pos = None
    return LogLine(text.rstrip("\r\n"), level, brush, entity, pos, leak)


class LineSplitter:
    """Setzt Zeilen aus Bytes zusammen. Fortschritt wie "0...1...2" kommt ohne Zeilenende."""

    def __init__(self, encoding: str = "utf-8") -> None:
        self.encoding = encoding
        self._buf = b""

    def feed(self, data: bytes) -> list[str]:
        self._buf += data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        *lines, self._buf = self._buf.split(b"\n")
        return [self._decode(line) for line in lines]

    @property
    def partial(self) -> str:
        return self._decode(self._buf)

    def flush(self) -> list[str]:
        rest, self._buf = self._buf, b""
        return [self._decode(rest)] if rest else []

    def _decode(self, data: bytes) -> str:
        try:
            return data.decode(self.encoding)
        except UnicodeDecodeError:
            return data.decode("cp1252", errors="replace")


def parse_pointfile(text: str) -> list[tuple[float, float, float]]:
    """Leak-Spur aus einer .lin-Datei: ein Punkt pro Zeile."""
    points = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            try:
                points.append((float(parts[0]), float(parts[1]), float(parts[2])))
            except ValueError:
                continue
    return points


def parse_portalfile(text: str) -> list[list[tuple[float, float, float]]]:
    """Portale aus einer .prt-Datei von vbsp (PRT1): je Portal die Ecken des Vielecks.
    Zeilen: `PRT1`, Zahl der Blätter, Zahl der Portale, dann je Portal
    `<Ecken> <Blatt> <Blatt> (x y z) (x y z) …`."""
    polys = []
    lines = text.splitlines()
    if not lines or not lines[0].strip().upper().startswith("PRT1"):
        raise ValueError("Keine Portal-Datei (PRT1)")
    for line in lines[3:]:
        if "(" not in line:
            continue
        head, _, rest = line.partition("(")
        try:
            count = int(head.split()[0])
        except (ValueError, IndexError):
            continue
        pts = []
        for chunk in ("(" + rest).split("(")[1:]:
            vals = chunk.split(")")[0].split()
            if len(vals) == 3:
                try:
                    pts.append((float(vals[0]), float(vals[1]), float(vals[2])))
                except ValueError:
                    break
        if len(pts) == count and count >= 3:
            polys.append(pts)
    return polys
