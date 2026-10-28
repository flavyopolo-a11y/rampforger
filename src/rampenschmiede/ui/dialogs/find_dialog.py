"""Suchen und Ersetzen (Strg+F): Entities nach Klasse, Name oder Wert; Texturen mit Platzhaltern."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core import search
from ...i18n import N_

if TYPE_CHECKING:
    from ..main_window import MainWindow


class FindDialog(QDialog):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window_ = window
        self.setWindowTitle(self.tr("Suchen und Ersetzen"))
        self.setModal(False)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        # Entities
        ent = QWidget()
        f = QFormLayout(ent)
        self.ent_text = QLineEdit()
        self.ent_text.setPlaceholderText(self.tr("z. B. trigger_teleport, stage2_dest, door_*"))
        self.ent_field = QComboBox()
        for key, label in (("alle", N_("Klasse, Name und alle Werte")), ("klasse", N_("Klasse")), ("name", N_("Name"))):
            self.ent_field.addItem(self.tr(label), key)
        self.ent_whole = QCheckBox(self.tr("Ganzer Wert"))
        self.ent_new = QLineEdit()
        f.addRow(self.tr("Suchen"), self.ent_text)
        f.addRow(self.tr("in"), self.ent_field)
        f.addRow("", self.ent_whole)
        f.addRow(self.tr("Ersetzen durch"), self.ent_new)
        row = QHBoxLayout()
        b = QPushButton(self.tr("Alle auswählen"))
        b.clicked.connect(self.select_entities)
        row.addWidget(b)
        b = QPushButton(self.tr("Alle ersetzen"))
        b.clicked.connect(self.replace_entities)
        row.addWidget(b)
        f.addRow(row)
        self.tabs.addTab(ent, self.tr("Entities"))

        # Texturen
        tex = QWidget()
        f = QFormLayout(tex)
        self.tex_find = QComboBox()
        self.tex_find.setEditable(True)
        self.tex_new = QComboBox()
        self.tex_new.setEditable(True)
        self.tex_only_sel = QCheckBox(self.tr("Nur in der Auswahl"))
        f.addRow(self.tr("Textur"), self.tex_find)
        f.addRow("", QLabel(self.tr("Platzhalter: * und ?, z. B. concrete/*")))
        f.addRow(self.tr("Ersetzen durch"), self.tex_new)
        f.addRow("", self.tex_only_sel)
        row = QHBoxLayout()
        b = QPushButton(self.tr("Alle auswählen"))
        b.clicked.connect(self.select_textures)
        row.addWidget(b)
        b = QPushButton(self.tr("Ersetzen"))
        b.clicked.connect(self.replace_textures)
        row.addWidget(b)
        f.addRow(row)
        self.tabs.addTab(tex, self.tr("Texturen"))

        self.result = QLabel()
        lay.addWidget(self.result)

    def refresh(self) -> None:
        """Listen mit den Texturen der Map füllen; aktuelle Textur als Ersatz vorschlagen."""
        ed = self.window_.editor
        used = [m.lower() for m in search.used_materials(ed.doc)]
        keep = self.tex_find.currentText()
        self.tex_find.clear()
        self.tex_find.addItems(used)
        self.tex_find.setCurrentText(keep or (used[0] if used else ""))
        keep = self.tex_new.currentText()
        self.tex_new.clear()
        self.tex_new.addItems(used)
        self.tex_new.setCurrentText(keep or ed.current_material.lower())

    # ---- Entities ---------------------------------------------------------------------------
    def _ent_args(self) -> tuple[str, str, bool]:
        return self.ent_text.text().strip(), self.ent_field.currentData(), self.ent_whole.isChecked()

    def select_entities(self) -> list[int]:
        text, field, whole = self._ent_args()
        ids = search.find_entities(self.window_.editor.doc, text, field, whole)
        self._select(ids, self.tr("{0} Entities gefunden"))
        return ids

    def replace_entities(self) -> bool:
        text, field, whole = self._ent_args()
        ed = self.window_.editor
        ids = search.find_entities(ed.doc, text, field, whole)
        cmd = search.replace_in_entities(ed.doc, ids, text, self.ent_new.text(), field, whole)
        if cmd is None:
            self.result.setText(self.tr("Nichts zu ersetzen"))
            return False
        ed.run(cmd)
        self.result.setText(self.tr("In {0} Entities ersetzt").format(len(ids)))
        return True

    # ---- Texturen ---------------------------------------------------------------------------
    def _tex_scope(self) -> list[int] | None:
        return sorted(self.window_.editor.selection) if self.tex_only_sel.isChecked() else None

    def select_textures(self) -> list[int]:
        ed = self.window_.editor
        ids = search.find_material_users(ed.doc, self.tex_find.currentText(), self._tex_scope())
        self._select(ids, self.tr("{0} Objekte mit dieser Textur"))
        return ids

    def replace_textures(self) -> bool:
        ed = self.window_.editor
        cmd = search.replace_materials(ed.doc, self.tex_find.currentText(), self.tex_new.currentText(),
                                       self._tex_scope())
        if cmd is None:
            self.result.setText(self.tr("Keine passende Textur (Rampen-Bausteine: Textur in der Bibliothek ändern)"))
            return False
        ed.run(cmd)
        self.result.setText(self.tr("Textur ersetzt"))
        self.refresh()
        return True

    def _select(self, ids: list[int], message: str) -> None:
        ed = self.window_.editor
        ed.set_selection(ids)
        if ids:
            self.window_.center_on_selection()
        self.result.setText(message.format(len(ids)))
