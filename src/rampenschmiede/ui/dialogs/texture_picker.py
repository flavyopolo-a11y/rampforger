"""Textur wählen: alle Texturen des Spiels und die eigenen, mit Suche (für die Rampen im Easy Mode).

Der Index der Texturen wird im Hintergrund geladen, wie im Material-Browser, damit das Fenster
auch bei zehntausenden Materialien sofort aufgeht.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QVBoxLayout,
)

from ...core.materials import MaterialLibrary
from ...i18n import N_
from ..panels.material_browser import THUMB, MaterialModel, _Bridge, _IndexJob

FILTERS = (("all", N_("Alle Texturen")), ("own", N_("Eigene Texturen")))


class TexturePicker(QDialog):
    def __init__(self, library: MaterialLibrary | None, current: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Textur für die Rampen wählen"))
        self.resize(760, 560)
        self.library = library
        self._all: list[str] = []
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Suchen … (z. B. metal, glass, concrete)"))
        self.search.setClearButtonEnabled(True)
        self.filter = QComboBox()
        for key, label in FILTERS:
            self.filter.addItem(self.tr(label), key)
        self.count = QLabel()
        self.count.setStyleSheet("color: #888;")
        top.addWidget(self.search, 1)
        top.addWidget(self.filter)
        top.addWidget(self.count)
        lay.addLayout(top)
        self.model = MaterialModel(self)
        self.model.set_library(library)
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setViewMode(QListView.IconMode)
        self.view.setIconSize(QSize(THUMB, THUMB))
        self.view.setGridSize(QSize(THUMB + 28, THUMB + 34))
        self.view.setUniformItemSizes(True)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setMovement(QListView.Static)
        self.view.setTextElideMode(Qt.ElideMiddle)
        lay.addWidget(self.view, 1)
        self.empty = QLabel(self.tr("Noch kein Spiel eingerichtet: Ohne Spiel gibt es nur deine eigenen Texturen. "
                                    "Richte Counter-Strike: Source oder Momentum Mod unter Spiel ein."))
        self.empty.setWordWrap(True)
        self.empty.setStyleSheet("color: #e85;")
        self.empty.setVisible(library is None or not library.has_game())
        lay.addWidget(self.empty)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.search.textChanged.connect(self._refilter)
        self.filter.currentIndexChanged.connect(self._refilter)
        self.view.doubleClicked.connect(lambda *_: self.accept())
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._update_ok())
        self._current = current.upper()
        self._bridge = _Bridge()
        self._bridge.index_ready.connect(self._on_index)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        if library is not None:
            self.count.setText(self.tr("lädt …"))
            self._pool.start(_IndexJob(library, self._bridge))
        self._update_ok()

    def _on_index(self, lib, names: list[str]) -> None:
        if lib is not self.library:
            return
        self._all = names
        self._refilter()

    def _refilter(self) -> None:
        if self.filter.currentData() == "own":
            base = self.library.own_names() if self.library else []
        else:
            base = self._all
        words = self.search.text().lower().split()
        if words:
            base = [n for n in base if all(w in n.lower() for w in words)]
        # Werkzeug-Texturen (Clip, Trigger, Skybox) sind keine Rampentexturen
        base = [n for n in base if not n.upper().startswith("TOOLS/")]
        self.model.set_names(base)
        self.count.setText(self.tr("{0} Texturen").format(len(base)))
        if self._current in (n.upper() for n in base):
            row = [n.upper() for n in base].index(self._current)
            self.view.setCurrentIndex(self.model.index(row))
        self._update_ok()

    def _update_ok(self) -> None:
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.chosen()))

    def chosen(self) -> str:
        index = self.view.currentIndex()
        return index.data(Qt.UserRole) if index.isValid() and self.view.selectionModel().isSelected(index) else ""


__all__ = ["TexturePicker"]
