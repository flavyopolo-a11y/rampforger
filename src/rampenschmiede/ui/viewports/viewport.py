"""Eine Ansicht (3D oder 2D) als QOpenGLWidget mit moderngl.

Kamerasteuerung wie in Hammer:
- 3D: rechte Maustaste halten oder Z umschalten = Umsehen, dazu WASD, Q/E (runter/hoch),
  Mausrad vor/zurück, mittlere Maustaste = seitlich schieben, Shift = schneller
- 2D: Mausrad zoomt zum Mauszeiger, mittlere Maustaste oder Leertaste + Ziehen verschiebt
Die linke Maustaste gehört dem aktiven Werkzeug.
"""
from __future__ import annotations

import time

import moderngl
import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QKeyEvent, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ...render.camera import VIEW_AXES, Camera2D, Camera3D
from ...render.gl_renderer import ViewportRenderer
from ..editor import EditorContext
from ..panels.library_panel import MIME_TEMPLATE

VIEW_TITLES = {
    "3d": "3D",
    "top": "Oben (X/Y)",
    "front": "Vorne (Y/Z)",
    "side": "Seite (X/Z)",
}

RENDER_MODES = {"textured": "Texturiert", "shaded": "Schattiert", "flat": "Flach", "wireframe": "Drahtgitter"}

FLY_KEYS = {Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D, Qt.Key_Q, Qt.Key_E}


