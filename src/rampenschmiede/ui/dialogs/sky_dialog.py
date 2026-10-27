"""Himmel wählen: alle Skyboxen des Spiels als Bilder, Klick wählt, Doppelklick übernimmt."""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSize, Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QVBoxLayout,
)

from ...core.materials import MaterialLibrary
from ...render.sky import available_skies, sky_material
from ..panels.material_browser import MaterialModel

THUMB_SIZE = QSize(96, 96)


class SkyModel(MaterialModel):
    """Material-Vorschauen der Vorderseite (ft), beschriftet mit dem Himmelsnamen."""

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable if index.isValid() else Qt.NoItemFlags

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if index.isValid() and role in (Qt.DisplayRole, Qt.ToolTipRole, Qt.UserRole):
            return sky_name(self.names[index.row()])
        return super().data(index, role)


def sky_name(material: str) -> str:
    return material[len("skybox/"):-2]


class SkyDialog(QDialog):
    def __init__(self, library: MaterialLibrary | None, current: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Himmel"))
        self.resize(720, 520)
        lay = QVBoxLayout(self)
        intro = QLabel(self.tr(
            "Der Himmel ist überall zu sehen, wo Skybox-Flächen (tools/toolsskybox) sind. In den Ansichten "
            "„Texturiert“ und „Licht-Vorschau“ zeigt die 3D-Ansicht ihn so wie im Spiel."))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        row = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(self.tr("Suchen …"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._refilter)
        row.addWidget(self.filter, 1)
        row.addWidget(QLabel(self.tr("Name:")))
        self.name = QLineEdit(current)
        self.name.setToolTip(self.tr("skyname der Map. Eigene Himmel liegen als materials/skybox/<Name>rt.vmt usw. vor."))
        row.addWidget(self.name, 1)
        lay.addLayout(row)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.skies = available_skies(library)
        finally:
            QApplication.restoreOverrideCursor()
        self.model = SkyModel(self)
        self.model.set_library(library)
        self.view = QListView()
        self.view.setViewMode(QListView.IconMode)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setIconSize(THUMB_SIZE)
        self.view.setGridSize(QSize(THUMB_SIZE.width() + 40, THUMB_SIZE.height() + 34))
        self.view.setUniformItemSizes(True)
        self.view.setModel(self.model)
        self.view.clicked.connect(lambda i: self.name.setText(i.data(Qt.UserRole)))
        self.view.doubleClicked.connect(lambda i: (self.name.setText(i.data(Qt.UserRole)), self.accept()))
        lay.addWidget(self.view, 1)
        if not self.skies:
            note = QLabel(self.tr("Keine Himmel gefunden. Ist ein Spielprofil mit CS:S oder HL2 eingerichtet? "
                                  "Den Namen kannst du trotzdem eintragen."))
            note.setWordWrap(True)
            lay.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self.tr("Übernehmen"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._refilter()

    def _refilter(self) -> None:
        words = self.filter.text().lower().split()
        names = [s for s in self.skies if all(w in s.lower() for w in words)]
        self.model.set_names([sky_material(s, "ft") for s in names])
        current = self.name.text().strip().lower()
        for row, s in enumerate(names):
            if s.lower() == current:
                self.view.setCurrentIndex(self.model.index(row))
                break

    def chosen(self) -> str:
        return self.name.text().strip()
