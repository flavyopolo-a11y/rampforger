"""Eingabefeld für ein Material: Vorschau, Name und ein Knopf „Aktuelles übernehmen“."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from ...core.materials import normalize
from ...render.scene_mesh import material_color

SWATCH = 22


def material_pixmap(editor, name: str, size: int = SWATCH) -> QPixmap:
    lib = editor.materials if editor is not None else None
    tex = lib.texture(name) if lib is not None else None
    if tex is not None:
        img = QImage(tex.rgba, tex.width, tex.height, tex.width * 4, QImage.Format_RGBA8888)
        return QPixmap.fromImage(img.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    r, g, b = material_color(name)
    pix = QPixmap(size, size)
    pix.fill(QColor(int(r * 255), int(g * 255), int(b * 255)))
    return pix


class MaterialField(QWidget):
    changed = Signal()

    def __init__(self, editor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        self._value = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.swatch = QLabel()
        self.swatch.setFixedSize(SWATCH, SWATCH)
        self.name = QLabel()
        self.name.setMinimumWidth(40)
        self.pick = QToolButton()
        self.pick.setText("⇐")
        self.pick.setToolTip(self.tr("Aktuelles Material aus dem Material-Browser übernehmen"))
        self.pick.clicked.connect(self._take_current)
        lay.addWidget(self.swatch)
        lay.addWidget(self.name, 1)
        lay.addWidget(self.pick)
        if editor is not None:
            editor.materials_changed.connect(self._refresh)

    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        self._value = str(value).upper()
        self._refresh()

    def _refresh(self) -> None:
        self.swatch.setPixmap(material_pixmap(self.editor, self._value))
        self.name.setText(normalize(self._value).rsplit("/", 1)[-1])
        self.setToolTip(self._value)

    def _take_current(self) -> None:
        if self.editor is not None and self.editor.current_material != self._value:
            self.set_value(self.editor.current_material)
            self.changed.emit()
