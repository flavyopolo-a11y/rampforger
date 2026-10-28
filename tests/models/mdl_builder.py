"""Kleine Source-Modelle (MDL, VVD, VTX) für Tests bauen: ein Würfel mit zwei Materialien.

Die Strukturen folgen studio.h und optimize.h des Source SDK (MDL-Version 48, VTX-Version 7).
"""
from __future__ import annotations

import struct
from pathlib import Path

#: Die sechs Würfelseiten: Normale und vier Ecken (gegen den Uhrzeigersinn von außen)
_FACES = [
    ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
    ((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
    ((0, 1, 0), [(1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)]),
    ((0, 0, -1), [(0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0)]),
    ((-1, 0, 0), [(0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)]),
    ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
]


class _Blob:
    def __init__(self, size: int = 0) -> None:
        self.data = bytearray(size)

    def put(self, raw: bytes) -> int:
        at = len(self.data)
        self.data += raw
        return at

    def string(self, text: str) -> int:
        return self.put(text.encode("latin-1") + b"\0")

    def set(self, at: int, fmt: str, *values) -> None:
        struct.pack_into(fmt, self.data, at, *values)


def cube_vertices(size: tuple[float, float, float], lo: tuple[float, float, float]):
    """24 Vertices (je Seite vier) als (Position, Normale, UV)."""
    out = []
    for normal, corners in _FACES:
        for k, c in enumerate(corners):
            pos = tuple(lo[i] + c[i] * size[i] for i in range(3))
            uv = ((0, 0), (1, 0), (1, 1), (0, 1))[k]
            out.append((pos, normal, uv))
    return out


def build_mdl(name: str, textures: list[str], cdmaterials: list[str], skins: list[list[int]],
              static: bool = True, surfaceprop: str = "metal", keyvalues: str = "",
              hull=((-16, -16, 0), (16, 16, 32)), bodyparts=((0, 12), (12, 12))) -> bytes:
    """Eine Bodygroup, ein Modell, ein Mesh je Eintrag in `bodyparts` ((Vertex-Offset, Anzahl) je Mesh,
    Material = Position in der Liste)."""
    blob = _Blob(408)
    # Texturen
    tex_index = len(blob.data)
    for _ in textures:
        blob.put(b"\0" * 64)
    for i, t in enumerate(textures):
        at = blob.string(t)
        blob.set(tex_index + i * 64, "<i", at - (tex_index + i * 64))
    # $cdmaterials: Offsets ab Dateianfang
    cd_index = blob.put(b"\0" * (4 * len(cdmaterials)))
    for i, cd in enumerate(cdmaterials):
        blob.set(cd_index + i * 4, "<i", blob.string(cd))
    # Skin-Tabelle
    skinref_count = len(skins[0]) if skins else 0
    skin_index = blob.put(b"".join(struct.pack(f"<{skinref_count}H", *row) for row in skins))
    # Bodygroup → Modell → Meshes
    body_index = blob.put(b"\0" * 16)
    body_name = blob.string("body")
    model_at = blob.put(b"\0" * 148)
    mesh_at = blob.put(b"\0" * (116 * len(bodyparts)))
    blob.set(body_index, "<4i", body_name - body_index, 1, 1, model_at - body_index)
    total = sum(n for _, n in bodyparts)
    blob.set(model_at, "<64s", b"cube")
    blob.set(model_at + 64, "<if", 0, 32.0)
    blob.set(model_at + 72, "<4i", len(bodyparts), mesh_at - model_at, total, 0)
    for m, (offset, count) in enumerate(bodyparts):
        blob.set(mesh_at + m * 116, "<4i", m, model_at - (mesh_at + m * 116), count, offset)
    surf_at = blob.string(surfaceprop)
    kv_at = blob.string(keyvalues) if keyvalues else 0

    # Kopf
    blob.set(0, "<4si4s64si", b"IDST", 48, b"\x01\x02\x03\x04", name.encode()[:63], 0)
    blob.set(80, "<3f3f", 0, 0, 16, 0, 0, 16)
    blob.set(104, "<3f3f3f3f", *hull[0], *hull[1], *hull[0], *hull[1])
    blob.set(152, "<i", 0x10 if static else 0)
    blob.set(204, "<9i", len(textures), tex_index, len(cdmaterials), cd_index, skinref_count, len(skins),
             skin_index, 1, body_index)
    blob.set(308, "<3i", surf_at, kv_at, 1 if keyvalues else 0)
    blob.set(328, "<f", 10.0)
    blob.set(76, "<i", len(blob.data))
    return bytes(blob.data)


def build_vvd(vertices, fixups: list[tuple[int, int, int]] | None = None, order: list[int] | None = None) -> bytes:
    """`order`: Reihenfolge, in der die Vertices in der Datei stehen (für Fixup-Tests)."""
    order = order or list(range(len(vertices)))
    raw = b"".join(struct.pack("<3f3BB3f3f2f", 1, 0, 0, 0, 0, 0, 1, *vertices[i][0], *vertices[i][1],
                               *vertices[i][2]) for i in order)
    fixups = fixups or []
    fix_raw = b"".join(struct.pack("<3i", *f) for f in fixups)
    fixup_start = 64
    vertex_start = 64 + len(fix_raw)
    header = struct.pack("<4s3i8i4i", b"IDSV", 4, 0, 1, len(vertices), *([0] * 7), len(fixups), fixup_start,
                         vertex_start, 0)
    return header + fix_raw + raw


def build_vtx(meshes: list[list[int]], wide_groups: bool = False, groups_per_mesh: int = 1) -> bytes:
    """`meshes`: je Mesh die Dreiecks-Indizes in seine eigenen Vertices (0 … n-1). Mit
    `groups_per_mesh` > 1 werden die Dreiecke auf mehrere Strip-Gruppen verteilt."""
    group_size = 33 if wide_groups else 25
    blob = _Blob(36)
    body = blob.put(b"\0" * 8)
    model = blob.put(b"\0" * 8)
    lod = blob.put(b"\0" * 12)
    mesh_at = blob.put(b"\0" * (9 * len(meshes)))
    blob.set(0, "<2i2Hi3i2i", 7, 24, 53, 9, 3, 0, 1, 0, 1, body)
    blob.set(body, "<2i", 1, model - body)
    blob.set(model, "<2i", 1, lod - model)
    blob.set(lod, "<2if", len(meshes), mesh_at - lod, 0.0)
    for m, indices in enumerate(meshes):
        mesh = mesh_at + m * 9
        tris = [indices[i:i + 3] for i in range(0, len(indices), 3)]
        per = -(-len(tris) // groups_per_mesh)
        chunks = [tris[i:i + per] for i in range(0, len(tris), per)]
        groups = blob.put(b"\0" * (group_size * len(chunks)))
        blob.set(mesh, "<2iB", len(chunks), groups - mesh, 0)
        for g, chunk in enumerate(chunks):
            base = groups + g * group_size
            used = sorted({i for t in chunk for i in t})
            local = {v: k for k, v in enumerate(used)}
            verts = blob.put(b"".join(struct.pack("<3BBH3b", 0, 0, 0, 1, v, 0, 0, 0) for v in used))
            idx = blob.put(b"".join(struct.pack("<H", local[i]) for t in chunk for i in t))
            strip = blob.put(struct.pack("<4ihBii", len(chunk) * 3, 0, len(used), 0, 1, 1, 0, 0))
            blob.set(base, "<6iB", len(used), verts - base, len(chunk) * 3, idx - base, 1, strip - base, 0)
    return bytes(blob.data)


def cube_indices(face_count: int) -> list[int]:
    out = []
    for f in range(face_count):
        b = f * 4
        out += [b, b + 1, b + 2, b, b + 2, b + 3]
    return out


def write_cube_model(root: Path, name: str = "models/test/crate.mdl", static: bool = True, physics: bool = True,
                     size=(32, 32, 32), lo=(-16, -16, 0), textures=("crate_top", "crate_side"),
                     cdmaterials=("models/test/",), skins=((0, 1), (1, 0)), fixups: bool = False,
                     wide_groups: bool = False, groups_per_mesh: int = 1, keyvalues: str = "") -> Path:
    """Würfel-Modell unter `root/<name>` schreiben: oben drei Seiten Material 0, unten drei Material 1."""
    verts = cube_vertices(size, lo)
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_mdl(name, list(textures), list(cdmaterials), [list(s) for s in skins], static=static,
                               keyvalues=keyvalues))
    if fixups:
        # In der Datei steht die zweite Hälfte zuerst; die Fixups stellen die Reihenfolge wieder her
        order = list(range(12, 24)) + list(range(12))
        vvd = build_vvd(verts, fixups=[(0, 12, 12), (0, 0, 12)], order=order)
    else:
        vvd = build_vvd(verts)
    path.with_suffix(".vvd").write_bytes(vvd)
    vtx = build_vtx([cube_indices(3), cube_indices(3)], wide_groups=wide_groups, groups_per_mesh=groups_per_mesh)
    path.with_suffix("").with_suffix(".dx90.vtx").write_bytes(vtx)
    if physics:
        path.with_suffix(".phy").write_bytes(struct.pack("<4i", 16, 0, 0, 0) + b'solid {}\0')
    return path


def write_material(root: Path, name: str, color=(200, 80, 40), alpha: int = 255, extra: str = "") -> None:
    """VMT mit kleiner VTF in einer Farbe. `extra`: weitere VMT-Zeilen, z. B. '"$alphatest" "1"'."""
    from srctools.vtf import VTF, ImageFormats

    base = root / "materials" / name
    base.parent.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".vmt").write_text(f'"VertexLitGeneric"\n{{\n"$basetexture" "{name}"\n{extra}\n}}\n')
    tex = VTF(16, 16, fmt=ImageFormats.RGBA8888)
    tex.get().copy_from(bytes((*color, alpha)) * 256, ImageFormats.RGBA8888)
    with base.with_suffix(".vtf").open("wb") as f:
        tex.save(f)
