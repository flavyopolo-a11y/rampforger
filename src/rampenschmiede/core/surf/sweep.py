"""Rampen als Querschnitt, der entlang eines Weges gezogen wird.

Ein Querschnitt (Profil) ist eine Liste konvexer Polygone in (quer, hoch). Der Weg ist
eine Folge von Gelenken: Position, Gierwinkel und optional ein eigener Querschnitt
(für Rampen, deren Form sich entlang der Länge ändert). An jedem Gelenk wird der
Querschnitt auf ganze Units gerundet; jedes Segment ist die konvexe Hülle aus zwei
aufeinanderfolgenden Querschnitten. Weil beide Nachbarsegmente dieselben gerundeten
Punkte benutzen, passen die Nähte exakt aufeinander.

Surf-Flächen bekommen auf Wunsch eine eingepasste Textur: quer zur Rampe genau einmal
(von der Oberkante bis zur Lippe), längs im gleichen Maßstab weiter, über alle Segmente
einer Kurve ohne Sprung.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Sequence

from ..geometry.brush import solid_polygons
from ..materials.sizes import texture_size
from ..model.objects import Face, TexAxis
from .hull import IPoint, hull_faces

Profile = list[list[tuple[float, float]]]  # konvexe Teile, je (quer, hoch)

NODRAW = "TOOLS/TOOLSNODRAW"


@dataclass
class Joint:
    x: float
    y: float
    z: float
    yaw: float  # Grad, Richtung der Rampe (0 = +X)
    profile: Profile | None = None
    #: Miter-Faktor für die Querachse an Knickstellen (1 / cos(halber Knick))
    miter: float = 1.0


@dataclass
class Materials:
    surf: str = "DEV/DEV_MEASUREGENERIC01B"
    side: str = "DEV/DEV_MEASUREGENERIC01"
    hidden: str = NODRAW
    #: Unterseite unsichtbar machen (bei Rampen, die auf dem Boden stehen oder nie von unten gesehen werden)
    hide_bottom: bool = True
    #: Surf-Textur quer einpassen (sonst Welt-Raster wie bei normalen Brushes)
    fit_surf: bool = False
    #: Größe der eingepassten Textur, 1.0 = quer genau einmal
    tex_size: float = 1.0
    #: Verschiebung der eingepassten Textur in Units (längs, quer)
    tex_shift: tuple[float, float] = (0.0, 0.0)


@dataclass
class SweepPiece:
    """Ein Segment-Brush: Seiten plus Index des Segments und des Profilteils."""

    faces: tuple[Face, ...]
    segment: int
    part: int


def face_material(normal: IPoint, materials: Materials) -> str:
    """Material einer Seite, die keine Kappe ist: schräg = Surf, senkrecht = Seite,
    waagrecht oben = Seite, waagrecht unten = unsichtbar."""
    nz = normal[2] / math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2)
    if nz <= -0.999:
        return materials.hidden if materials.hide_bottom else materials.side
    if abs(nz) < 0.01 or nz >= 0.999:
        return materials.side
    return materials.surf


def _round(v: float) -> int:
    return int(math.floor(v + 0.5))


#: Wie genau die Richtung eines ganzzahligen Querachsen-Vektors sein muss
LATTICE_TOLERANCE_DEG = 0.25


@lru_cache(maxsize=1024)
def lattice_dir(yaw: float, max_len: int = 32) -> tuple[int, int] | None:
    """Kürzester ganzzahliger Richtungsvektor (bis Länge `max_len`), der höchstens
    LATTICE_TOLERANCE_DEG von `yaw` abweicht, oder None, wenn es keinen gibt."""
    a = math.radians(yaw)
    dx, dy = math.cos(a), math.sin(a)
    best: tuple[float, int, int] | None = None
    for p in range(-max_len, max_len + 1):
        for q in range(-max_len, max_len + 1):
            n2 = p * p + q * q
            if n2 == 0 or n2 > max_len * max_len or math.gcd(p, q) != 1 or p * dx + q * dy <= 0:
                continue
            err = abs(math.degrees(math.atan2(p * dy - q * dx, p * dx + q * dy)))
            if err <= LATTICE_TOLERANCE_DEG and (best is None or (n2, p, q) < best):
                best = (n2, p, q)
    return None if best is None else (best[1], best[2])


@dataclass
class Sweep:
    joints: list[Joint]
    profile: Profile
    materials: Materials = field(default_factory=Materials)
    #: Kappen am Anfang und Ende sichtbar (sonst unsichtbar, z. B. wenn ein anderes Teil anschließt)
    open_start: bool = True
    open_end: bool = True
    #: Für gerade Wege: Querachse als ganzzahliger Vektor. Dann liegen alle Punkte eines
    #: Querschnitts exakt in einer Ebene und jedes Segment ist ein exaktes Prisma ohne Knicke.
    #: Lässt sich die Richtung nicht genau genug treffen, wird normal gerundet.
    lattice: bool = False

    def joint_points(self, k: int) -> list[list[IPoint]]:
        j = self.joints[k]
        prof = j.profile or self.profile
        axis = lattice_dir(round(j.yaw + 90, 6) % 360) if self.lattice else None
        if axis is not None:
            p, q = axis
            unit = math.hypot(p, q)
            cx, cy = _round(j.x), _round(j.y)
            return [[(cx + _round(o / unit) * p, cy + _round(o / unit) * q, _round(j.z + h)) for o, h in poly]
                    for poly in prof]
        a = math.radians(j.yaw)
        # Querachse zeigt nach links von der Laufrichtung
        lx, ly = -math.sin(a) * j.miter, math.cos(a) * j.miter
        return [[(_round(j.x + o * lx), _round(j.y + o * ly), _round(j.z + h)) for o, h in poly] for poly in prof]

    def build(self) -> list[SweepPiece]:
        pieces: list[SweepPiece] = []
        chains: dict = {}
        n = len(self.joints)
        rings = [self.joint_points(k) for k in range(n)]
        mats = self.materials
        # Welche Profilpunkte bilden die Unterseite bzw. eine flache Oberkante?
        profiles = [self.joints[k].profile or self.profile for k in range(n)]
        for k in range(n - 1):
            for part, (start, end) in enumerate(zip(rings[k], rings[k + 1])):
                start_set, end_set = set(start), set(end)
                base, top = set(), set()
                for ring, prof in ((start, profiles[k]), (end, profiles[k + 1])):
                    heights = [h for poly in prof for _o, h in poly]
                    lo, hi = min(heights), max(heights)
                    for pt, (_o, h) in zip(ring, prof[part]):
                        if h == lo:
                            base.add(pt)
                        if h == hi:
                            top.add(pt)
                first, last = k == 0, k == n - 2

                def material_for(normal: IPoint, loop: list[IPoint], s=start_set, e=end_set, f=first,
                                 la=last, b=base, t=top) -> str:
                    pts = set(loop)
                    if pts <= s:
                        return mats.side if f and self.open_start else mats.hidden
                    if pts <= e:
                        return mats.side if la and self.open_end else mats.hidden
                    if pts <= b:
                        return mats.hidden if mats.hide_bottom else mats.side
                    if pts <= t:
                        return mats.side
                    nz = normal[2] / math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2)
                    return mats.side if abs(nz) < 0.01 else mats.surf

                faces = hull_faces([*start, *end], material_for)
                if faces is not None:
                    if mats.fit_surf:
                        faces = self._fit_surf(faces, start_set, k, part, chains)
                    pieces.append(SweepPiece(faces, k, part))
        return pieces

    def _fit_surf(self, faces: tuple[Face, ...], seam: set[IPoint], k: int, part: int,
                  chains: dict) -> tuple[Face, ...]:
        """Surf-Flächen eines Segments eingepasst texturieren: u längs der Rampe, v quer
        hangabwärts. Ein Hang kann pro Segment aus mehreren Flächen bestehen, wenn das Runden
        auf ganze Units ihn leicht knickt; sie bekommen dieselbe Abbildung und passen so
        nahtlos. `chains` merkt sich je Hang (Profilteil und Seite) Maßstab und Abbildung des
        vorigen Segments: An der Mitte der Naht läuft die Textur ohne Sprung weiter."""
        mats = self.materials
        polys = solid_polygons(faces)
        a, b = self.joints[k], self.joints[k + 1]
        travel = _unit((b.x - a.x, b.y - a.y, b.z - a.z))
        left = (-math.sin(math.radians(a.yaw)), math.cos(math.radians(a.yaw)))
        slopes: dict = {}
        for i, (face, poly) in enumerate(zip(faces, polys)):
            if face.material != mats.surf or not poly:
                continue
            n = _unit(face.plane.normal)
            if abs(n[2]) > 0.999:
                continue
            key = (part, n[0] * left[0] + n[1] * left[1] > 0)
            slopes.setdefault(key, []).append((i, n, poly))
        out = list(faces)
        for key, members in slopes.items():
            n = _unit(tuple(sum(m[1][c] for m in members) for c in range(3)))
            u = _unit(tuple(travel[c] - n[c] * _dot(travel, n) for c in range(3)))
            v = _unit(_cross(n, u))
            if v[2] > 0:
                v = (-v[0], -v[1], -v[2])
            points = [p for m in members for p in m[2]]
            vs = [_dot(p, v) for p in points]
            w, h = texture_size(mats.surf)
            prev = chains.get(key)
            # Maßstab einmal je Hang, damit alle Segmente gleich groß texturiert sind
            scale = prev[4] if prev else round(max((max(vs) - min(vs)) / h * mats.tex_size, 0.01), 6)
            seam_pts = [p for p in points if (round(p[0]), round(p[1]), round(p[2])) in seam] or points
            mid = tuple(sum(p[c] for p in seam_pts) / len(seam_pts) for c in range(3))
            if prev:
                # Texturkoordinaten (in Units) an der Naht vom vorigen Segment übernehmen
                at_u = _dot(mid, prev[0]) + prev[2]
                at_v = _dot(mid, prev[1]) + prev[3]
                off_u, off_v = at_u - _dot(mid, u), at_v - _dot(mid, v)
            else:
                off_u = mats.tex_shift[0] - _dot(mid, u)
                off_v = mats.tex_shift[1] - min(vs)  # Oberkante = Texturrand
            chains[key] = (u, v, off_u, off_v, scale)
            uaxis = TexAxis(*_clean(u), _wrap(off_u / scale, w), scale)
            vaxis = TexAxis(*_clean(v), _wrap(off_v / scale, h), scale)
            for i, _n, _poly in members:
                out[i] = dataclasses.replace(faces[i], uaxis=uaxis, vaxis=vaxis, rotation=0.0)
        return tuple(out)


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b) -> tuple[float, float, float]:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(v) -> tuple[float, float, float]:
    n = math.sqrt(_dot(v, v))
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-12 else (0.0, 0.0, 0.0)


def _clean(v) -> tuple[float, float, float]:
    return tuple(0.0 if abs(c) < 1e-9 else round(c, 9) for c in v)  # type: ignore[return-value]


def _wrap(offset: float, size: int) -> float:
    r = round(offset % size, 4) if size else offset
    return 0.0 if r == size else r


def straight_joints(length: float, segments: int = 1, x: float = 0, y: float = 0, z: float = 0,
                    yaw: float = 0, dz: float = 0) -> list[Joint]:
    """Gerader Weg, optional mit Gefälle `dz` über die ganze Länge."""
    a = math.radians(yaw)
    segments = max(1, segments)
    out = []
    for i in range(segments + 1):
        t = i / segments
        out.append(Joint(x + math.cos(a) * length * t, y + math.sin(a) * length * t, z + dz * t, yaw))
    return out


def arc_joints(radius: float, angle: float, segment_length: float = 96.0, max_step: float = 5.0,
               x: float = 0, y: float = 0, z: float = 0, yaw: float = 0, dz: float = 0) -> list[Joint]:
    """Kreisbogen ab (x, y) in Richtung `yaw`; positiver Winkel biegt nach links.

    Die Schrittweite folgt der Segmentlänge auf der Mittellinie, höchstens `max_step` Grad.
    """
    if radius <= 0 or angle == 0:
        return straight_joints(segment_length, 1, x, y, z, yaw, dz)
    total = abs(angle)
    step = min(max_step, math.degrees(segment_length / radius))
    count = max(1, math.ceil(total / step - 1e-9))
    step = total / count
    sign = 1 if angle > 0 else -1
    a0 = math.radians(yaw)
    # Mittelpunkt liegt links (bzw. rechts) der Laufrichtung
    cx = x - math.sin(a0) * radius * sign
    cy = y + math.cos(a0) * radius * sign
    joints = []
    miter = 1 / math.cos(math.radians(step) / 2)
    for i in range(count + 1):
        heading = yaw + sign * step * i
        h = math.radians(heading)
        px = cx + math.sin(h) * radius * sign
        py = cy - math.cos(h) * radius * sign
        m = 1.0 if i in (0, count) else miter
        joints.append(Joint(px, py, z + dz * i / count, heading, miter=m))
    return joints


def _yaw_diff(a: float, b: float) -> float:
    return ((b - a + 180) % 360) - 180


def segment_yaw(a: Joint, b: Joint) -> float:
    return math.degrees(math.atan2(b.y - a.y, b.x - a.x))


def concat(*paths: Sequence[Joint]) -> list[Joint]:
    """Wege aneinanderhängen. Das gemeinsame Gelenk zeigt in die Mitte zwischen dem
    ankommenden und dem abgehenden Segment und bekommt den passenden Miter-Faktor."""
    out: list[Joint] = []
    for p in paths:
        if not p:
            continue
        if not out:
            out.extend(Joint(j.x, j.y, j.z, j.yaw, j.profile, j.miter) for j in p)
            continue
        if len(out) >= 2 and len(p) >= 2:
            d_in = segment_yaw(out[-2], out[-1])
            d_out = segment_yaw(p[0], p[1])
            bend = _yaw_diff(d_in, d_out)
            joint = out[-1]
            joint.yaw = d_in + bend / 2
            joint.miter = 1 / math.cos(math.radians(bend) / 2)
        out.extend(Joint(j.x, j.y, j.z, j.yaw, j.profile, j.miter) for j in p[1:])
    return out


def turn_after(path: Sequence[Joint]) -> tuple[float, float, float, float]:
    """Endpunkt und Richtung eines Weges, um den nächsten Abschnitt anzuhängen."""
    end = path[-1]
    return end.x, end.y, end.z, end.yaw
