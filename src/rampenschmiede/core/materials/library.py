"""Materialien aus dem Spiel lesen: Dateisystem aus VPKs und Ordnern, VMT und VTF.

Die Suchpfade kommen aus der gameinfo.txt des Spielprofils (über srctools, auch für
Strata/Momentum). Eigene Ordner (z. B. die Texturen eines Projekts) kommen davor, damit
sie Spiel-Materialien überdecken können.

Namen werden wie in VMF ohne `materials/` und ohne `.vmt` geführt, Groß- und
Kleinschreibung spielt wie in Source keine Rolle.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from srctools import vmt, vtf
from srctools.filesys import FileSystemChain, RawFileSystem, VPKFileSystem
from srctools.game import Game
from srctools.tokenizer import TokenSyntaxError

#: Größte Kantenlänge für Vorschauen und die Textur in der 3D-Ansicht
PREVIEW_SIZE = 256
TRANSLUCENT_KEYS = ("$translucent", "$alphatest", "%compiletrigger")


def normalize(name: str) -> str:
    """'materials/Dev/Foo.vmt' → 'dev/foo'."""
    n = name.replace("\\", "/").strip().strip("/").lower()
    if n.startswith("materials/"):
        n = n[len("materials/"):]
    if n.endswith(".vmt"):
        n = n[:-4]
    return n


@dataclass(frozen=True)
class MaterialInfo:
    name: str
    shader: str
    basetexture: str | None
    #: Textur, die der Editor statt $basetexture zeigt (%tooltexture)
    tooltexture: str | None
    translucent: bool
    keywords: tuple[str, ...]
    surfaceprop: str
    #: Durchsichtige Pixel: "alphatest" (hart ausgeschnitten), "translucent" (halb durchsichtig) oder ""
    transparency: str = ""
    #: Zweite Textur von Überblend-Materialien (WorldVertexTransition, Displacements)
    basetexture2: str | None = None

    @property
    def preview_texture(self) -> str | None:
        return self.tooltexture or self.basetexture


@dataclass(frozen=True)
class TextureImage:
    """Verkleinertes RGBA-Bild einer Textur und die Größe der Originaltextur in Pixeln."""

    width: int
    height: int
    rgba: bytes
    source_width: int
    source_height: int


@dataclass
class MaterialLibrary:
    fsys: FileSystemChain = field(default_factory=FileSystemChain)
    _names: list[str] | None = None
    _infos: dict[str, MaterialInfo | None] = field(default_factory=dict)
    _images: dict[str | tuple, TextureImage | None] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    own_folders: list[str] = field(default_factory=list)
    _own: list[str] | None = None

    @classmethod
    def for_game(cls, game_dir: str | Path | None, extra_dirs: Iterable[str | Path] = ()) -> "MaterialLibrary":
        """Bibliothek für ein Spiel. Fehlt der Spielordner, gibt es nur die eigenen Ordner."""
        fsys = FileSystemChain()
        if game_dir and (Path(game_dir) / "gameinfo.txt").is_file():
            try:
                fsys = Game(game_dir).get_filesystem()
            except (OSError, ValueError, KeyError):
                # z. B. Steam nicht gefunden: wenigstens den Spielordner selbst nutzen
                fsys = _plain_filesystem(Path(game_dir))
        lib = cls(fsys)
        for d in extra_dirs:
            lib.add_folder(d)
        return lib

    def add_folder(self, folder: str | Path) -> None:
        """Ordner, der `materials/...` enthält, mit Vorrang vor dem Spiel einhängen."""
        if Path(folder).is_dir():
            with self._lock:
                self.fsys.add_sys(RawFileSystem(str(folder)), priority=True)
                self.own_folders.append(str(folder))
                self.forget()

    def forget(self) -> None:
        with self._lock:
            self._names = None
            self._own = None
            self._infos.clear()
            self._images.clear()

    # ---- Index -------------------------------------------------------------------------
    def names(self) -> list[str]:
        """Alle Materialnamen, sortiert. Beim ersten Aufruf werden alle VPKs durchsucht."""
        with self._lock:
            if self._names is None:
                found: set[str] = set()
                for f in self.fsys.walk_folder("materials"):
                    if f.path.lower().endswith(".vmt"):
                        found.add(normalize(f.path))
                self._names = sorted(found)
            return self._names

    def exists(self, name: str) -> bool:
        return self._file(f"materials/{normalize(name)}.vmt") is not None

    def _file(self, path: str):
        try:
            return self.fsys[path]
        except (FileNotFoundError, KeyError):
            return None

    # ---- Material und Textur ---------------------------------------------------------------
    def material(self, name: str) -> MaterialInfo | None:
        key = normalize(name)
        with self._lock:
            if key in self._infos:
                return self._infos[key]
            info = self._read_material(key)
            self._infos[key] = info
            return info

    def _read_material(self, key: str) -> MaterialInfo | None:
        f = self._file(f"materials/{key}.vmt")
        if f is None:
            return None
        try:
            with f.open_str() as stream:
                mat = vmt.Material.parse(stream, f.path)
            mat = mat.apply_patches(self.fsys)
        except (OSError, ValueError, KeyError, UnicodeDecodeError, TokenSyntaxError):
            return None

        def tex(key_name: str) -> str | None:
            value = mat.get(key_name, "")
            return normalize(value) if value else None

        translucent = any(mat.get(k, "0") not in ("0", "") for k in TRANSLUCENT_KEYS)
        keywords = tuple(k.strip() for k in mat.get("%keywords", "").split(",") if k.strip())
        transparency = ("alphatest" if mat.get("$alphatest", "0") not in ("0", "") else
                        "translucent" if mat.get("$translucent", "0") not in ("0", "") else "")
        return MaterialInfo(key, mat.shader.lower(), tex("$basetexture"), tex("%tooltexture"),
                            translucent, keywords, mat.get("$surfaceprop", ""), transparency,
                            tex("$basetexture2"))

    def texture(self, name: str) -> TextureImage | None:
        """Vorschaubild für ein Material (aus %tooltexture oder $basetexture). Threadsicher:
        Vorschauen dürfen im Hintergrund geladen werden."""
        key = normalize(name)
        with self._lock:
            if key in self._images:
                return self._images[key]
            info = self.material(key)
            image = self._read_texture(info.preview_texture) if info and info.preview_texture else None
            self._images[key] = image
            return image

    def texture2(self, name: str) -> TextureImage | None:
        """Zweite Textur eines Überblend-Materials ($basetexture2), None bei normalen Materialien."""
        key = normalize(name)
        with self._lock:
            if (key, 2) in self._images:
                return self._images[(key, 2)]
            info = self.material(key)
            image = self._read_texture(info.basetexture2) if info and info.basetexture2 else None
            self._images[(key, 2)] = image
            return image

    def own_names(self) -> list[str]:
        """Materialien aus den eigenen Ordnern (Texturpakete, importierte Texturen)."""
        with self._lock:
            if self._own is None:
                found: set[str] = set()
                for folder in self.own_folders:
                    base = Path(folder) / "materials"
                    if base.is_dir():
                        found |= {normalize(str(p.relative_to(folder))) for p in base.rglob("*.vmt")}
                self._own = sorted(found)
            return self._own

    def is_own(self, name: str) -> bool:
        """Liegt das Material in einem eigenen Ordner (muss also in die BSP gepackt werden)?"""
        return normalize(name) in set(self.own_names())

    def _read_texture(self, tex_name: str) -> TextureImage | None:
        f = self._file(f"materials/{tex_name}.vtf")
        if f is None:
            return None
        try:
            with f.open_bin() as stream:
                tex = vtf.VTF.read(stream)
                level = 0
                while (max(tex.width, tex.height) >> level) > PREVIEW_SIZE and level + 1 < tex.mipmap_count:
                    level += 1
                frame = tex.get(mipmap=level)
                frame.load()
                rgba = bytes(frame.to_PIL().convert("RGBA").tobytes())
                w, h = frame.width, frame.height
        except (OSError, ValueError, EOFError, IndexError, NotImplementedError):
            return None
        if max(w, h) > PREVIEW_SIZE:
            rgba, w, h = _shrink(rgba, w, h)
        return TextureImage(w, h, rgba, tex.width, tex.height)


def _plain_filesystem(game_dir: Path) -> FileSystemChain:
    fsys = FileSystemChain()
    for vpk in sorted(game_dir.glob("pak*_dir.vpk")):
        fsys.add_sys(VPKFileSystem(str(vpk)))
    fsys.add_sys(RawFileSystem(str(game_dir)))
    return fsys


def _shrink(rgba: bytes, w: int, h: int) -> tuple[bytes, int, int]:
    from PIL import Image

    scale = PREVIEW_SIZE / max(w, h)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    img = Image.frombytes("RGBA", (w, h), rgba).resize((nw, nh), Image.Resampling.BILINEAR)
    return img.tobytes(), nw, nh


__all__ = ["MaterialInfo", "MaterialLibrary", "PREVIEW_SIZE", "TextureImage", "normalize"]
