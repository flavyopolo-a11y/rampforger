"""Himmel für die 3D-Ansicht: die sechs Skybox-Bilder eines `skyname` aus der Material-Bibliothek.

Die Bilder liegen in der Reihenfolge, in der der Shader sie erwartet (rt, lf, bk, ft, up, dn
für +X, -X, +Y, -Y, oben, unten). Fehlt das untere Bild (bei vielen Himmeln nur ein
Platzhalter), wird es mit der Farbe am unteren Rand der Seitenbilder gefüllt.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.materials import MaterialLibrary

#: Reihenfolge der Ebenen im Shader
SKY_SUFFIXES = ("rt", "lf", "bk", "ft", "up", "dn")
#: So groß wie die Vorschau-Texturen der Bibliothek (PREVIEW_SIZE)
SKY_SIZE = 256


@dataclass(frozen=True)
class SkyImages:
    name: str
    layers: tuple[bytes, ...]  # 6 × SKY_SIZE² RGBA
    size: int = SKY_SIZE


def sky_material(name: str, suffix: str) -> str:
    return f"skybox/{name}{suffix}"


def available_skies(library: MaterialLibrary | None) -> list[str]:
    """Namen aller Himmel, für die es mindestens die Seitenbilder gibt."""
    if library is None:
        return []
    names = set(library.names())
    out = []
    for n in names:
        if n.startswith("skybox/") and n.endswith("up"):
            base = n[len("skybox/"):-2]
            if base and all(sky_material(base, s) in names for s in ("rt", "lf", "ft", "bk")):
                out.append(base)
    return sorted(out, key=str.lower)


def _resize(rgba: bytes, w: int, h: int, size: int) -> bytes:
    if (w, h) == (size, size):
        return rgba
    from PIL import Image

    return Image.frombytes("RGBA", (w, h), rgba).resize((size, size), Image.Resampling.BILINEAR).tobytes()


def _bottom_color(layers: list[bytes | None], size: int) -> bytes:
    """Mittlere Farbe der untersten Bildzeile der Seitenbilder."""
    total = [0, 0, 0]
    count = 0
    row = (size - 1) * size * 4
    for data in layers[:4]:
        if data is None:
            continue
        line = data[row:row + size * 4]
        for c in range(3):
            total[c] += sum(line[c::4])
        count += size
    if not count:
        return bytes((90, 90, 90, 255))
    return bytes((total[0] // count, total[1] // count, total[2] // count, 255))


def load_sky(library: MaterialLibrary | None, name: str, size: int = SKY_SIZE) -> SkyImages | None:
    """Alle sechs Bilder oder None, wenn der Himmel (oder eine Seite) fehlt."""
    if library is None or not name:
        return None
    layers: list[bytes | None] = []
    for suffix in SKY_SUFFIXES:
        img = library.texture(sky_material(name, suffix))
        if img is None or not img.width or not img.height:
            layers.append(None)
            continue
        # Platzhalter-Bilder (z. B. 4×4 unten) wie fehlende behandeln
        if suffix == "dn" and min(img.width, img.height) < 16:
            layers.append(None)
            continue
        layers.append(_resize(img.rgba, img.width, img.height, size))
    if any(data is None for data in layers[:5]):
        return None
    if layers[5] is None:
        layers[5] = _bottom_color(layers, size) * (size * size)
    return SkyImages(name, tuple(layers), size)  # type: ignore[arg-type]


class SkyCache:
    """Merkt sich den zuletzt geladenen Himmel je Bibliothek (Laden dauert einen Moment)."""

    def __init__(self) -> None:
        self._key: tuple[int, str] | None = None
        self._sky: SkyImages | None = None
        #: Steigt bei jedem neu geladenen Himmel (Ansichten laden dann neu hoch)
        self.generation = 0

    def get(self, library: MaterialLibrary | None, name: str) -> SkyImages | None:
        key = (id(library), name.lower())
        if key != self._key:
            self._key = key
            try:
                self._sky = load_sky(library, name)
            except Exception:  # kaputte Textur: dann eben kein Himmel
                self._sky = None
            self.generation += 1
        return self._sky

    def forget(self) -> None:
        self._key = None