class Viewport(QOpenGLWidget):
    def __init__(self, editor: EditorContext, view: str = "3d", parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.view = view
        self.render_mode = "textured"
        self.cam3d = Camera3D.default()
        self.cam2d = Camera2D(view if view != "3d" else "top")
        self.ctx: moderngl.Context | None = None
        self.renderer: ViewportRenderer | None = None
        self.gl_error: str | None = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumSize(120, 90)

        self._mouselook = False
        self._mouselook_toggle = False
        self._pan_last: QPointF | None = None
        self._space_down = False
        self._keys: set[int] = set()
        self._last_tick = time.perf_counter()
        self._fly_timer = QTimer(self)
        self._fly_timer.setInterval(16)
        self._fly_timer.timeout.connect(self._fly_tick)
        self.mouse_world: tuple[float, float] | None = None

        editor.redraw_requested.connect(self.update)
        editor.document_replaced.connect(self._load_camera)
        self._load_camera()

    # ---- Ansichtstyp -------------------------------------------------------------
    @property
    def is_3d(self) -> bool:
        return self.view == "3d"

    def set_view(self, view: str) -> None:
        self.view = view
        if view != "3d":
            center = (self.cam2d.center_h, self.cam2d.center_v)
            self.cam2d.view = view
            self.cam2d.center_h, self.cam2d.center_v = center
        self.update()

    def axes(self) -> tuple[int, int, int]:
        return VIEW_AXES[self.view]

    def _load_camera(self) -> None:
        ed = self.editor.doc.editor
        self.cam3d.position = np.array(ed.camera_position, dtype=float)
        self.cam3d.yaw, self.cam3d.pitch = ed.camera_angles
        self.update()

    def store_camera(self) -> None:
        if self.is_3d:
            ed = self.editor.doc.editor
            ed.camera_position = tuple(float(c) for c in self.cam3d.position)  # type: ignore[assignment]
            ed.camera_angles = (self.cam3d.yaw, self.cam3d.pitch)

    # ---- OpenGL ------------------------------------------------------------------
    def initializeGL(self) -> None:
        try:
            self.ctx = moderngl.create_context()
            self.renderer = ViewportRenderer(self.ctx)
        except Exception as exc:  # pragma: no cover - hängt vom Grafiktreiber ab
            self.gl_error = f"OpenGL 3.3 nicht verfügbar: {exc}"
            self.editor.status_message.emit(self.gl_error)

    def paintGL(self) -> None:
        if self.renderer is None or self.ctx is None:
            self._paint_error()
            return
        dpr = self.devicePixelRatioF()
        w, h = self.width(), self.height()
        pixels = (max(1, int(w * dpr)), max(1, int(h * dpr)))
        painter = QPainter(self)
        # Qt-Zeichenzustand sichern, damit moderngl und QPainter sich nicht stören
        painter.beginNativePainting()
        try:
            fbo = self.ctx.detect_framebuffer(self.defaultFramebufferObject())
            self.renderer.sync(self.editor.scene.arrays(), self.editor.scene.atlas if self.is_3d else None)
            tool = self.editor.tool
            if self.is_3d:
                extra = _join_lines(tool.lines_3d(self) if tool else None, self.editor.leak_lines)
                self.renderer.draw_3d(fbo, self.cam3d, w, h, self.render_mode, extra, pixels)
            else:
                extra = _join_lines(tool.lines_2d(self) if tool else None, self.editor.leak_lines)
                self.renderer.draw_2d(fbo, self.cam2d, w, h, self.editor.grid, extra, pixels)
            self.ctx.disable(moderngl.DEPTH_TEST)
        finally:
            painter.endNativePainting()
        self._paint_overlay(painter)
        painter.end()

    def _paint_error(self) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(40, 0, 0))
        p.setPen(QColor(255, 200, 200))
        p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self.gl_error or "OpenGL nicht verfügbar")
        p.end()

    def _paint_overlay(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        font = QFont(self.font())
        font.setPointSizeF(9)
        p.setFont(font)
        if self._mouselook:
            p.setPen(QColor(255, 200, 80))
            p.drawText(8, 16, self.tr("Umsehen · W A S D fliegen · Q/E runter/hoch · Shift schneller"))
        if self.editor.tool:
            if self.is_3d:
                self.editor.tool.paint_3d(self, p)
            else:
                self.editor.tool.paint_2d(self, p)

    # ---- Koordinaten ---------------------------------------------------------------
    def to_world(self, pos: QPointF | QPoint) -> tuple[float, float]:
        return self.cam2d.to_world(pos.x(), pos.y(), self.width(), self.height())

    def to_screen(self, h: float, v: float) -> QPointF:
        x, y = self.cam2d.to_screen(h, v, self.width(), self.height())
        return QPointF(x, y)

    def ray(self, pos: QPointF | QPoint) -> tuple[np.ndarray, np.ndarray]:
        return self.cam3d.ray(pos.x(), pos.y(), self.width(), self.height())

    # ---- Vorlagen hineinziehen ---------------------------------------------------------
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasFormat(MIME_TEMPLATE):
            e.acceptProposedAction()

    def dragMoveEvent(self, e) -> None:
        if e.mimeData().hasFormat(MIME_TEMPLATE):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        if not e.mimeData().hasFormat(MIME_TEMPLATE):
            return
        key = bytes(e.mimeData().data(MIME_TEMPLATE)).decode("utf-8")
        e.acceptProposedAction()
        self.editor.template_dropped.emit(key, self.drop_point(e.position()))

    def drop_point(self, pos: QPointF) -> tuple[float, float, float]:
        """Weltpunkt unter der Maus: in 2D auf Höhe 0 der fehlenden Achse, in 3D die
        getroffene Fläche oder sonst der Boden (z = 0)."""
        if not self.is_3d:
            h_axis, v_axis, _ = self.axes()
            wh, wv = self.to_world(pos)
            p = [0.0, 0.0, 0.0]
            p[h_axis], p[v_axis] = wh, wv
            return (p[0], p[1], p[2])
        from ..tools.base import pick_3d

        origin, direction = self.ray(pos)
        hit = pick_3d(self.editor, origin, direction)
        if hit is not None:
            point = origin + direction * hit[1]
        elif direction[2] < -1e-6:
            point = origin + direction * (-origin[2] / direction[2])
        else:
            point = origin + direction * 512
        return (float(point[0]), float(point[1]), float(point[2]))

    def center_on(self, point: tuple[float, float, float], size: float | None = None) -> None:
        if self.is_3d:
            dist = max(256.0, (size or 256.0) * 1.5)
            self.cam3d.look_at_point(np.array(point, dtype=float), dist)
        else:
            h, v, _ = self.axes()
            self.cam2d.center_h, self.cam2d.center_v = point[h], point[v]
            if size:
                self.cam2d.zoom = max(0.02, min(8.0, min(self.width(), self.height()) / (size * 1.6)))
        self.update()

    # ---- Maus ------------------------------------------------------------------------
    def mousePressEvent(self, e: QMouseEvent) -> None:
        self.setFocus()
        if self.is_3d and e.button() == Qt.RightButton:
            self._start_mouselook(e)
            return
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and self._space_down):
            self._pan_last = e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() == Qt.LeftButton and self.editor.tool:
            if self.is_3d:
                self.editor.tool.press_3d(self, e)
            else:
                self.editor.tool.press_2d(self, e)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._mouselook:
            self._mouselook_move(e)
            return
        if self._pan_last is not None:
            d = e.position() - self._pan_last
            self._pan_last = e.position()
            if self.is_3d:
                f = 2.0 if e.modifiers() & Qt.ShiftModifier else 1.0
                self.cam3d.position = self.cam3d.position - self.cam3d.right() * d.x() * f + self.cam3d.up() * d.y() * f
            else:
                self.cam2d.center_h -= d.x() / self.cam2d.zoom
                self.cam2d.center_v += d.y() / self.cam2d.zoom
            self.update()
            return
        if not self.is_3d:
            self.mouse_world = self.to_world(e.position())
            self._report_cursor()
        if self.editor.tool:
            if self.is_3d:
                self.editor.tool.move_3d(self, e)
            else:
                self.editor.tool.move_2d(self, e)
                self.setCursor(self.editor.tool.cursor_2d(self, e.position()))

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if self.is_3d and e.button() == Qt.RightButton and self._mouselook and not self._mouselook_toggle:
            self._stop_mouselook()
            return
        if self._pan_last is not None and e.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._pan_last = None
            self.unsetCursor()
            return
        if e.button() == Qt.LeftButton and self.editor.tool:
            if self.is_3d:
                self.editor.tool.release_3d(self, e)
            else:
                self.editor.tool.release_2d(self, e)

    def mouseDoubleClickEvent(self, e: QMouseEvent) -> None:
        self.mousePressEvent(e)

    def wheelEvent(self, e: QWheelEvent) -> None:
        steps = e.angleDelta().y() / 120.0
        if self.is_3d:
            f = 4.0 if e.modifiers() & Qt.ShiftModifier else 1.0
            self.cam3d.position = self.cam3d.position + self.cam3d.forward() * steps * 64 * f
        else:
            self.cam2d.zoom_at(1.2 ** steps, e.position().x(), e.position().y(), self.width(), self.height())
            self._report_cursor()
        self.update()

    def _report_cursor(self) -> None:
        if self.mouse_world is None:
            return
        names = "XYZ"
        h, v, _ = self.axes()
        g = self.editor.grid
        self.editor.status_message.emit(
            f"{names[h]} {self.editor.snap(self.mouse_world[0])}  {names[v]} {self.editor.snap(self.mouse_world[1])}"
            f"  ·  Zoom {self.cam2d.zoom:.2f}  ·  Raster {g}"
        )

    # ---- Umsehen und Fliegen (3D) -------------------------------------------------------
    def _start_mouselook(self, e: QMouseEvent | None = None, toggle: bool = False) -> None:
        self._mouselook = True
        self._mouselook_toggle = toggle
        self._look_center = self.mapToGlobal(self.rect().center())
        QCursor.setPos(self._look_center)
        self.setCursor(Qt.BlankCursor)
        self.grabMouse()
        self._fly_timer.start()
        self._last_tick = time.perf_counter()
        self.update()

    def _stop_mouselook(self) -> None:
        self._mouselook = False
        self._mouselook_toggle = False
        self.releaseMouse()
        self.unsetCursor()
        if not self._keys:
            self._fly_timer.stop()
        self.store_camera()
        self.update()

    def _mouselook_move(self, e: QMouseEvent) -> None:
        gpos = e.globalPosition().toPoint()
        d = gpos - self._look_center
        if d.x() == 0 and d.y() == 0:
            return
        self.cam3d.rotate(-d.x() * 0.2, -d.y() * 0.2)
        QCursor.setPos(self._look_center)
        self.update()

    def _fly_tick(self) -> None:
        now = time.perf_counter()
        dt = min(0.1, now - self._last_tick)
        self._last_tick = now
        if not self._keys:
            if not self._mouselook:
                self._fly_timer.stop()
            return
        cam = self.cam3d
        move = np.zeros(3)
        if Qt.Key_W in self._keys:
            move += cam.forward()
        if Qt.Key_S in self._keys:
            move -= cam.forward()
        if Qt.Key_D in self._keys:
            move += cam.right()
        if Qt.Key_A in self._keys:
            move -= cam.right()
        if Qt.Key_E in self._keys:
            move += np.array([0.0, 0.0, 1.0])
        if Qt.Key_Q in self._keys:
            move -= np.array([0.0, 0.0, 1.0])
        if np.linalg.norm(move) > 0:
            boost = 3.0 if self._shift else 1.0
            cam.position = cam.position + move / np.linalg.norm(move) * cam.speed * boost * dt
            self.update()

    _shift = False

    # ---- Tastatur ------------------------------------------------------------------------
    def event(self, e: QEvent) -> bool:
        # Beim Fliegen gehören WASD/Q/E der Kamera, auch mit Shift (sonst würde z. B.
        # Shift+E das Entity-Werkzeug wählen).
        if e.type() == QEvent.ShortcutOverride and self._mouselook and e.key() in FLY_KEYS:
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        self._shift = bool(e.modifiers() & Qt.ShiftModifier)
        key = e.key()
        if e.isAutoRepeat() and key in FLY_KEYS:
            return
        if self.is_3d and key == Qt.Key_Z and not e.modifiers():
            if self._mouselook:
                self._stop_mouselook()
            else:
                self._start_mouselook(toggle=True)
            return
        if self.is_3d and (self._mouselook or not (e.modifiers() & Qt.ControlModifier)) and key in FLY_KEYS \
                and (self._mouselook or self.editor.tool is None or not self.editor.tool.wants_key(key)):
            self._keys.add(key)
            if not self._fly_timer.isActive():
                self._last_tick = time.perf_counter()
                self._fly_timer.start()
            return
        if key == Qt.Key_Space and not e.isAutoRepeat():
            self._space_down = True
            self.setCursor(Qt.OpenHandCursor)
            return
        if self.editor.tool and self.editor.tool.key_press(self, e):
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e: QKeyEvent) -> None:
        self._shift = bool(e.modifiers() & Qt.ShiftModifier)
        if e.isAutoRepeat():
            return
        if e.key() in self._keys:
            self._keys.discard(e.key())
            return
        if e.key() == Qt.Key_Space:
            self._space_down = False
            self.unsetCursor()
            return
        super().keyReleaseEvent(e)

    def focusOutEvent(self, e) -> None:
        self._keys.clear()
        self._space_down = False
        if self._mouselook:
            self._stop_mouselook()
        super().focusOutEvent(e)
        self.update()

    def focusInEvent(self, e) -> None:
        super().focusInEvent(e)
        self.update()


def _join_lines(*parts):
    """Werkzeug-Linien und Leck-Spur in einen Puffer, leere Teile fallen weg."""
    present = [p for p in parts if p is not None and len(p)]
    if not present:
        return None
    return present[0] if len(present) == 1 else np.concatenate(present)
