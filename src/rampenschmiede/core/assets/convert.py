"""Freie Assets in Source-Dateien umwandeln: Texturen zu VTF/VMT, Rundum-Bilder zu Skyboxen.

Texturen landen unter `materials/rampenschmiede/frei/`, Himmel unter `materials/skybox/`, beides
im Ordner der eigenen Texturen; beim Kompilieren werden die benutzten Dateien in die BSP gepackt.
"""
from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
from PIL import Image
from srctools import vtf

from ..materials.authoring import PREFIX, safe_name

FOLDER = "frei"
#: Kantenlänge der Texturen (Source mag Zweierpotenzen; 1024 ist scharf und klein genug)
TEXTURE_SIZE = 1024
SKY_FACE = 1024
#: Reihenfolge und Richtung der Skybox-Bilder wie in der Engine (siehe sky.glsl)
SKY_SUFFIXES = ("rt", "lf", "bk", "ft", "up", "dn")
LICENSE_TEXT = ("Diese Dateien stammen von Poly Haven (https://polyhaven.com) und stehen unter CC0:\n"
                "frei nutzbar, auch kommerziell, ohne Namensnennung. Umgewandelt von der Rampenschmiede.\n")
#: Oberfläche (Schritte, Einschläge) nach Kategorie
SURFACEPROPS = (("brick", "brick"), ("concrete", "concrete"), ("metal", "metal"), ("wood", "wood"),
                ("rock", "rock"), ("stone", "rock"), ("cobble", "rock"), ("sand", "sand"), ("snow", "snow"),
                ("gravel", "gravel"), ("grass", "grass"), ("dirt", "dirt"), ("ground", "dirt"), ("soil", "dirt"),
                ("tile", "tile"), ("asphalt", "concrete"), ("plaster", "plaster"), ("fabric", "carpet"))


def surfaceprop_for(words) -> str:
    low = " ".join(words).lower()
    for word, prop in SURFACEPROPS:
        if word in low:
            return prop
    return ""


def _pow2(n: int, limit: int) -> int:
    p = 4
    while p * 2 <= min(n, limit):
        p *= 2
    return p


def write_vtf(path: Path, image: Image.Image, flags: vtf.VTFFlags = vtf.VTFFlags.EMPTY, mips: bool = True,
              limit: int = TEXTURE_SIZE) -> None:
    img = image.convert("RGBA")
    size = (_pow2(img.width, limit), _pow2(img.height, limit))
    if size != img.size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    has_alpha = img.getextrema()[3][0] < 255
    fmt = vtf.ImageFormats.DXT5 if has_alpha else vtf.ImageFormats.DXT1
    tex = vtf.VTF(*size, (7, 2), fmt=fmt, flags=flags)
    tex.get().copy_from(img.tobytes())
    if mips:
        tex.compute_mipmaps()
    data = io.BytesIO()
    tex.save(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.getvalue())


def _license(folder: Path) -> None:
    f = folder / "LIZENZ.txt"
    if not f.exists():
        f.write_text(LICENSE_TEXT, encoding="utf-8")


def texture_material(root: str | Path, asset_id: str, diffuse: bytes, normal: bytes | None = None,
                     surfaceprop: str = "") -> str:
    """Textur als LightmappedGeneric (mit $bumpmap, wenn ein Normalenbild da ist). Liefert den
    Materialnamen."""
    name = safe_name(asset_id)
    folder = Path(root) / "materials" / PREFIX / FOLDER
    material = f"{PREFIX}/{FOLDER}/{name}"
    write_vtf(folder / f"{name}.vtf", Image.open(io.BytesIO(diffuse)))
    lines = ['"LightmappedGeneric"', "{", f'    "$basetexture" "{material}"']
    if normal is not None:
        write_vtf(folder / f"{name}_normal.vtf", Image.open(io.BytesIO(normal)), vtf.VTFFlags.NORMAL)
        lines.append(f'    "$bumpmap" "{material}_normal"')
    if surfaceprop:
        lines.append(f'    "$surfaceprop" "{surfaceprop}"')
    lines += ['    "%keywords" "rampenschmiede,poly haven,cc0"', "}"]
    (folder / f"{name}.vmt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _license(folder)
    return material


def face_directions(face: int, size: int) -> np.ndarray:
    """Blickrichtung je Pixel (size × size × 3) für ein Skybox-Bild, Umkehrung von sky.glsl."""
    c = (np.arange(size, dtype=np.float64) + 0.5) / size
    u, v = np.meshgrid(c, c)
    sx, sy = 2 * u - 1, 1 - 2 * v
    one = np.ones_like(sx)
    dirs = {
        0: (one, -sx, sy),    # rt: +X
        1: (-one, sx, sy),    # lf: -X
        2: (sx, one, sy),     # bk: +Y
        3: (-sx, -one, sy),   # ft: -Y
        4: (-sy, -sx, one),   # up: +Z
        5: (sy, -sx, -one),   # dn: -Z
    }[face]
    return np.stack(dirs, axis=-1)


def equirect_faces(panorama: Image.Image, size: int = SKY_FACE) -> list[Image.Image]:
    """Rundum-Bild (2:1, Mitte = Blick nach +X) in die sechs Skybox-Bilder zerlegen."""
    pano = np.asarray(panorama.convert("RGB"), dtype=np.uint8)
    h, w = pano.shape[:2]
    out = []
    for face in range(6):
        d = face_directions(face, size)
        lon = np.arctan2(d[..., 1], d[..., 0])
        lat = np.arctan2(d[..., 2], np.hypot(d[..., 0], d[..., 1]))
        # Von innen gesehen: nach rechts im Bild = im Uhrzeigersinn drehen = Winkel kleiner
        x = ((0.5 - lon / (2 * math.pi)) % 1.0) * w
        y = (0.5 - lat / math.pi) * h
        xi = np.clip(x.astype(np.int64), 0, w - 1)
        yi = np.clip(y.astype(np.int64), 0, h - 1)
        out.append(Image.fromarray(pano[yi, xi]))
    return out


def skybox_from_panorama(root: str | Path, asset_id: str, panorama: bytes, size: int = SKY_FACE) -> str:
    """Skybox (6 VTF + VMT unter materials/skybox/) aus einem Rundum-Bild. Liefert den skyname."""
    sky = "rs_" + safe_name(asset_id)
    folder = Path(root) / "materials" / "skybox"
    img = Image.open(io.BytesIO(panorama))
    img.load()
    clamp = vtf.VTFFlags.CLAMP_S | vtf.VTFFlags.CLAMP_T | vtf.VTFFlags.NO_MIP | vtf.VTFFlags.NO_LOD
    for suffix, face in zip(SKY_SUFFIXES, equirect_faces(img, size)):
        write_vtf(folder / f"{sky}{suffix}.vtf", face, clamp, mips=False, limit=size)
        (folder / f"{sky}{suffix}.vmt").write_text(
            '"UnlitGeneric"\n{\n'
            f'    "$basetexture" "skybox/{sky}{suffix}"\n'
            '    "$nofog" "1"\n    "$ignorez" "1"\n'
            '    "%keywords" "rampenschmiede,poly haven,cc0"\n}\n', encoding="utf-8")
    _license(folder)
    return sky


__all__ = ["equirect_faces", "face_directions", "skybox_from_panorama", "surfaceprop_for", "texture_material",
           "write_vtf"]
