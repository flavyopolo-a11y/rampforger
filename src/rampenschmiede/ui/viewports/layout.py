"""Vier Ansichten im 2x2-Raster mit verschiebbaren Trennern. Jede Ansicht kann über
ihre Kopfzeile auf 3D, Oben, Vorne oder Seite umgestellt werden (wie in Hammer)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QSplitter, QVBoxLayout, QWidget

from ..editor import EditorContext
from .viewport import RENDER_MODES, VIEW_TITLES, Viewport

DEFAULT_LAYOUT = ("3d", "top", "front", "side")

#: Rahmen der aktiven Ansicht (wie in Hammer hervorgehoben)
ACTIVE_STYLE = ("ViewportFrame { border: 2px solid #ff8c28; }"
                " #viewHeader { background: rgba(255, 140, 40, 0.22); }")
INACTIVE_STYLE = "ViewportFrame { border: 2px solid transparent; }"


class ViewportFrame(QFrame):
    def __init__(self, editor: EditorContext, view: str, parent=None) -> None:
        super().__init__(parent)
        self.viewport = Viewport(editor, view)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        header = QWidget()
        header.setObjectName("viewHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(4, 2, 4, 2)
        self.view_combo = QComboBox()
        for key, title in VIEW_TITLES.items():
            self.view_combo.addItem(self.tr(title), key)
        self.view_combo.setCurrentIndex(list(VIEW_TITLES).index(view))
        self.view_combo.currentIndexChanged.connect(self._on_view)
        self.mode_combo = QComboBox()
        for key, title in RENDER_MODES.items():
            self.mode_combo.addItem(self.tr(title), key)
        self.mode_combo.currentIndexChanged.connect(self._on_mode)
        hl.addWidget(self.view_combo)
        hl.addWidget(self.mode_combo)
        hl.addStretch(1)
        lay.addWidget(header)
        lay.addWidget(self.viewport, 1)
        self.mode_combo.setVisible(view == "3d")
        self.active = False
        self.set_active(False)

    def set_active(self, on: bool) -> None:
        self.active = on
        self.setStyleSheet(ACTIVE_STYLE if on else INACTIVE_STYLE)

    def _on_view(self, _: int) -> None:
        view = self.view_combo.currentData()
        self.viewport.set_view(view)
        self.mode_combo.setVisible(view == "3d")

    def _on_mode(self, _: int) -> None:
        self.viewport.render_mode = self.mode_combo.currentData()
        self.viewport.update()

    def set_view(self, view: str) -> None:
        self.view_combo.setCurrentIndex(list(VIEW_TITLES).index(view))


class ViewportGrid(QSplitter):
    def __init__(self, editor: EditorContext, parent=None) -> None:
        super().__init__(Qt.Vertical, parent)
        self.frames: list[ViewportFrame] = []
        self.rows = []
        for r in range(2):
            row = QSplitter(Qt.Horizontal)
            for c in range(2):
                frame = ViewportFrame(editor, DEFAULT_LAYOUT[r * 2 + c])
                row.addWidget(frame)
                self.frames.append(frame)
                frame.viewport.activated.connect(lambda f=frame: self.set_active(f))
            self.addWidget(row)
            self.rows.append(row)
        self.reset()
        self.set_active(self.frames[0])

    def set_active(self, frame: ViewportFrame) -> None:
        for f in self.frames:
            if f.active != (f is frame):
                f.set_active(f is frame)

    def active_frame(self) -> ViewportFrame | None:
        return next((f for f in self.frames if f.active), None)

    def reset(self) -> None:
        self.setSizes([1, 1])
        for row in self.rows:
            row.setSizes([1, 1])
        for frame, view in zip(self.frames, DEFAULT_LAYOUT):
            frame.set_view(view)

    def viewports(self) -> list[Viewport]:
        return [f.viewport for f in self.frames]

    def save_state(self) -> dict:
        return {
            "outer": [int(s) for s in self.sizes()],
            "rows": [[int(s) for s in r.sizes()] for r in self.rows],
            "views": [f.viewport.view for f in self.frames],
        }

    def restore_state(self, state: dict) -> None:
        try:
            self.setSizes(state["outer"])
            for row, sizes in zip(self.rows, state["rows"]):
                row.setSizes(sizes)
            for frame, view in zip(self.frames, state["views"]):
                if view in VIEW_TITLES:
                    frame.set_view(view)
        except (KeyError, TypeError, ValueError):
            pass
