"""Kameras für die 3D- und 2D-Ansichten. Matrizen sind numpy-Arrays (Zeilen-Major);
beim Hochladen in den Shader werden sie transponiert."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# Achsen der 2D-Ansichten wie in Hammer: (horizontal, vertikal, Tiefe)
VIEW_AXES = {
    "top": (0, 1, 2),    # Oben: X/Y
    "front": (1, 2, 0),  # Vorne: Y/Z
    "side": (0, 2, 1),   # Seite: X/Z
}


def perspective(fov_y_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov_y_deg) / 2)
    m = np.zeros((4, 4), dtype=np.float64)
    m[0, 0] = f / max(aspect, 1e-6)
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    f = target - eye
    f = f / np.linalg.norm(f)
    s = np.cross(f, up)
    if np.linalg.norm(s) < 1e-9:
        s = np.cross(f, np.array([0.0, 1.0, 0.0]))
    s = s / np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.identity(4)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


@dataclass
class Camera3D:
    position: np.ndarray
    yaw: float = 45.0     # Grad, 0 = Blick entlang +X
    pitch: float = -25.0  # Grad, positiv = nach oben
    fov: float = 75.0
    near: float = 4.0
    far: float = 65536.0
    speed: float = 600.0  # Units pro Sekunde

    @staticmethod
    def default() -> "Camera3D":
        return Camera3D(np.array([-512.0, -512.0, 384.0]))

    def forward(self) -> np.ndarray:
        y, p = math.radians(self.yaw), math.radians(self.pitch)
        return np.array([math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p)])

    def right(self) -> np.ndarray:
        y = math.radians(self.yaw)
        return np.array([math.sin(y), -math.cos(y), 0.0])

    def up(self) -> np.ndarray:
        return np.cross(self.right(), self.forward())

    def view(self) -> np.ndarray:
        return look_at(self.position, self.position + self.forward(), np.array([0.0, 0.0, 1.0]))

    def projection(self, width: int, height: int) -> np.ndarray:
        return perspective(self.fov, width / max(height, 1), self.near, self.far)

    def mvp(self, width: int, height: int) -> np.ndarray:
        return self.projection(width, height) @ self.view()

    def rotate(self, dyaw: float, dpitch: float) -> None:
        self.yaw = (self.yaw + dyaw) % 360.0
        self.pitch = max(-89.0, min(89.0, self.pitch + dpitch))

    def ray(self, x: float, y: float, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
        """Strahl durch Pixel (x, y), Ursprung oben links."""
        nx = 2 * x / max(width, 1) - 1
        ny = 1 - 2 * y / max(height, 1)
        inv = np.linalg.inv(self.mvp(width, height))
        near = inv @ np.array([nx, ny, -1.0, 1.0])
        far = inv @ np.array([nx, ny, 1.0, 1.0])
        near, far = near[:3] / near[3], far[:3] / far[3]
        d = far - near
        return self.position.copy(), d / np.linalg.norm(d)

    def look_at_point(self, target: np.ndarray, distance: float | None = None) -> None:
        if distance is not None:
            self.position = target - self.forward() * distance
        d = target - self.position
        if np.linalg.norm(d) < 1e-6:
            return
        d = d / np.linalg.norm(d)
        self.yaw = math.degrees(math.atan2(d[1], d[0])) % 360
        self.pitch = math.degrees(math.asin(max(-1.0, min(1.0, d[2]))))


@dataclass
class Camera2D:
    view: str = "top"
    center_h: float = 0.0
    center_v: float = 0.0
    zoom: float = 0.5  # Pixel pro Unit

    @property
    def axes(self) -> tuple[int, int, int]:
        return VIEW_AXES[self.view]

    def mvp(self, width: int, height: int) -> np.ndarray:
        h, v, d = self.axes
        m = np.zeros((4, 4))
        sx = 2 * self.zoom / max(width, 1)
        sy = 2 * self.zoom / max(height, 1)
        m[0, h] = sx
        m[0, 3] = -self.center_h * sx
        m[1, v] = sy
        m[1, 3] = -self.center_v * sy
        m[3, 3] = 1.0
        return m

    def to_world(self, x: float, y: float, width: int, height: int) -> tuple[float, float]:
        """Pixel (Ursprung oben links) zu (horizontal, vertikal) in Welt-Units."""
        return (
            self.center_h + (x - width / 2) / self.zoom,
            self.center_v - (y - height / 2) / self.zoom,
        )

    def to_screen(self, h: float, v: float, width: int, height: int) -> tuple[float, float]:
        return (
            (h - self.center_h) * self.zoom + width / 2,
            height / 2 - (v - self.center_v) * self.zoom,
        )

    def zoom_at(self, factor: float, x: float, y: float, width: int, height: int) -> None:
        before = self.to_world(x, y, width, height)
        self.zoom = max(0.01, min(64.0, self.zoom * factor))
        after = self.to_world(x, y, width, height)
        self.center_h += before[0] - after[0]
        self.center_v += before[1] - after[1]
