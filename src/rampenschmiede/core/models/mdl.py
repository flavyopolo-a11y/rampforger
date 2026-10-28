"""Source-Modelle (MDL mit VVD und VTX) für die Vorschau lesen.

srctools liest nur die Metadaten einer MDL. Für die Vorschau brauchen wir die Dreiecke:
Die VVD enthält die Vertices (Position, Normale, UV), die VTX die Dreiecke je Mesh als
Indizes. Gelesen wird nur die höchste Detailstufe (LOD 0) und je Bodygroup das erste
Modell, also das, was das Spiel ohne besondere Einstellungen zeigt.

Unterstützt werden die MDL-Versionen 44 bis 49 (HL2, CS:S, Momentum). Animationen,
Bones und Flexes werden nicht ausgewertet: Die Vertices liegen in der Grundpose.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

import numpy as np

STATIC_PROP_FLAG = 0x10
MDL_VERSIONS = range(44, 50)
VTX_SUFFIXES = (".dx90.vtx", ".dx80.vtx", ".sw.vtx", ".vtx")
_VERTEX = np.dtype([("weights", "<f4", 3), ("bones", "u1", 3), ("numbones", "u1"),
                    ("pos", "<f4", 3), ("normal", "<f4", 3), ("uv", "<f4", 2)])
assert _VERTEX.itemsize == 48
_VTX_VERT = np.dtype([("weights", "u1", 3), ("numbones", "u1"), ("orig", "<u2"), ("bones", "i1", 3)])
assert _VTX_VERT.itemsize == 9


class ModelError(ValueError):
    """Datei ist keine lesbare MDL/VVD/VTX."""


@dataclass(frozen=True)
class MeshRef:
    """Ein Mesh der MDL: welches Material (Spalte der Skin-Tabelle) und wo seine Vertices liegen."""

    material: int
    vertex_start: int  # Index in die VVD-Vertices (LOD 0)
    vertex_count: int


@dataclass
class StudioHeader:
    name: str
    version: int
    flags: int
    eye: tuple[float, float, float]
    hull_min: tuple[float, float, float]
    hull_max: tuple[float, float, float]
    view_min: tuple[float, float, float]
    view_max: tuple[float, float, float]
    textures: list[str]
    cdmaterials: list[str]
    #: Je Skin die Textur-Indizes je Material-Spalte
    skins: list[list[int]]
    surfaceprop: str
    keyvalues: str
    mass: float
    #: Je Bodygroup die Meshes des ersten Modells
    bodyparts: list[list[MeshRef]] = field(default_factory=list)
    bodygroup_count: int = 0

    @property
    def static_prop(self) -> bool:
        return bool(self.flags & STATIC_PROP_FLAG)


@dataclass
class ModelGeometry:
    """Dreiecke eines Modells im Modell-Koordinatensystem."""

    positions: np.ndarray  # (n, 3) float32
    normals: np.ndarray    # (n, 3) float32
    uvs: np.ndarray        # (n, 2) float32
    triangles: np.ndarray  # (m, 3) int32, Indizes in positions
    tri_material: np.ndarray  # (m,) int32, Material-Spalte der Skin-Tabelle

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)

    def bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
        if not len(self.triangles):
            return None
        used = self.positions[np.unique(self.triangles)]
        lo, hi = used.min(axis=0), used.max(axis=0)
        return (tuple(float(v) for v in lo), tuple(float(v) for v in hi))  # type: ignore[return-value]


#: Kanten zwischen Dreiecken, die stärker als so viel Grad abknicken, zeigen die 2D-Ansichten
CREASE_DEG = 35.0


def feature_edges(geom: ModelGeometry, crease_deg: float = CREASE_DEG) -> np.ndarray:
    """Umriss- und Knickkanten als Linienpaare (2k, 3). Vertices an UV-Nähten werden über
    ihre Position zusammengeführt, sonst sähe jede Naht wie eine offene Kante aus."""
    tris = geom.triangles
    if not len(tris):
        return np.zeros((0, 3), dtype=np.float32)
    pos = geom.positions
    _, ids = np.unique(np.round(pos * 16).astype(np.int64), axis=0, return_inverse=True)
    ids = ids.reshape(-1)
    p0, p1, p2 = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    fn = np.cross(p1 - p0, p2 - p0)
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    a = np.concatenate([tris[:, 0], tris[:, 1], tris[:, 2]])
    b = np.concatenate([tris[:, 1], tris[:, 2], tris[:, 0]])
    owner = np.tile(np.arange(len(tris)), 3)
    ka, kb = ids[a], ids[b]
    keep = ka != kb
    a, b, owner, ka, kb = a[keep], b[keep], owner[keep], ka[keep], kb[keep]
    key = np.minimum(ka, kb) * (int(ids.max()) + 1) + np.maximum(ka, kb)
    order = np.argsort(key, kind="stable")
    key_s = key[order]
    starts = np.flatnonzero(np.r_[True, key_s[1:] != key_s[:-1]])
    counts = np.diff(np.r_[starts, len(key_s)])
    first = order[starts]
    show = counts != 2
    two = counts == 2
    second = order[starts[two] + 1]
    dots = np.einsum("ij,ij->i", fn[owner[first[two]]], fn[owner[second]])
    show[two] = dots < np.cos(np.radians(crease_deg))
    sel = first[show]
    out = np.empty((len(sel) * 2, 3), dtype=np.float32)
    out[0::2] = pos[a[sel]]
    out[1::2] = pos[b[sel]]
    return out


def _cstr(data: bytes, offset: int) -> str:
    if offset <= 0 or offset >= len(data):
        return ""
    end = data.find(b"\0", offset)
    return data[offset:end if end >= 0 else len(data)].decode("latin-1")


def _vec(data: bytes, offset: int) -> tuple[float, float, float]:
    return struct.unpack_from("<3f", data, offset)  # type: ignore[return-value]


def read_header(data: bytes) -> StudioHeader:
    if len(data) < 408 or data[:4] != b"IDST":
        raise ModelError("keine MDL-Datei")
    version = struct.unpack_from("<i", data, 4)[0]
    if version not in MDL_VERSIONS:
        raise ModelError(f"MDL-Version {version} wird nicht unterstützt")
    try:
        return _read_header(data, version)
    except (struct.error, IndexError) as exc:
        raise ModelError(f"MDL beschädigt: {exc}") from exc


def _read_header(data: bytes, version: int) -> StudioHeader:
    name = data[12:76].split(b"\0", 1)[0].decode("latin-1")
    eye = _vec(data, 80)
    hull_min, hull_max = _vec(data, 104), _vec(data, 116)
    view_min, view_max = _vec(data, 128), _vec(data, 140)
    flags = struct.unpack_from("<i", data, 152)[0]
    (tex_count, tex_index, cd_count, cd_index, skinref_count, skin_count, skin_index,
     body_count, body_index) = struct.unpack_from("<9i", data, 204)
    surface_index, kv_index, kv_count = struct.unpack_from("<3i", data, 308)
    mass = struct.unpack_from("<f", data, 328)[0]

    textures = []
    for i in range(max(0, tex_count)):
        base = tex_index + i * 64
        textures.append(_cstr(data, base + struct.unpack_from("<i", data, base)[0]).replace("\\", "/").lstrip("/"))
    cdmaterials = []
    for i in range(max(0, cd_count)):
        cd = _cstr(data, struct.unpack_from("<i", data, cd_index + i * 4)[0]).replace("\\", "/").lstrip("/")
        if cd and not cd.endswith("/"):
            cd += "/"
        cdmaterials.append(cd)
    skins = []
    for s in range(max(0, skin_count)):
        skins.append(list(struct.unpack_from(f"<{skinref_count}H", data, skin_index + s * skinref_count * 2)))
    if not skins:
        skins = [list(range(len(textures)))]

    bodyparts: list[list[MeshRef]] = []
    for b in range(max(0, body_count)):
        base = body_index + b * 16
        _name, model_count, _base, model_index = struct.unpack_from("<4i", data, base)
        if model_count <= 0:
            bodyparts.append([])
            continue
        model = base + model_index  # erstes Modell der Bodygroup
        mesh_count, mesh_index, _nverts, vertex_index = struct.unpack_from("<4i", data, model + 72)
        first = vertex_index // 48
        meshes = []
        for m in range(max(0, mesh_count)):
            mb = model + mesh_index + m * 116
            material, _model_ofs, count, offset = struct.unpack_from("<4i", data, mb)
            meshes.append(MeshRef(material, first + offset, count))
        bodyparts.append(meshes)

    return StudioHeader(
        name=name, version=version, flags=flags, eye=eye,
        hull_min=hull_min, hull_max=hull_max, view_min=view_min, view_max=view_max,
        textures=textures, cdmaterials=cdmaterials, skins=skins,
        surfaceprop=_cstr(data, surface_index),
        keyvalues=_cstr(data, kv_index) if kv_count else "",
        mass=mass, bodyparts=bodyparts, bodygroup_count=max(0, body_count),
    )


def read_vertices(data: bytes) -> np.ndarray:
    """Alle Vertices der höchsten Detailstufe (mit angewendeter Fixup-Tabelle)."""
    if len(data) < 64 or data[:4] != b"IDSV":
        raise ModelError("keine VVD-Datei")
    num_lods = struct.unpack_from("<i", data, 12)[0]
    lod_counts = struct.unpack_from("<8i", data, 16)
    num_fixups, fixup_start, vertex_start = struct.unpack_from("<3i", data, 48)
    total = lod_counts[0] if num_lods > 0 else 0
    if vertex_start + total * 48 > len(data) or total < 0:
        raise ModelError("VVD beschädigt")
    verts = np.frombuffer(data, dtype=_VERTEX, count=total, offset=vertex_start)
    if num_fixups <= 0:
        return verts
    parts = []
    for i in range(num_fixups):
        lod, source, count = struct.unpack_from("<3i", data, fixup_start + i * 12)
        if lod >= 0:  # Fixups gelten für alle Stufen bis einschließlich ihrer eigenen
            parts.append(verts[source:source + count])
    return np.concatenate(parts) if parts else verts[:0]


def _strip_groups(data: bytes, mesh: int, count: int, offset: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """(Vertices, Indizes) aller Strip-Gruppen eines VTX-Meshs. Neuere Compiler schreiben
    8 Bytes mehr je Gruppe; die passende Größe erkennt man daran, dass alles gültig ist."""
    for stride in (25, 33):
        groups = []
        ok = True
        for g in range(count):
            base = mesh + offset + g * stride
            if base + 25 > len(data):
                ok = False
                break
            nverts, vofs, nidx, iofs = struct.unpack_from("<4i", data, base)
            if (nverts < 0 or nidx < 0 or nidx % 3 or base + vofs + nverts * 9 > len(data)
                    or base + iofs + nidx * 2 > len(data)):
                ok = False
                break
            verts = np.frombuffer(data, dtype=_VTX_VERT, count=nverts, offset=base + vofs)
            idx = np.frombuffer(data, dtype="<u2", count=nidx, offset=base + iofs)
            if nidx and int(idx.max()) >= nverts:
                ok = False
                break
            groups.append((verts, idx))
        if ok:
            return groups
    raise ModelError("VTX beschädigt")


def read_triangles(data: bytes, header: StudioHeader) -> tuple[list[np.ndarray], list[int]]:
    """Dreiecke je Mesh als Indizes in die VVD-Vertices, dazu die Material-Spalte je Mesh."""
    if len(data) < 36:
        raise ModelError("keine VTX-Datei")
    version, = struct.unpack_from("<i", data, 0)
    if version != 7:
        raise ModelError(f"VTX-Version {version} wird nicht unterstützt")
    body_count, body_offset = struct.unpack_from("<2i", data, 28)
    tris: list[np.ndarray] = []
    materials: list[int] = []
    try:
        for b in range(min(body_count, len(header.bodyparts))):
            meshes = header.bodyparts[b]
            bp = body_offset + b * 8
            model_count, model_offset = struct.unpack_from("<2i", data, bp)
            if model_count <= 0 or not meshes:
                continue
            model = bp + model_offset
            lod_count, lod_offset = struct.unpack_from("<2i", data, model)
            if lod_count <= 0:
                continue
            lod = model + lod_offset
            mesh_count, mesh_offset = struct.unpack_from("<2i", data, lod)
            for m in range(min(mesh_count, len(meshes))):
                ref = meshes[m]
                mesh = lod + mesh_offset + m * 9
                group_count, group_offset = struct.unpack_from("<2i", data, mesh)
                for verts, idx in _strip_groups(data, mesh, group_count, group_offset):
                    if not len(idx):
                        continue
                    orig = verts["orig"].astype(np.int64)
                    if int(orig.max()) >= ref.vertex_count:
                        raise ModelError("VTX passt nicht zur MDL")
                    tri = (orig[idx.astype(np.int64)] + ref.vertex_start).reshape(-1, 3)
                    tris.append(tri.astype(np.int32))
                    materials.append(ref.material)
    except struct.error as exc:
        raise ModelError(f"VTX beschädigt: {exc}") from exc
    return tris, materials


def build_geometry(header: StudioHeader, vvd: bytes, vtx: bytes) -> ModelGeometry:
    verts = read_vertices(vvd)
    tri_parts, mats = read_triangles(vtx, header)
    if tri_parts:
        triangles = np.concatenate(tri_parts)
        tri_material = np.concatenate([np.full(len(t), m, dtype=np.int32) for t, m in zip(tri_parts, mats)])
    else:
        triangles = np.zeros((0, 3), dtype=np.int32)
        tri_material = np.zeros(0, dtype=np.int32)
    if len(triangles) and int(triangles.max()) >= len(verts):
        raise ModelError("VTX verweist auf fehlende Vertices")
    return ModelGeometry(
        positions=np.ascontiguousarray(verts["pos"], dtype=np.float32),
        normals=np.ascontiguousarray(verts["normal"], dtype=np.float32),
        uvs=np.ascontiguousarray(verts["uv"], dtype=np.float32),
        triangles=triangles,
        tri_material=tri_material,
    )


__all__ = ["CREASE_DEG", "MDL_VERSIONS", "feature_edges", "MeshRef", "ModelError", "ModelGeometry", "STATIC_PROP_FLAG", "StudioHeader",
           "VTX_SUFFIXES", "build_geometry", "read_header", "read_triangles", "read_vertices"]
