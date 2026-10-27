"""Texturgrößen für Bausteine, die eine Textur einpassen.

Der Kern kennt die Material-Bibliothek nicht. Die Oberfläche meldet hier, wie sie
Texturgrößen nachschlägt; ohne Bibliothek gilt 512 × 512 (die Größe der Dev- und der
selbst erzeugten Texturen).
"""
from __future__ import annotations

from typing import Callable

DEFAULT_SIZE = (512, 512)

_lookup: Callable[[str], tuple[int, int] | None] | None = None


def set_size_lookup(fn: Callable[[str], tuple[int, int] | None] | None) -> None:
    global _lookup
    _lookup = fn


def texture_size(material: str) -> tuple[int, int]:
    size = _lookup(material) if _lookup is not None else None
    if not size or size[0] <= 0 or size[1] <= 0:
        return DEFAULT_SIZE
    return size


__all__ = ["DEFAULT_SIZE", "set_size_lookup", "texture_size"]
