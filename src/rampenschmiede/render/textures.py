"""Texturen für die 3D-Ansicht: jedem Material eine Ebene in einem Textur-Array.

Der Atlas ist reine CPU-Seite und wird von allen Ansichten geteilt. Jede Ansicht lädt
neu hinzugekommene Ebenen in ihr eigenes GL-Textur-Array hoch (siehe gl_renderer).
Alle Ebenen haben dieselbe Größe; die echte Texturgröße wird für die UV-Berechnung
mitgeführt, damit Skalierung und Verschiebung wie im Spiel aussehen.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from ..core.materials import MaterialLibrary, normalize

LAYER_SIZE = 256
#: GL garantiert mindestens 256 Ebenen; Ebene 0 ist weiß (für Farben ohne Textur)
MAX_LAYERS = 256


@dataclass(frozen=True)
class TextureSlot:
    layer: int
    width: int    # Größe der Originaltextur in Pixeln (für UV)
    height: int


class TextureAtlas:
    def __init__(self, library: MaterialLibrary | None = None) -> None:
        self._lock = threading.Lock()
        self.library = library
        self._slots: dict[str, TextureSlot | None] = {}
        self._layers: list[bytes] = [b"\xff" * (LAYER_SIZE * LAYER_SIZE * 4)]
        #: Steigt, wenn sich die Zuordnung Material → Ebene ändert (Meshes neu bauen)
        self.generation = 0

    def set_library(self, library: MaterialLibrary | None) -> None:
        with self._lock:
            self.library = library
            self._slots.clear()
            self._layers = self._layers[:1]
            self.generation += 1

    @property
    def layer_count(self) -> int:
        return len(self._layers)

    def layer_data(self, index: int) -> bytes:
        return self._layers[index]

    def slot(self, material: str) -> TextureSlot | None:
        """Ebene für ein Material, None wenn es keine Textur gibt (dann zeigt die Ansicht eine Farbe)."""
        key = normalize(material)
        with self._lock:
            if key in self._slots:
                return self._slots[key]
            lib = self.library
        image = lib.texture(key) if lib is not None else None
        with self._lock:
            if key in self._slots:
                return self._slots[key]
            if image is None or len(self._layers) >= MAX_LAYERS:
                self._slots[key] = None
                return None
            self._layers.append(_to_layer(image.rgba, image.width, image.height))
            slot = TextureSlot(len(self._layers) - 1, image.source_width, image.source_height)
            self._slots[key] = slot
            return slot


def _to_layer(rgba: bytes, w: int, h: int) -> bytes:
    if (w, h) == (LAYER_SIZE, LAYER_SIZE):
        return rgba
    from PIL import Image

    img = Image.frombytes("RGBA", (w, h), rgba).resize((LAYER_SIZE, LAYER_SIZE), Image.Resampling.BILINEAR)
    return img.tobytes()
