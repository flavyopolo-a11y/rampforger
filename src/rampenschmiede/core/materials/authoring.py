"""Eigene Texturen erzeugen: Bilder importieren (PNG, JPG, TGA …) und Farb-Texturen für
den Rampen-Assistenten. Ergebnis sind VTF und VMT in einem Ordner mit dem Aufbau eines
Spielordners (`materials/rampenschmiede/...`). Beim Kompilieren werden sie in die BSP
gepackt, die Map läuft also auch bei anderen ohne Zusatz-Download.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw
from srctools import vmt, vtf

from .library import MaterialLibrary, normalize

PREFIX = "rampenschmiede"
MAX_SIZE = 2048
#: Texturen in VMTs, die mit gepackt werden müssen
TEXTURE_KEYS = ("$basetexture", "$basetexture2", "$bumpmap", "$bumpmap2", "$normalmap", "$detail",
                "$envmapmask", "$blendmodulatetexture", "$selfillummask", "%tooltexture")

_NAME_RE = re.compile(r"[^a-z0-9_]+")

RGB = tuple[int, int, int]


def safe_name(text: str) -> str:
    name = _NAME_RE.sub("_", text.lower()).strip("_")
    return name or "textur"


def _pow2(n: int) -> int:
    p = 1
    while p * 2 <= min(n, MAX_SIZE):
        p *= 2
    return max(p, 4)


def write_texture(root: str | Path, name: str, image: Image.Image, surfaceprop: str = "",
                  params: Iterable[tuple[str, str]] = ()) -> str:
    """Bild als VTF+VMT unter root/materials/rampenschmiede/<name> speichern. Seiten werden
    auf Zweierpotenzen gebracht (Pflicht in Source). Liefert den Materialnamen."""
    name = safe_name(name)
    img = image.convert("RGBA")
    size = (_pow2(img.width), _pow2(img.height))
    if size != img.size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    has_alpha = img.getextrema()[3][0] < 255
    tex = vtf.VTF(*size, (7, 2), fmt=vtf.ImageFormats.DXT5 if has_alpha else vtf.ImageFormats.DXT1)
    tex.get().copy_from(img.tobytes())
    tex.compute_mipmaps()
    folder = Path(root) / "materials" / PREFIX
    folder.mkdir(parents=True, exist_ok=True)
    data = io.BytesIO()
    tex.save(data)
    (folder / f"{name}.vtf").write_bytes(data.getvalue())
    material = f"{PREFIX}/{name}"
    lines = ['"LightmappedGeneric"', "{", f'    "$basetexture" "{material}"']
    if surfaceprop:
        lines.append(f'    "$surfaceprop" "{surfaceprop}"')
    if has_alpha:
        lines.append('    "$alphatest" "1"')
    for key, value in params:
        lines.append(f'    "{key}" "{value}"')
    lines.append('    "%keywords" "rampenschmiede"')
    lines.append("}")
    (folder / f"{name}.vmt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return material


def import_image(root: str | Path, path: str | Path, name: str | None = None) -> str:
    """Bilddatei als eigenes Material übernehmen."""
    with Image.open(path) as img:
        img.load()
        return write_texture(root, name or Path(path).stem, img)


# ---- Farb-Texturen für den Rampen-Assistenten --------------------------------------------

def _hex(c: RGB) -> str:
    return f"{c[0]:02x}{c[1]:02x}{c[2]:02x}"


def _shade(c: RGB, f: float) -> RGB:
    return tuple(max(0, min(255, round(v * f))) for v in c)  # type: ignore[return-value]


def wall_image(color: RGB, size: int = 256) -> Image.Image:
    """Glatte Wand mit feinem Raster, damit Abstände im Spiel lesbar bleiben."""
    img = Image.new("RGB", (size, size), color)
    d = ImageDraw.Draw(img)
    line = _shade(color, 0.86)
    for k in range(0, size, size // 4):
        d.line([(k, 0), (k, size - 1)], fill=line)
        d.line([(0, k), (size - 1, k)], fill=line)
    edge = _shade(color, 0.72)
    d.rectangle([0, 0, size - 1, size - 1], outline=edge)
    return img


def lava_image(size: int = 256, seed: int = 3) -> Image.Image:
    """Lava: glühendes Orange mit dunklen, erkalteten Schollen (kachelbar)."""
    import numpy as np

    rng = np.random.default_rng(seed)
    total = np.zeros((size, size))
    for cells, weight in ((4, 1.0), (8, 0.5), (16, 0.25), (32, 0.12)):
        grid = rng.random((cells, cells))
        # Bilinear und kachelbar hochrechnen
        t = np.arange(size) * cells / size
        i0 = np.floor(t).astype(int) % cells
        i1 = (i0 + 1) % cells
        f = t - np.floor(t)
        f = f * f * (3 - 2 * f)
        rows = grid[i0][:, None, :] * (1 - f)[:, None, None] + grid[i1][:, None, :] * f[:, None, None]
        rows = rows[:, 0, :]
        layer = rows[:, i0] * (1 - f)[None, :] + rows[:, i1] * f[None, :]
        total += weight * layer
    total = (total - total.min()) / (np.ptp(total) or 1.0)
    heat = np.clip((total - 0.35) / 0.4, 0, 1)
    dark = np.array([60, 18, 8], dtype=float)
    hot = np.array([255, 140, 30], dtype=float)
    white = np.array([255, 230, 120], dtype=float)
    rgb = dark + (hot - dark) * heat[..., None]
    rgb += (white - hot) * np.clip((total - 0.8) / 0.2, 0, 1)[..., None]
    return Image.fromarray(np.clip(rgb, 0, 255).astype("uint8"), "RGB")


def lava_material(root: str | Path) -> str:
    """Leuchtende Lava-Textur (selbstleuchtend, kein Licht nötig)."""
    return write_texture(root, "lava", lava_image(), "slime", (("$selfillum", "1"),))


def ramp_image(color: RGB, lines: RGB, size: int = 512) -> Image.Image:
    """Typische Surf-Rampe: Grundfarbe mit Linien quer zur Fahrtrichtung und Kanten."""
    img = Image.new("RGB", (size, size), color)
    d = ImageDraw.Draw(img)
    step = size // 4
    width = max(2, size // 64)
    for k in range(0, size, step):
        d.rectangle([0, k, size - 1, k + width - 1], fill=lines)
    soft = _shade(color, 0.9)
    for k in range(step // 2, size, step):
        d.line([(0, k), (size - 1, k)], fill=soft)
    return img


def wall_material(root: str | Path, color: RGB) -> str:
    return write_texture(root, f"wand_{_hex(color)}", wall_image(color), "concrete")


def ramp_material(root: str | Path, color: RGB, lines: RGB) -> str:
    return write_texture(root, f"rampe_{_hex(color)}_{_hex(lines)}", ramp_image(color, lines), "metal")


# ---- Packen --------------------------------------------------------------------------------

def pack_list(library: MaterialLibrary, materials: Iterable[str]) -> list[tuple[str, str]]:
    """Dateien eigener Materialien zum Packen in die BSP: (Pfad in der BSP, Datei auf der
    Platte). Spiel-Materialien werden nicht gepackt."""
    out: dict[str, str] = {}
    for mat in sorted({normalize(m) for m in materials}):
        if not library.is_own(mat):
            continue
        vmt_file = _own_file(library, f"materials/{mat}.vmt")
        if vmt_file is None:
            continue
        out[f"materials/{mat}.vmt"] = str(vmt_file)
        try:
            parsed = vmt.Material.parse(vmt_file.read_text(encoding="utf-8", errors="replace").splitlines(), str(vmt_file))
        except Exception:  # noqa: BLE001 - kaputte VMT: nur die VMT selbst packen
            continue
        for key in TEXTURE_KEYS:
            tex = parsed.get(key, "")
            if not tex:
                continue
            rel = f"materials/{normalize(tex)}.vtf"
            f = _own_file(library, rel)
            if f is not None:
                out[rel] = str(f)
    return sorted(out.items())


def _own_file(library: MaterialLibrary, rel: str) -> Path | None:
    for folder in reversed(library.own_folders):  # zuletzt eingehängt = höchster Vorrang
        p = Path(folder) / rel
        if p.is_file():
            return p
    return None


def bspzip_list(files: list[tuple[str, str]]) -> str:
    """Inhalt der Liste für `bspzip -addlist`: abwechselnd Pfad in der BSP und auf der Platte."""
    return "".join(f"{inner}\n{outer}\n" for inner, outer in files)


__all__ = [
    "bspzip_list",
    "import_image",
    "pack_list",
    "ramp_image",
    "ramp_material",
    "safe_name",
    "wall_image",
    "wall_material",
    "write_texture",
]
