"""Sounds des Spiels (aus den VPKs und Ordnern wie die Materialien): Liste für den Sound-Browser
und Auspacken einer Datei zum Abspielen. Namen wie in Source ohne `sound/`, z. B.
`ambient/wind/wind1.wav`."""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from .materials.library import MaterialLibrary

SUFFIXES = (".wav", ".mp3", ".ogg")


def normalize(name: str) -> str:
    n = name.replace("\\", "/").strip().lstrip("/")
    if n.lower().startswith("sound/"):
        n = n[6:]
    # Sound-Zeichen am Anfang (z. B. `)` für Raumklang, `*` für Streaming) gehören nicht zum Pfad
    return n.lstrip("*#@><^)}$!?&~`+%").lower()


class SoundLibrary:
    def __init__(self, materials: MaterialLibrary | None) -> None:
        self.materials = materials
        self._names: list[str] | None = None
        self._lock = threading.Lock()

    def names(self) -> list[str]:
        """Alle Sound-Dateien, sortiert (beim ersten Aufruf werden die VPKs durchsucht)."""
        with self._lock:
            if self._names is None:
                found: set[str] = set()
                if self.materials is not None:
                    for f in self.materials.fsys.walk_folder("sound"):
                        if f.path.lower().endswith(SUFFIXES):
                            found.add(normalize(f.path))
                self._names = sorted(found)
            return self._names

    def read(self, name: str) -> bytes | None:
        if self.materials is None:
            return None
        try:
            f = self.materials.fsys[f"sound/{normalize(name)}"]
        except (FileNotFoundError, KeyError):
            return None
        with f.open_bin() as fh:
            return fh.read()

    def extract(self, name: str, cache_dir: Path) -> Path | None:
        """Datei zum Abspielen auspacken (einmal je Inhalt)."""
        data = self.read(name)
        if data is None:
            return None
        suffix = Path(normalize(name)).suffix or ".wav"
        out = cache_dir / f"{hashlib.sha1(data).hexdigest()[:16]}{suffix}"
        if not out.is_file():
            cache_dir.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
        return out


__all__ = ["SUFFIXES", "SoundLibrary", "normalize"]
