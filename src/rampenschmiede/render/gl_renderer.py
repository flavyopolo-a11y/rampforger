"""OpenGL-Zeichnen mit moderngl. Ein ViewportRenderer gehört zu genau einem GL-Kontext."""
from __future__ import annotations

import math
from importlib import resources

import moderngl
import numpy as np

from .camera import Camera2D, Camera3D
from .scene_mesh import SceneArrays


def _shader(name: str) -> str:
    return resources.files("rampenschmiede.resources.shaders").joinpath(name).read_text(encoding="utf-8")


def _mat(m: np.ndarray) -> bytes:
    # numpy ist zeilenweise, GLSL erwartet spaltenweise
    return m.T.astype("f4").tobytes()


BACKGROUND_3D = (0.12, 0.13, 0.15)
BACKGROUND_2D = (0.0, 0.0, 0.0)


class ViewportRenderer:
    def __init__(self, ctx: moderngl.Context) -> None:
        self.ctx = ctx
        self.prog_faces = ctx.program(vertex_shader=_shader("faces.vert"), fragment_shader=_shader("faces.frag"))
        self.prog_lines = ctx.program(vertex_shader=_shader("lines.vert"), fragment_shader=_shader("lines.frag"))
        self._faces_vbo: moderngl.Buffer | None = None
        self._faces_vao: moderngl.VertexArray | None = None
        self._faces_count = 0
        self._lines_vbo: moderngl.Buffer | None = None
        self._lines_vao: moderngl.VertexArray | None = None
        self._lines_count = 0
        self._sel_vbo: moderngl.Buffer | None = None
        self._sel_vao: moderngl.VertexArray | None = None
        self._sel_count = 0
        self._dyn_vbo = ctx.buffer(reserve=6 * 4 * 4096, dynamic=True)
        self._dyn_vao = ctx.vertex_array(self.prog_lines, [(self._dyn_vbo, "3f 3f", "in_pos", "in_color")])
        self._version = -1

    # ---- Hochladen ---------------------------------------------------------
    def _upload(self, data: np.ndarray, vbo: moderngl.Buffer | None, prog: moderngl.Program, fmt: str,
                names: tuple[str, ...]) -> tuple[moderngl.Buffer | None, moderngl.VertexArray | None]:
        raw = data.astype("f4").tobytes()
        if not raw:
            return vbo, None
        if vbo is None or vbo.size < len(raw):
            if vbo is not None:
                vbo.release()
            vbo = self.ctx.buffer(reserve=max(len(raw), 1024) * 2, dynamic=True)
        vbo.write(raw)
        return vbo, self.ctx.vertex_array(prog, [(vbo, fmt, *names)])

    def sync(self, arrays: SceneArrays) -> None:
        if arrays.version == self._version:
            return
        for vao in (self._faces_vao, self._lines_vao, self._sel_vao):
            if vao is not None:
                vao.release()
        self._faces_vbo, self._faces_vao = self._upload(
            arrays.faces, self._faces_vbo, self.prog_faces, "3f 3f 3f 1f",
            ("in_pos", "in_normal", "in_color", "in_selected"))
        self._faces_count = len(arrays.faces)
        self._lines_vbo, self._lines_vao = self._upload(
            arrays.lines2d, self._lines_vbo, self.prog_lines, "3f 3f", ("in_pos", "in_color"))
        self._lines_count = len(arrays.lines2d)
        self._sel_vbo, self._sel_vao = self._upload(
            arrays.lines_sel, self._sel_vbo, self.prog_lines, "3f 3f", ("in_pos", "in_color"))
        self._sel_count = len(arrays.lines_sel)
        self._version = arrays.version

    def _draw_dynamic_lines(self, data: np.ndarray) -> None:
        if len(data) == 0:
            return
        raw = data.astype("f4").tobytes()
        if len(raw) > self._dyn_vbo.size:
            self._dyn_vao.release()
            self._dyn_vbo.release()
            self._dyn_vbo = self.ctx.buffer(reserve=len(raw) * 2, dynamic=True)
            self._dyn_vao = self.ctx.vertex_array(self.prog_lines, [(self._dyn_vbo, "3f 3f", "in_pos", "in_color")])
        self._dyn_vbo.write(raw)
        self._dyn_vao.render(moderngl.LINES, vertices=len(data))

    # ---- 3D ------------------------------------------------------------------
    def draw_3d(self, fbo: moderngl.Framebuffer, cam: Camera3D, width: int, height: int,
                mode: str = "shaded", extra_lines: np.ndarray | None = None,
                pixel_size: tuple[int, int] | None = None) -> None:
        """width/height in logischen Pixeln (für die Kamera), pixel_size in echten Pixeln."""
        fbo.use()
        self.ctx.viewport = (0, 0, *(pixel_size or (width, height)))
        fbo.clear(*BACKGROUND_3D, 1.0, depth=1.0)
        self.ctx.enable(moderngl.DEPTH_TEST)
        mvp = _mat(cam.mvp(width, height))
        if mode != "wireframe" and self._faces_vao is not None:
            self.prog_faces["u_mvp"].write(mvp)
            self.prog_faces["u_light_dir"].value = tuple(_normalize((0.35, 0.55, 0.9)))
            self.prog_faces["u_flat"].value = 1.0 if mode == "flat" else 0.0
            self.ctx.polygon_offset = (1.0, 1.0)
            self._faces_vao.render(moderngl.TRIANGLES, vertices=self._faces_count)
            self.ctx.polygon_offset = (0.0, 0.0)
        self.prog_lines["u_mvp"].write(mvp)
        if self._lines_vao is not None:
            # Drahtgitter in Brush-Farben, sonst dunkle Kanten für bessere Lesbarkeit
            self.prog_lines["u_override"].value = (0.0, 0.0, 0.0, 0.0) if mode == "wireframe" else (0.1, 0.1, 0.12, 1.0)
            self._lines_vao.render(moderngl.LINES, vertices=self._lines_count)
            self.prog_lines["u_override"].value = (0.0, 0.0, 0.0, 0.0)
        if self._sel_vao is not None:
            self.ctx.disable(moderngl.DEPTH_TEST)
            self._sel_vao.render(moderngl.LINES, vertices=self._sel_count)
            self.ctx.enable(moderngl.DEPTH_TEST)
        if extra_lines is not None:
            self._draw_dynamic_lines(extra_lines)
        self.ctx.disable(moderngl.DEPTH_TEST)

    # ---- 2D ------------------------------------------------------------------
    def draw_2d(self, fbo: moderngl.Framebuffer, cam: Camera2D, width: int, height: int, grid_size: int,
                extra_lines: np.ndarray | None = None, pixel_size: tuple[int, int] | None = None) -> None:
        fbo.use()
        self.ctx.viewport = (0, 0, *(pixel_size or (width, height)))
        fbo.clear(*BACKGROUND_2D, 1.0, depth=1.0)
        self.ctx.disable(moderngl.DEPTH_TEST)
        self.prog_lines["u_mvp"].write(_mat(cam.mvp(width, height)))
        self.prog_lines["u_override"].value = (0.0, 0.0, 0.0, 0.0)
        self._draw_dynamic_lines(grid_lines(cam, width, height, grid_size))
        if self._lines_vao is not None:
            self._lines_vao.render(moderngl.LINES, vertices=self._lines_count)
        if extra_lines is not None:
            self._draw_dynamic_lines(extra_lines)

    def release(self) -> None:
        for obj in (self._faces_vao, self._lines_vao, self._sel_vao, self._faces_vbo, self._lines_vbo,
                    self._sel_vbo, self._dyn_vao, self._dyn_vbo, self.prog_faces, self.prog_lines):
            if obj is not None:
                obj.release()


