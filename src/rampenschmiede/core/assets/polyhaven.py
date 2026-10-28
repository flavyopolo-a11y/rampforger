"""Poly Haven: freie Texturen und Himmel (alles CC0, also ohne Bedingungen nutzbar).

Die öffentliche API (api.polyhaven.com) liefert Listen, Kategorien und Download-Adressen.
Bedingungen der API: ein eigener User-Agent je Programm und ein sichtbarer Hinweis, dass die
Assets von Poly Haven kommen (steht im Dialog und in LIZENZ.txt neben den Dateien).
Downloads landen in einem Zwischenspeicher, damit nichts doppelt geladen wird.
"""
from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ... import __version__

API = "https://api.polyhaven.com"
SITE = "https://polyhaven.com/a/"
USER_AGENT = f"Rampenschmiede/{__version__} (Surf-Map-Editor; https://github.com/flavyopolo-a11y/rampforger)"
ATTRIBUTION = "Assets von Poly Haven (polyhaven.com), Lizenz CC0"
TIMEOUT = 30
#: Asset-Arten der API und wie der Editor sie nennt
KINDS = {"textures": "Texturen", "hdris": "Himmel"}
#: Welche Bilder einer Textur genommen werden (erste vorhandene gewinnt)
DIFFUSE_KEYS = ("diffuse", "diff", "albedo", "color", "col")
#: Source erwartet Normalen im DirectX-Format (Grün nach unten)
NORMAL_KEYS = ("nor_dx", "normal_dx", "nor", "normal")
RESOLUTIONS = ("1k", "2k", "4k")

#: Zum Testen austauschbar: (URL) -> Bytes
Fetch = Callable[[str], bytes]


@dataclass(frozen=True)
class Asset:
    id: str
    name: str
    kind: str
    categories: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    thumbnail: str = ""
    authors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def page(self) -> str:
        return SITE + self.id

    def matches(self, text: str) -> bool:
        words = text.lower().split()
        hay = " ".join((self.id, self.name, *self.categories, *self.tags)).lower()
        return all(w in hay for w in words)


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - feste https-Adressen
        return resp.read()


class PolyHaven:
    """Zugriff auf die API mit Zwischenspeicher auf der Platte."""

    def __init__(self, cache_dir: str | Path, fetch: Fetch = http_get) -> None:
        self.cache = Path(cache_dir)
        self.fetch = fetch

    def _json(self, path: str, params: dict[str, str] | None = None) -> object:
        url = f"{API}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return json.loads(self.fetch(url).decode("utf-8"))

    def assets(self, kind: str, category: str = "") -> list[Asset]:
        params = {"type": kind}
        if category:
            params["categories"] = category
        data = self._json("assets", params)
        out = []
        if isinstance(data, dict):
            for aid, info in data.items():
                if not isinstance(info, dict):
                    continue
                out.append(Asset(aid, str(info.get("name", aid)), kind, tuple(info.get("categories", ()) or ()),
                                 tuple(info.get("tags", ()) or ()), str(info.get("thumbnail_url", "")),
                                 tuple((info.get("authors") or {}).keys())))
        out.sort(key=lambda a: a.name.lower())
        return out

    def categories(self, kind: str) -> list[str]:
        """Kategorien, die meistbenutzten zuerst."""
        data = self._json(f"categories/{kind}")
        if not isinstance(data, dict):
            return []
        return [c for c, _n in sorted(data.items(), key=lambda kv: -int(kv[1] or 0)) if c != "all"]

    def files(self, asset_id: str) -> dict:
        data = self._json(f"files/{urllib.parse.quote(asset_id)}")
        return data if isinstance(data, dict) else {}

    def download(self, url: str) -> bytes:
        """Datei laden, aus dem Zwischenspeicher, wenn schon einmal geladen."""
        name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + Path(urllib.parse.urlparse(url).path).suffix
        path = self.cache / name
        if path.is_file():
            return path.read_bytes()
        data = self.fetch(url)
        self.cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return data


def _file_url(entry: object, formats: tuple[str, ...]) -> str | None:
    """Aus {Auflösung: {Format: {url}}} die kleinste passende Auflösung nehmen."""
    if not isinstance(entry, dict):
        return None
    for res in RESOLUTIONS:
        by_format = entry.get(res)
        if not isinstance(by_format, dict):
            continue
        for fmt in formats:
            f = by_format.get(fmt)
            if isinstance(f, dict) and f.get("url"):
                return str(f["url"])
    return None


def texture_urls(files: dict) -> tuple[str | None, str | None]:
    """(Farbbild, Normalenbild) einer Textur, je als JPG/PNG in 1k (sonst größer)."""
    lower = {k.lower(): v for k, v in files.items()}
    diffuse = next((_file_url(lower[k], ("jpg", "png")) for k in DIFFUSE_KEYS if k in lower), None)
    normal = next((_file_url(lower[k], ("jpg", "png")) for k in NORMAL_KEYS if k in lower), None)
    return diffuse, normal


def sky_url(files: dict) -> str | None:
    """Rundum-Bild eines Himmels als normales Bild (tonemapped JPG), sonst None."""
    tone = files.get("tonemapped")
    if isinstance(tone, dict) and tone.get("url"):
        return str(tone["url"])
    return None


__all__ = ["ATTRIBUTION", "Asset", "KINDS", "PolyHaven", "USER_AGENT", "http_get", "sky_url", "texture_urls"]
