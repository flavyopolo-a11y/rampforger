"""Kleine 3D-Ansicht für Browser: Modelle und Materialien texturiert und beleuchtet anschauen.

Ziehen dreht (Kamera kreist um die Mitte), das Mausrad zoomt. Der Inhalt sind Gruppen aus
Dreiecken mit je einer Textur; `model_groups` und `material_groups` bauen sie aus einem Modell
bzw. aus einem Material auf einer Grundform (Kugel, Würfel, Rampe).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import moderngl
import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ...core.materials import MaterialLibrary
from ...core.materials.library import TextureImage

BACKGROUND = (0.118, 0.122, 0.133)
NO_TEXTURE = (0.69, 0.69, 0.67)
FOV = 35.0
SHAPES = {"kugel": "Kugel", "wuerfel": "Würfel", "rampe": "Rampe"}

_VERT = """
#version 330
uniform mat4 u_mvp;
in vec3 in_pos;
in vec3 in_normal;
in vec2 in_uv;
out vec3 v_normal;
out vec2 v_uv;
void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
    v_normal = in_normal;
    v_uv = in_uv;
}
"""
_FRAG = """
#version 330
uniform sampler2D u_tex;
uniform float u_textured;
uniform vec3 u_color;
uniform vec3 u_light;
uniform vec3 u_eye_dir;
in vec3 v_normal;
in vec2 v_uv;
out vec4 f_color;
void main() {
    vec4 base = u_textured > 0.5 ? texture(u_tex, v_uv) : vec4(u_color, 1.0);
    if (base.a < 0.35) discard;  // Laub, Gitter: durchsichtige Stellen weglassen
    vec3 n = normalize(v_normal);
    if (dot(n, u_eye_dir) > 0.0) n = -n;  // zweiseitige Flächen von beiden Seiten beleuchten
    float light = 0.38 + 0.62 * max(dot(n, u_light), 0.0);
    f_color = vec4(base.rgb * light, 1.0);
}
"""


@dataclass
class MeshGroup:
    """Dreiecke ohne Indizes (je drei Ecken hintereinander) mit einer Textur."""

    positions: np.ndarray  # (n, 3)
    normals: np.ndarray    # (n, 3)
    uvs: np.ndarray        # (n, 2)
    texture: TextureImage | None = None
    color: tuple[float, float, float] = NO_TEXTURE


def model_groups(model, library: MaterialLibrary | None, skin: int = 0) -> list[MeshGroup]:
    """Ein Modell, je Material eine Gruppe."""
    geom = getattr(model, "geometry", None)
    if geom is None or not geom.triangle_count:
        return []
    materials = model.materials(skin)
    out = []
    for index in np.unique(geom.tri_material):
        tris = geom.triangles[geom.tri_material == index].reshape(-1)
        name = materials[index] if index < len(materials) else ""
        tex = library.texture(name) if library is not None and name else None
        out.append(MeshGroup(geom.positions[tris], geom.normals[tris], geom.uvs[tris], tex))
    return out


def _sphere(rings: int = 24, segments: int = 48, r: float = 64.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    pos, nor, uv = [], [], []

    def vertex(i: int, j: int) -> None:
        theta = math.pi * i / rings
        phi = 2 * math.pi * j / segments
        n = (math.sin(theta) * math.cos(phi), math.sin(theta) * math.sin(phi), math.cos(theta))
        pos.append([c * r for c in n])
        nor.append(n)
        uv.append((2.0 * j / segments, 1.0 * i / rings))

    for i in range(rings):
        for j in range(segments):
            for a, b in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j), (i + 1, j + 1), (i, j + 1)):
                vertex(a, b)
    return (np.asarray(pos, np.float32), np.asarray(nor, np.float32), np.asarray(uv, np.float32))


def _quads(quads: list[tuple[tuple, ...]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vierecke (a, b, c, d gegen den Uhrzeigersinn von außen) mit Textur 0..1 je Viereck."""
    pos, nor, uv = [], [], []
    corners_uv = ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0))
    for quad in quads:
        a, b, c = (np.asarray(p, np.float64) for p in quad[:3])
        n = np.cross(b - a, c - a)
        n /= max(np.linalg.norm(n), 1e-9)
        pts = list(quad) if len(quad) == 4 else [quad[0], quad[1], quad[2], quad[2]]
        for k in (0, 1, 2, 0, 2, 3):
            pos.append(pts[k])
            nor.append(n)
            uv.append(corners_uv[k])
    return (np.asarray(pos, np.float32), np.asarray(nor, np.float32), np.asarray(uv, np.float32))


