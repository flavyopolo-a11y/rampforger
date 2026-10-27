"""Schalter „Alle Rampen | Nur diese Rampe“: Gilt eine Textur auf einer Rampe für alle Rampen
oder nur für die eine? Steht gut sichtbar überall, wo man Rampen texturiert, und alle
Schalter zeigen denselben Zustand (er liegt im Editor)."""
from __future__ import annotations

from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QWidget

from ...core.materials.apply import SCOPE_ALL, SCOPE_ONE
from ..icons import ACTIVE

SCOPES = ((SCOPE_ALL, "Alle Rampen"), (SCOPE_ONE, "Nur diese Rampe"))
STYLE = (f"QPushButton {{ padding: 3px 10px; }} QPushButton:checked {{ background: {ACTIVE}; color: #111; "
         "font-weight: bold; border: 1px solid #ffb070; }")


class ScopeSwitch(QWidget):
    def __init__(self, editor, label: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        if label:
            text = QLabel(self.tr("Textur gilt für:"))
            text.setStyleSheet("padding-right: 6px;")
            lay.addWidget(text)
        self.group = QButtonGroup(self)
        self.buttons: dict[str, QPushButton] = {}
        for key, title in SCOPES:
            b = QPushButton(self.tr(title))
            b.setCheckable(True)
            b.setStyleSheet(STYLE)
            b.setToolTip(self.tr(
                "Alle Rampen: Eine Textur auf der Surf-Fläche oder den Seiten einer Rampe gilt für alle Rampen "
                "und für neue. Nur diese Rampe: nur die eine, auf die du sie legst."))
            self.group.addButton(b)
            self.buttons[key] = b
            b.clicked.connect(lambda _=False, k=key: editor.set_material_scope(k))
            lay.addWidget(b)
        editor.material_scope_changed.connect(self._show)
        self._show(editor.material_scope)

    def _show(self, key: str) -> None:
        b = self.buttons.get(key)
        if b is not None and not b.isChecked():
            b.setChecked(True)

    def scope(self) -> str:
        return next(k for k, b in self.buttons.items() if b.isChecked())
