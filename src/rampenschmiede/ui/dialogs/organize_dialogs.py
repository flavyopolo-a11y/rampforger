"""Dialoge zum Ordnen: An Entity binden (Strg+T) und Mehrfach kopieren (Strg+Shift+V)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from ...core.organize import COMMON_BRUSH_CLASSES


def _buttons(dlg: QDialog) -> QDialogButtonBox:
    b = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    b.accepted.connect(dlg.accept)
    b.rejected.connect(dlg.reject)
    return b


class TieEntityDialog(QDialog):
    """Welche Brush-Entity sollen die Brushes werden? Häufige zuerst, dann alle aus dem Katalog."""

    def __init__(self, solid_classes: list[str], current: str = "func_detail", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("An Entity binden"))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(self.tr("Die ausgewählten Brushes werden zu einer Brush-Entity.\n"
                                     "Trigger bekommen automatisch die Trigger-Textur.")))
        self.classname = QComboBox()
        self.classname.setEditable(True)
        names = list(COMMON_BRUSH_CLASSES)
        names += [n for n in solid_classes if n not in COMMON_BRUSH_CLASSES and n != "worldspawn"]
        self.classname.addItems(names)
        self.classname.setCurrentText(current)
        f = QFormLayout()
        f.addRow(self.tr("Klasse"), self.classname)
        lay.addLayout(f)
        lay.addWidget(_buttons(self))

    def value(self) -> str:
        return self.classname.currentText().strip()


class MultiCopyDialog(QDialog):
    """Mehrfach kopieren wie „Paste Special“ in Hammer: Anzahl, Versatz und Drehung je Kopie."""

    def __init__(self, size: tuple[float, float, float] = (64, 0, 0), parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Mehrfach kopieren"))
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.count = QSpinBox()
        self.count.setRange(1, 256)
        self.count.setValue(4)
        f.addRow(self.tr("Anzahl Kopien"), self.count)
        self.offset = self._row(f, self.tr("Versatz je Kopie"), (size[0], 0, 0), 65536, 0, "")
        self.rotation = self._row(f, self.tr("Drehung je Kopie"), (0, 0, 0), 360, 2, "°")
        self.group = QCheckBox(self.tr("Kopien als Gruppe"))
        f.addRow("", self.group)
        lay.addLayout(f)
        lay.addWidget(QLabel(self.tr("Tipp: Drehung um Z mit Versatz in Z ergibt eine Wendeltreppe.")))
        lay.addWidget(_buttons(self))

    @staticmethod
    def _row(f: QFormLayout, label: str, values, limit: float, decimals: int, suffix: str) -> list[QDoubleSpinBox]:
        row = QHBoxLayout()
        spins = []
        for axis, v in zip("XYZ", values):
            s = QDoubleSpinBox()
            s.setRange(-limit, limit)
            s.setDecimals(decimals)
            s.setPrefix(f"{axis} ")
            s.setSuffix(suffix)
            s.setValue(v)
            row.addWidget(s)
            spins.append(s)
        f.addRow(label, row)
        return spins

    def values(self) -> dict:
        return {
            "count": self.count.value(),
            "offset": tuple(s.value() for s in self.offset),
            "rotation": tuple(s.value() for s in self.rotation),
            "make_group": self.group.isChecked(),
        }