def _cube(s: float = 48.0):
    p = [(-s, -s, -s), (s, -s, -s), (s, s, -s), (-s, s, -s), (-s, -s, s), (s, -s, s), (s, s, s), (-s, s, s)]
    faces = ((4, 5, 6, 7), (3, 2, 1, 0), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    return _quads([tuple(p[i] for i in f) for f in faces])


def _ramp(length: float = 96.0, width: float = 64.0, height: float = 64.0):
    """Surf-Rampe im Querschnitt: zwei schräge Flächen, Boden und Stirnseiten."""
    x0, x1, h, w = -length / 2, length / 2, height, width / 2
    top = [(x0, 0.0, h), (x1, 0.0, h)]
    left = [(x0, -w, 0.0), (x1, -w, 0.0)]
    right = [(x0, w, 0.0), (x1, w, 0.0)]
    quads = [
        (left[0], left[1], top[1], top[0]),
        (right[1], right[0], top[0], top[1]),
        (left[1], left[0], right[0], right[1]),
        (left[0], top[0], right[0]),
        (left[1], right[1], top[1]),
    ]
    pos, nor, uv = _quads(quads)
    pos[:, 2] -= h / 2
    return pos, nor, uv


def material_groups(name: str, library: MaterialLibrary | None, shape: str = "kugel") -> list[MeshGroup]:
    """Ein Material auf einer Grundform."""
    build = {"kugel": _sphere, "wuerfel": _cube, "rampe": _ramp}.get(shape, _sphere)
    pos, nor, uv = build()
    tex = library.texture(name) if library is not None and name else None
    return [MeshGroup(pos, nor, uv, tex)]


def _perspective(fov: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov) / 2)
    m = np.zeros((4, 4))
    m[0, 0], m[1, 1] = f / aspect, f
    m[2, 2], m[2, 3] = (far + near) / (near - far), 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def _look_at(eye: np.ndarray, center: np.ndarray) -> np.ndarray:
    f = center - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, (0.0, 0.0, 1.0))
    s /= max(np.linalg.norm(s), 1e-9)
    u = np.cross(s, f)
    m = np.identity(4)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


