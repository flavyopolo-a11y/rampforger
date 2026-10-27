"""Kleines Spiel zum Testen: gameinfo.txt, ein VPK mit Materialien und ein loser Ordner."""
import io
from pathlib import Path

from PIL import Image
from srctools import vtf
from srctools.vpk import VPK

GAMEINFO = '''"GameInfo"
{
    game "Testspiel"
    FileSystem
    {
        SteamAppId 240
        SearchPaths
        {
            game |gameinfo_path|.
        }
    }
}
'''


def vtf_bytes(color, size=(64, 32)) -> bytes:
    tex = vtf.VTF(*size, (7, 2), fmt=vtf.ImageFormats.DXT1)
    tex.get().copy_from(Image.new("RGBA", size, color).tobytes())
    tex.compute_mipmaps()
    out = io.BytesIO()
    tex.save(out)
    return out.getvalue()


def vmt_text(base: str, shader: str = "LightmappedGeneric", extra: str = "") -> str:
    return f'"{shader}"\n{{\n    "$basetexture" "{base}"\n{extra}}}\n'


def make_game(root: Path) -> Path:
    """Spielordner mit VPK (rot, grün, ein Patch-Material) und losem Ordner (blau)."""
    game = root / "spiel"
    game.mkdir(parents=True)
    (game / "gameinfo.txt").write_text(GAMEINFO, encoding="utf-8")
    pak = VPK(game / "pak01_dir.vpk", mode="w")
    pak.add_file("materials/test/rot.vmt", vmt_text("test/rot", extra='    "%keywords" "surf,rot"\n').encode())
    pak.add_file("materials/test/rot.vtf", vtf_bytes((255, 0, 0, 255)))
    pak.add_file("materials/test/gruen.vmt", vmt_text("test/gruen", extra='    "$alphatest" "1"\n').encode())
    pak.add_file("materials/test/gruen.vtf", vtf_bytes((0, 255, 0, 255), (512, 512)))
    pak.add_file("materials/test/flicken.vmt",
                 b'"patch"\n{\n    "include" "materials/test/rot.vmt"\n    "insert" { "$surfaceprop" "metal" }\n}\n')
    pak.write_dirfile()
    loose = game / "materials" / "lose"
    loose.mkdir(parents=True)
    (loose / "blau.vmt").write_text(vmt_text("lose/blau"), encoding="utf-8")
    (loose / "blau.vtf").write_bytes(vtf_bytes((0, 0, 255, 255)))
    return game
