"""Kleine BSP-Dateien für Tests bauen (ohne vbsp): Welt-Würfel, Detail-Rampe, Trigger."""
from __future__ import annotations

import struct
from pathlib import Path
from weakref import WeakKeyDictionary

from srctools.bsp import (
    BSP,
    BModel,
    Brush,
    BrushContents,
    BrushSide,
    Plane,
    VisLeaf,
    VisLeafFlags,
    VisTree,
)
from srctools.math import Vec
from srctools.vmf import VMF, Output


def _empty_file(path: Path) -> None:
    # Alle Lumps leer, nur der Game-Lump (35) braucht seine Anzahl 0
    data_at = 8 + 64 * 16 + 4
    lumps = [(data_at, 4) if i == 35 else (0, 0) for i in range(64)]
    header = b"VBSP" + struct.pack("<i", 20) + b"".join(struct.pack("<iii4s", o, n, 0, b"\0" * 4) for o, n in lumps)
    path.write_bytes(header + struct.pack("<i", 1) + struct.pack("<i", 0))


def _box_sides(bsp: BSP, lo, hi, mat: str, bevel: bool = False) -> list[BrushSide]:
    tex = bsp.create_texinfo(mat, Vec(0.25, 0, 0), 0, Vec(0, -0.25, 0), 0, Vec(1 / 16, 0, 0), 0,
                             Vec(0, -1 / 16, 0), 0, reflectivity=Vec(0.5, 0.5, 0.5), width=512, height=512)
    sides = []
    for axis in range(3):
        n = [0.0, 0.0, 0.0]
        n[axis] = 1.0
        sides.append(BrushSide(Plane(Vec(*n), hi[axis]), tex, -1, False))
        n[axis] = -1.0
        sides.append(BrushSide(Plane(Vec(*n), -lo[axis]), tex, -1, False))
    if bevel:
        sides.append(BrushSide(Plane(Vec(1, 1, 0).norm(), 9999), tex, -1, True))
    return sides


def _ramp_sides(bsp: BSP, mat: str) -> list[BrushSide]:
    """Dreiecks-Rampe: Boden z=0, x von 0 bis 512, Spitze bei x=256, z=256, y von 0 bis 1024."""
    tex = bsp.create_texinfo(mat, Vec(0, 0.25, 0), 16, Vec(0, 0, -0.25), 0, Vec(0, 1 / 16, 0), 0,
                             Vec(0, 0, -1 / 16), 0, reflectivity=Vec(0.5, 0.5, 0.5), width=512, height=512)
    s = 2 ** -0.5
    return [
        BrushSide(Plane(Vec(0, 0, -1), 0), tex, -1, False),
        BrushSide(Plane(Vec(-s, 0, s), 0), tex, -1, False),
        BrushSide(Plane(Vec(s, 0, s), 512 * s), tex, -1, False),
        BrushSide(Plane(Vec(0, -1, 0), 0), tex, -1, False),
        BrushSide(Plane(Vec(0, 1, 0), 1024), tex, -1, False),
    ]


def _tree(brushes: list[Brush]) -> VisTree:
    leaf = VisLeaf(BrushContents.SOLID, 0, 0, VisLeafFlags(0), Vec(-4096, -4096, -4096), Vec(4096, 4096, 4096),
                   [], brushes, -1)
    empty = VisLeaf(BrushContents.EMPTY, -1, 0, VisLeafFlags(0), Vec(), Vec(), [], [], -1)
    return VisTree(Plane(Vec(0, 0, 1), 0), Vec(-4096, -4096, -4096), Vec(4096, 4096, 4096), [], 0, leaf, empty)


def build_bsp(path: Path) -> Path:
    _empty_file(path)
    bsp = BSP(path)
    vmf = VMF()
    vmf.spawn["skyname"] = "sky_day01_05"
    trigger = vmf.create_ent("trigger_teleport", target="dest", spawnflags="1", origin="0 0 0")
    trigger.add_out(Output("OnStartTouch", "!activator", "AddOutput", "gravity 1", 0.5, times=1))
    vmf.create_ent("info_teleport_destination", targetname="dest", origin="128 64 32", angles="0 90 0")
    vmf.create_ent("info_player_counterterrorist", origin="0 0 16", angles="0 0 0")
    vmf.create_ent("light", origin="0 0 200", _light="255 255 255 200")
    bsp.ents = vmf

    world = Brush(BrushContents.SOLID, _box_sides(bsp, (-512, -512, -64), (512, 512, 0), "DEV/DEV_MEASUREGENERIC01",
                                                  bevel=True))
    clip = Brush(BrushContents.PLAYER_CLIP, _box_sides(bsp, (0, 0, 0), (64, 64, 64), "TOOLS/TOOLSPLAYERCLIP"))
    ramp = Brush(BrushContents.SOLID | BrushContents.DETAIL, _ramp_sides(bsp, "DEV/DEV_MEASUREGENERIC01B"))
    trig = Brush(BrushContents.EMPTY, _box_sides(bsp, (100, 100, 0), (200, 200, 100), "TOOLS/TOOLSTRIGGER"))
    bsp.brushes = [world, clip, ramp, trig]
    models: WeakKeyDictionary = WeakKeyDictionary()
    models[vmf.spawn] = BModel(Vec(-512, -512, -64), Vec(512, 1024, 256), Vec(), _tree([world, clip, ramp]), [])
    models[trigger] = BModel(Vec(100, 100, 0), Vec(200, 200, 100), Vec(), _tree([trig]), [])
    bsp.bmodels = models
    bsp.save()
    return path
