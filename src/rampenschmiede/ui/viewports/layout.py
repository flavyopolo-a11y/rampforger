"""Vier Ansichten im 2x2-Raster mit verschiebbaren Trennern. Jede Ansicht kann über
ihre Kopfzeile auf 3D, Oben, Vorne oder Seite umgestellt werden (wie in Hammer)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...render.scene_mesh import is_translucent
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
        self.mode_combo.setItemData(list(RENDER_MODES).index("lightmap"), self.tr(
            "Ein Kästchen = ein Lichtpunkt der Lightmap. Rot: fein (schöne Schatten, kostet Speicher), "
            "grau: Standard 16, blau: grob (spart Speicher). Dunkel: Flächen ohne Lightmap. "
            "Ändern im Textur-Werkzeug unter Lightmap-Skalierung."), Qt.ToolTipRole)
        self.mode_combo.currentIndexChanged.connect(self._on_mode)
        self.trigger_button = QToolButton()
        self.trigger_button.setText(self.tr("Trigger"))
        self.trigger_button.setCheckable(True)
        self.trigger_button.setChecked(editor.show_triggers_3d)
        self.trigger_button.setToolTip(self.tr(
            "Trigger und Zonen in 3D halbdurchsichtig zeigen. Aus: nur ihr Umriss bleibt, anklicken geht nicht, "
            "damit man ungestört an Rampen arbeitet"))
        self.trigger_button.toggled.connect(self._on_triggers)
        hl.addWidget(self.view_combo)
        hl.addWidget(self.mode_combo)
        hl.addWidget(self.trigger_button)
        hl.addStretch(1)
        lay.addWidget(header)
        lay.addWidget(self.viewport, 1)
        self.mode_combo.setVisible(view == "3d")
        self.trigger_button.setVisible(view == "3d")
        self.active = False
        self.set_active(False)

    def set_active(self, on: bool) -> None:
        self.active = on
        self.setStyleSheet(ACTIVE_STYLE if on else INACTIVE_STYLE)

    def _on_view(self, _: int) -> None:
        view = self.view_combo.currentData()
        self.viewport.set_view(view)
        self.mode_combo.setVisible(view == "3d")
        self.trigger_button.setVisible(view == "3d")

    def _on_triggers(self, on: bool) -> None:
        self.viewport.editor.show_triggers_3d = on
        if not on:
            self.viewport.editor.set_selection([i for i in self.viewport.editor.selection
                                                if not _is_trigger(self.viewport.editor, i)])
        # alle 3D-Ansichten neu zeichnen
        for w in self.window().findChildren(ViewportFrame):
            if w.trigger_button.isChecked() != on:
                w.trigger_button.blockSignals(True)
                w.trigger_button.setChecked(on)
                w.trigger_button.blockSignals(False)
            w.viewport.update()

    def _on_mode(self, _: int) -> None:
        self.viewport.render_mode = self.mode_combo.currentData()
        self.viewport.update()

    def set_view(self, view: str) -> None:
        self.view_combo.setCurrentIndex(list(VIEW_TITLES).index(view))


def _is_trigger(editor: EditorContext, oid: int) -> bool:
    obj = editor.doc.get(oid)
    if obj is None:
        return False
    return any(is_translucent(s) for s in [obj, *editor.doc.children(oid)])


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
