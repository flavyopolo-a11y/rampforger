"""Transformieren (Strg+M): Verschieben, Drehen und Skalieren mit exakten Zahlen."""
from __future__ import annotations

import math

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..editor import EditorContext


class TransformDialog(QDialog):
    def __init__(self, editor: EditorContext, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.setWindowTitle(self.tr("Transformieren"))
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        move = QWidget()
        f = QFormLayout(move)
        self.move = []
        row = QHBoxLayout()
        for axis in "XYZ":
            s = QSpinBox()
            s.setRange(-65536, 65536)
            s.setPrefix(f"{axis} ")
            row.addWidget(s)
            self.move.append(s)
        f.addRow(self.tr("Verschieben um"), row)
        self.tabs.addTab(move, self.tr("Verschieben"))

        rot = QWidget()
        f = QFormLayout(rot)
        self.rot_axis = QComboBox()
        for i, name in enumerate(("X", "Y", "Z")):
            self.rot_axis.addItem(self.tr("um {0}").format(name), i)
        self.rot_axis.setCurrentIndex(2)
        self.rot_angle = QDoubleSpinBox()
        self.rot_angle.setRange(-360, 360)
        self.rot_angle.setDecimals(2)
        self.rot_angle.setSuffix("°")
        f.addRow(self.tr("Achse"), self.rot_axis)
        f.addRow(self.tr("Winkel"), self.rot_angle)
        self.tabs.addTab(rot, self.tr("Drehen"))

        sc = QWidget()
        f = QFormLayout(sc)
        self.scale = []
        row = QHBoxLayout()
        for axis in "XYZ":
            s = QDoubleSpinBox()
            s.setRange(1, 10000)
            s.setValue(100)
            s.setSuffix(" %")
            s.setPrefix(f"{axis} ")
            row.addWidget(s)
            self.scale.append(s)
        f.addRow(self.tr("Skalieren auf"), row)
        self.tabs.addTab(sc, self.tr("Skalieren"))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def apply(self) -> bool:
        bb = self.editor.selection_bbox()
        if bb is None:
            return False
        pivot = tuple(math.floor(c + 0.5) for c in bb.center)
        tab = self.tabs.currentIndex()
        if tab == 0:
            delta = tuple(s.value() for s in self.move)
            ok = any(delta) and self.editor.move_selection(delta)  # type: ignore[arg-type]
        elif tab == 1:
            angle = self.rot_angle.value()
            ok = bool(angle) and self.editor.rotate_selection(pivot, self.rot_axis.currentData(), angle)  # type: ignore[arg-type]
        else:
            factors = tuple(s.value() / 100 for s in self.scale)
            ok = self.editor.scale_selection(pivot, factors)  # type: ignore[arg-type]
        self.editor.stack.end_merge()
        return bool(ok)
