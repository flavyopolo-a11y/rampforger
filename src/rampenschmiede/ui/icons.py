"""Symbole für Werkzeuge und Werkzeugleisten.

Alle Symbole sind kleine, selbst gezeichnete SVGs (24×24, Linien), die zur Laufzeit in der
Textfarbe des Themas gefärbt werden. Aktive Werkzeuge leuchten im Schmiede-Orange. So
braucht das Programm keine fremden Icon-Dateien und es gibt keine Lizenzfragen.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

NORMAL = "#e1e4e8"
DISABLED = "#6e737a"
ACTIVE = "#ff8c28"
SIZES = (16, 24, 32, 48)

#: SVG-Inhalt je Symbol, `currentColor` wird ersetzt
_SHAPES: dict[str, str] = {
    # Werkzeuge
    "select": '<path d="M5 3 L5 19 L9.5 14.8 L12.6 21.2 L15.3 20 L12.3 13.6 L18.2 13.6 Z" '
              'fill="currentColor" fill-opacity="0.25"/>',
    "shape": '<path d="M12 2.5 L20.5 7.2 L20.5 16.8 L12 21.5 L3.5 16.8 L3.5 7.2 Z"/>'
             '<path d="M3.5 7.2 L12 12 L20.5 7.2 M12 12 L12 21.5"/>'
             '<path d="M12 12 L20.5 7.2 L20.5 16.8 L12 21.5 Z" fill="currentColor" fill-opacity="0.25" stroke="none"/>',
    "entity": '<path d="M9 18h6M10 21h4"/>'
              '<path d="M12 3a6 6 0 0 0-4 10.5c.8.8 1 1.5 1 2.5h6c0-1 .2-1.7 1-2.5A6 6 0 0 0 12 3z" '
              'fill="currentColor" fill-opacity="0.25"/>',
    "face": '<path d="M3 9 L13 4 L21 10 L11 15 Z" fill="currentColor" fill-opacity="0.3"/>'
            '<path d="M8 6.5 L16 12.5 M6.3 10.7 L17 7"/>'
            '<path d="M3 9 L3 15 L11 21 L21 16 L21 10 M11 15 L11 21"/>',
    "paint": '<path d="M14.5 4.5l5 5L10 19H5v-5z" fill="currentColor" fill-opacity="0.25"/><path d="M12.5 6.5l5 5"/>',
    "clip": '<path d="M4 6h10v14H4z" fill="currentColor" fill-opacity="0.25"/>'
            '<path d="M14 6h6v14h-6" stroke-dasharray="2 2"/><path d="M14 2.5v19"/>',
    "hole": '<path d="M3 4h18v16H3z" fill="currentColor" fill-opacity="0.25"/><path d="M8.5 8.5h7v7h-7z"/>',
    "carve": '<path d="M3 9h18v10H3z" fill="currentColor" fill-opacity="0.25"/>'
             '<path d="M8 4h8v10H8z" stroke-dasharray="2 2"/>',
    # Formen
    "shape_block": '<path d="M12 3 L20.5 7.5 L20.5 16.5 L12 21 L3.5 16.5 L3.5 7.5 Z"/>'
                   '<path d="M3.5 7.5 L12 12 L20.5 7.5 M12 12 L12 21"/>'
                   '<path d="M3.5 7.5 L12 3 L20.5 7.5 L12 12 Z" fill="currentColor" fill-opacity="0.3" stroke="none"/>',
    "shape_wedge": '<path d="M3 19 L3 9 L13 19 Z M3 9 L11 4 L21 14 L13 19 M21 14 L21 14"/>'
                   '<path d="M3 9 L11 4 L21 14 L13 19 Z" fill="currentColor" fill-opacity="0.3" stroke="none"/>',
    "shape_cylinder": '<ellipse cx="12" cy="6" rx="7" ry="2.8" fill="currentColor" fill-opacity="0.3"/>'
                      '<path d="M5 6v12c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8V6"/>',
    "shape_arch": '<path d="M3 20V12a9 9 0 0 1 18 0v8h-4v-8a5 5 0 0 0-10 0v8z" fill="currentColor" fill-opacity="0.3"/>',
    "shape_stairs": '<path d="M3 20v-4h4.5v-4H12V8h4.5V4H21v16z" fill="currentColor" fill-opacity="0.3"/>',
    # Datei und Bearbeiten
    "new": '<path d="M6 2.5h8l4 4v15H6z M14 2.5v4h4"/><path d="M12 11v7M8.5 14.5h7"/>',
    "open": '<path d="M3 6.5a1.5 1.5 0 0 1 1.5-1.5H9l2 2.2h8.5A1.5 1.5 0 0 1 21 8.7V18a1.5 1.5 0 0 1-1.5 1.5h-15'
            'A1.5 1.5 0 0 1 3 18z"/><path d="M3 10.5h18"/>',
    "save": '<path d="M4 4h13l3 3v13H4z"/><path d="M8 4v5h8V4M7.5 20v-6h9v6"/>',
    "undo": '<path d="M9 14 L4 9 L9 4"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="M15 14 L20 9 L15 4"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "grid_finer": '<path d="M4 4h16v16H4z M9.3 4v16 M14.6 4v16 M4 9.3h16 M4 14.6h16"/>',
    "grid_coarser": '<path d="M4 4h16v16H4z M12 4v16 M4 12h16"/>',
    "compile": '<circle cx="12" cy="12" r="9.5"/><path d="M10 8 L16 12 L10 16 Z" fill="currentColor"/>',
    "expert": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    # Texturen
    "ramp": '<path d="M2.5 19 L13 7 L21.5 7 L21.5 19 Z" fill="currentColor" fill-opacity="0.25"/>'
            '<path d="M6 15 L14.5 15 M9.2 11.3 L17.8 11.3"/>',
    # Bibliothek
    "curve": '<path d="M3 20 C3 10 10 4 20 4"/><path d="M8 20 C8 13 13 9 20 9" stroke-dasharray="2 2.2"/>',
    "halfpipe": '<path d="M3 5 L3 9 C3 15 7 19 12 19 C17 19 21 15 21 9 L21 5"/>',
    "bhop": '<path d="M3 17h6v3H3z M10 12h5v3h-5z M16 7h5v3h-5z" fill="currentColor" fill-opacity="0.25"/>',
    "flag": '<path d="M5 21V3.5"/><path d="M5 4h12l-2.5 4L17 12H5" fill="currentColor" fill-opacity="0.25"/>',
    "prefab": '<path d="M3.5 8 L12 3.5 L20.5 8 L20.5 16 L12 20.5 L3.5 16 Z"/><path d="M3.5 8 L12 12.5 L20.5 8'
              ' M12 12.5 L12 20.5"/><path d="M7.7 5.8 L16.3 10.2" />',
    "sun": '<circle cx="12" cy="12" r="4" fill="currentColor" fill-opacity="0.25"/>'
           '<path d="M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8'
           'M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/>',
    "sky": '<path d="M6.5 18.5a4 4 0 0 1-.4-8 6 6 0 0 1 11.6 1.5 3.3 3.3 0 0 1-.2 6.5z" fill="currentColor"'
           ' fill-opacity="0.25"/><path d="M3 21.5h18"/>',
    "palette": '<path d="M12 3a9 9 0 1 0 0 18c1.4 0 2-1 1.6-2.1-.5-1.3.3-2.4 1.7-2.4H18a3 3 0 0 0 3-3'
               'C21 7.2 17 3 12 3z"/><circle cx="7.5" cy="11" r="1.3" fill="currentColor"/>'
               '<circle cx="10.5" cy="7" r="1.3" fill="currentColor"/><circle cx="15.5" cy="7.5" r="1.3" fill="currentColor"/>',
    "eye": '<path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "eye_off": '<path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" stroke-opacity="0.45"/>'
               '<path d="M4 20 L20 4"/>',
}


def names() -> list[str]:
    return sorted(_SHAPES)


def _svg(name: str, color: str) -> bytes:
    body = _SHAPES[name].replace("currentColor", color)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


def pixmap(name: str, size: int, color: str = NORMAL) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(_svg(name, color)))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return pix


@lru_cache(maxsize=None)
def icon(name: str) -> QIcon:
    """Symbol mit Zuständen: normal, deaktiviert und aktiv (eingeschaltet) in Orange."""
    ic = QIcon()
    for size in SIZES:
        ic.addPixmap(pixmap(name, size, NORMAL), QIcon.Normal, QIcon.Off)
        ic.addPixmap(pixmap(name, size, ACTIVE), QIcon.Normal, QIcon.On)
        ic.addPixmap(pixmap(name, size, ACTIVE), QIcon.Active, QIcon.On)
        ic.addPixmap(pixmap(name, size, DISABLED), QIcon.Disabled, QIcon.Off)
        ic.addPixmap(pixmap(name, size, DISABLED), QIcon.Disabled, QIcon.On)
    return ic


__all__ = ["ACTIVE", "icon", "names", "pixmap"]