def _normalize(v: tuple[float, float, float]) -> tuple[float, float, float]:
    n = math.sqrt(sum(c * c for c in v))
    return (v[0] / n, v[1] / n, v[2] / n)


GRID_COLOR = (0.22, 0.22, 0.22)
GRID_COLOR_64 = (0.33, 0.33, 0.33)
GRID_COLOR_1024 = (0.45, 0.32, 0.12)
AXIS_COLOR = (0.15, 0.45, 0.65)
MIN_GRID_PIXELS = 6


def grid_lines(cam: Camera2D, width: int, height: int, grid_size: int) -> np.ndarray:
    """Gitterlinien für den sichtbaren Bereich. Wird das Gitter zu dicht, wird die
    Schrittweite verdoppelt, wie in Hammer."""
    step = max(1, grid_size)
    while step * cam.zoom < MIN_GRID_PIXELS:
        step *= 2
    h_axis, v_axis, d_axis = cam.axes
    h0, v1 = cam.to_world(0, 0, width, height)
    h1, v0 = cam.to_world(width, height, width, height)
    lines: list[list[float]] = []

    def point(h: float, v: float) -> list[float]:
        p = [0.0, 0.0, 0.0]
        p[h_axis], p[v_axis] = h, v
        return p

    def color(value: int) -> tuple[float, float, float]:
        if value == 0:
            return AXIS_COLOR
        if value % 1024 == 0:
            return GRID_COLOR_1024
        if value % 64 == 0 and step <= 64:
            return GRID_COLOR_64
        return GRID_COLOR

    start = math.floor(h0 / step) * step
    h = start
    while h <= h1:
        c = color(int(h))
        lines.append(point(h, v0) + list(c))
        lines.append(point(h, v1) + list(c))
        h += step
    start = math.floor(v0 / step) * step
    v = start
    while v <= v1:
        c = color(int(v))
        lines.append(point(h0, v) + list(c))
        lines.append(point(h1, v) + list(c))
        v += step
    return np.asarray(lines, dtype=np.float32).reshape(-1, 6)
