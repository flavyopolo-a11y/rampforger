"""OpenGL-Zeichnen mit moderngl. Ein ViewportRenderer gehört zu genau einem GL-Kontext."""
from __future__ import annotations

import math
from importlib import resources

import moderngl
import numpy as np

from .camera import Camera2D, Camera3D
from .scene_mesh import SceneArrays
from .textures import LAYER_SIZE, MAX_LAYERS, TextureAtlas


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
        self._tex: moderngl.TextureArray | None = None
        self._tex_atlas: TextureAtlas | None = None
        self._tex_generation = -1
        self._tex_uploaded = 0

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

    def sync_textures(self, atlas: TextureAtlas | None) -> None:
        """Neue Ebenen des Atlas hochladen. Das Array wächst bei Bedarf (verdoppelt)."""
        if atlas is None:
            return
        if atlas is not self._tex_atlas or atlas.generation != self._tex_generation:
            self._tex_atlas, self._tex_generation, self._tex_uploaded = atlas, atlas.generation, 0
        count = atlas.layer_count
        if count <= self._tex_uploaded and self._tex is not None:
            return
        capacity = self._tex.size[2] if self._tex is not None else 0
        if count > capacity:
            new_capacity = min(MAX_LAYERS, max(32, capacity * 2))
            while new_capacity < count:
                new_capacity = min(MAX_LAYERS, new_capacity * 2)
            if self._tex is not None:
                self._tex.release()
            self._tex = self.ctx.texture_array((LAYER_SIZE, LAYER_SIZE, new_capacity), 4)
            self._tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            self._tex.repeat_x = self._tex.repeat_y = True
            self._tex_uploaded = 0
        assert self._tex is not None
        for layer in range(self._tex_uploaded, count):
            self._tex.write(atlas.layer_data(layer), viewport=(0, 0, layer, LAYER_SIZE, LAYER_SIZE, 1))
        self._tex.build_mipmaps()
        self._tex_uploaded = count

    def sync(self, arrays: SceneArrays, atlas: TextureAtlas | None = None) -> None:
        self.sync_textures(atlas)
        if arrays.version == self._version:
            return
        for vao in (self._faces_vao, self._lines_vao, self._sel_vao):
            if vao is not None:
                vao.release()
        self._faces_vbo, self._faces_vao = self._upload(
            arrays.faces, self._faces_vbo, self.prog_faces, "3f 3f 3f 2f 1f 1f",
            ("in_pos", "in_normal", "in_color", "in_uv", "in_layer", "in_selected"))
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
            textured = mode == "textured" and self._tex is not None
            self.prog_faces["u_textured"].value = 1.0 if textured else 0.0
            if textured:
                self._tex.use(0)
                self.prog_faces["u_textures"].value = 0
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
                    self._sel_vbo, self._dyn_vao, self._dyn_vbo, self.prog_faces, self.prog_lines, self._tex):
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
