"""Modell wählen: alle Modelle des Spiels als Bildchen mit Suche und drehbarer Vorschau."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
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

from ...core.models.library import ModelLibrary, normalize_model
from ..panels.model_browser import THUMB, ModelListModel, ModelPreview, describe


class ModelDialog(QDialog):
    def __init__(self, library: ModelLibrary | None, current: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Modell wählen"))
        self.resize(880, 560)
        self.library = library
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(self.tr("Suchen, z. B. tree, rock, barrel …"))
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._refilter)
        row.addWidget(self.filter, 1)
        row.addWidget(QLabel(self.tr("Modell:")))
        self.name = QLineEdit(current)
        row.addWidget(self.name, 2)
        lay.addLayout(row)

        body = QHBoxLayout()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.names = library.names() if library is not None else []
        finally:
            QApplication.restoreOverrideCursor()
        self.model = ModelListModel(self)
        self.model.set_library(library)
        self.view = QListView()
        self.view.setViewMode(QListView.IconMode)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setIconSize(QSize(THUMB, THUMB))
        self.view.setGridSize(QSize(THUMB + 26, THUMB + 30))
        self.view.setUniformItemSizes(True)
        self.view.setWordWrap(True)
        self.view.setModel(self.model)
        self.view.selectionModel().currentChanged.connect(lambda cur, _p: self._pick(cur.data(Qt.UserRole)))
        self.view.doubleClicked.connect(lambda i: (self._pick(i.data(Qt.UserRole)), self.accept()))
        body.addWidget(self.view, 3)
        side = QVBoxLayout()
        self.preview = ModelPreview()
        side.addWidget(self.preview)
        self.info = QLabel()
        self.info.setWordWrap(True)
        side.addWidget(self.info)
        side.addStretch(1)
        body.addLayout(side, 1)
        lay.addLayout(body, 1)
        if not self.names:
            note = QLabel(self.tr("Keine Modelle gefunden. Ist ein Spielprofil mit CS:S oder HL2 eingerichtet? "
                                  "Den Pfad kannst du trotzdem eintragen."))
            note.setWordWrap(True)
            lay.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self.tr("Übernehmen"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._refilter()

    def _pick(self, name: str | None) -> None:
        if not name:
            return
        self.name.setText(name)
        model = self.library.load(name) if self.library is not None else None
        self.preview.show_model(self.library, model)
        self.info.setText(describe(model, name))

    def _refilter(self) -> None:
        words = self.filter.text().lower().split()
        names = [n for n in self.names if all(w in n for w in words)]
        self.model.set_names(names)
        current = normalize_model(self.name.text()) if self.name.text().strip() else ""
        row = self.model._rows.get(current)
        if row is not None:
            self.view.setCurrentIndex(self.model.index(row))

    def chosen(self) -> str:
        text = self.name.text().strip()
        return normalize_model(text) if text else ""