class Preview3D(QOpenGLWidget):
    """Drehbare 3D-Vorschau. `set_groups` tauscht den Inhalt, die Kamera passt sich an."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setToolTip(self.tr("Ziehen dreht, Mausrad zoomt"))
        self.yaw, self.pitch, self.zoom = 35.0, 22.0, 1.0
        self.groups: list[MeshGroup] = []
        self.ctx: moderngl.Context | None = None
        self.gl_error: str | None = None
        self._gpu: list[tuple[moderngl.VertexArray, moderngl.Buffer, moderngl.Texture | None, MeshGroup]] = []
        self._dirty = True
        self._center = np.zeros(3)
        self._radius = 64.0
        self._last: QPointF | None = None

    # ---- Inhalt ------------------------------------------------------------------------
    def set_groups(self, groups: list[MeshGroup], reset_view: bool = True) -> None:
        self.groups = groups
        self._dirty = True
        if groups:
            allpos = np.concatenate([g.positions for g in groups])
            lo, hi = allpos.min(axis=0), allpos.max(axis=0)
            self._center = (lo + hi) / 2
            self._radius = max(float(np.linalg.norm(hi - lo)) / 2, 1.0)
        if reset_view:
            self.zoom = 1.0
        self.update()

    def clear(self) -> None:
        self.set_groups([])

    # ---- OpenGL ------------------------------------------------------------------------
    def initializeGL(self) -> None:
        try:
            self.ctx = moderngl.create_context()
            self.prog = self.ctx.program(vertex_shader=_VERT, fragment_shader=_FRAG)
        except Exception as exc:  # pragma: no cover - hängt vom Grafiktreiber ab
            self.ctx = None
            self.gl_error = str(exc)

    def _upload(self) -> None:
        for vao, vbo, tex, _g in self._gpu:
            vao.release()
            vbo.release()
            if tex is not None:
                tex.release()
        self._gpu = []
        assert self.ctx is not None
        for g in self.groups:
            data = np.hstack([g.positions, g.normals, g.uvs]).astype("f4")
            vbo = self.ctx.buffer(data.tobytes())
            vao = self.ctx.vertex_array(self.prog, [(vbo, "3f 3f 2f", "in_pos", "in_normal", "in_uv")])
            tex = None
            if g.texture is not None:
                tex = self.ctx.texture((g.texture.width, g.texture.height), 4, g.texture.rgba)
                tex.build_mipmaps()
                tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
                tex.repeat_x = tex.repeat_y = True
            self._gpu.append((vao, vbo, tex, g))
        self._dirty = False

    def eye(self) -> np.ndarray:
        y, p = math.radians(self.yaw), math.radians(self.pitch)
        dist = self._radius / math.sin(math.radians(FOV) / 2) * 1.05 / self.zoom
        return self._center + dist * np.array([math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p)])

    def paintGL(self) -> None:
        if self.ctx is None:
            return
        fbo = self.ctx.detect_framebuffer(self.defaultFramebufferObject())
        fbo.use()
        dpr = self.devicePixelRatioF()
        self.ctx.viewport = (0, 0, max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        fbo.clear(*BACKGROUND, 1.0, depth=1.0)
        if self._dirty:
            self._upload()
        if not self._gpu:
            return
        self.ctx.enable(moderngl.DEPTH_TEST)
        eye = self.eye()
        dist = float(np.linalg.norm(eye - self._center))
        mvp = _perspective(FOV, self.width() / max(1, self.height()), max(dist / 100, 0.1),
                           dist + self._radius * 4) @ _look_at(eye, self._center)
        self.prog["u_mvp"].write(mvp.T.astype("f4").tobytes())
        light = np.array([0.45, 0.35, 0.82])
        self.prog["u_light"].value = tuple(light / np.linalg.norm(light))
        view_dir = (self._center - eye) / max(dist, 1e-9)
        self.prog["u_eye_dir"].value = tuple(float(c) for c in view_dir)
        for vao, _vbo, tex, g in self._gpu:
            textured = tex is not None
            self.prog["u_textured"].value = 1.0 if textured else 0.0
            self.prog["u_color"].value = g.color
            if textured:
                tex.use(0)
                self.prog["u_tex"].value = 0
            vao.render(moderngl.TRIANGLES)
        self.ctx.disable(moderngl.DEPTH_TEST)

    # ---- Maus --------------------------------------------------------------------------
    def mousePressEvent(self, e: QMouseEvent) -> None:
        self._last = e.position()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._last is None:
            return
        d = e.position() - self._last
        self._last = e.position()
        self.yaw = (self.yaw - d.x() * 0.8) % 360
        self.pitch = max(-85.0, min(85.0, self.pitch + d.y() * 0.6))
        self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._last = None

    def wheelEvent(self, e: QWheelEvent) -> None:
        self.zoom = max(0.4, min(6.0, self.zoom * (1.15 if e.angleDelta().y() > 0 else 1 / 1.15)))
        self.update()


__all__ = ["MeshGroup", "Preview3D", "SHAPES", "material_groups", "model_groups"]
