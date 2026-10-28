"""Sound-Browser: alle Sounds des Spiels mit Suche, Ordnern und Abspielen. Aus den
Entity-Eigenschaften (z. B. `message` bei ambient_generic) übernimmt „Wählen“ den Namen."""
from __future__ import annotations

import re

from PySide6.QtCore import QSortFilterProxyModel, QStringListModel, Qt, QUrl
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from ...core.sounds import SoundLibrary, normalize
from ..icons import icon
from ..paths import data_dir


def _player():
    """QMediaPlayer mit Ausgabe; None, wenn Qt Multimedia fehlt (z. B. ohne Audio-Gerät)."""
    try:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    except ImportError:  # pragma: no cover - hängt von der Qt-Installation ab
        return None, None
    player = QMediaPlayer()
    out = QAudioOutput()
    player.setAudioOutput(out)
    return player, out


class SoundBrowser(QDialog):
    def __init__(self, library: SoundLibrary, current: str = "", parent=None, choose: bool = True) -> None:
        super().__init__(parent)
        self.library = library
        self.setWindowTitle(self.tr("Sounds"))
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Suchen … (z. B. wind, door, button)"))
        self.search.setClearButtonEnabled(True)
        row.addWidget(self.search, 1)
        self.folder = QComboBox()
        self.folder.setMinimumWidth(160)
        row.addWidget(self.folder)
        lay.addLayout(row)

        names = library.names()
        self.model = QStringListModel(names, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.view = QListView()
        self.view.setModel(self.proxy)
        self.view.setUniformItemSizes(True)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.doubleClicked.connect(lambda _i: self.play())
        self.view.selectionModel().currentChanged.connect(lambda *_a: self._update())
        lay.addWidget(self.view, 1)

        self.folder.addItem(self.tr("Alle Ordner"), "")
        for f in sorted({n.split("/", 1)[0] for n in names if "/" in n}):
            self.folder.addItem(f, f)
        self.search.textChanged.connect(lambda _t: self._refilter())
        self.folder.currentIndexChanged.connect(lambda _i: self._refilter())

        controls = QHBoxLayout()
        self.play_btn = QPushButton(icon("play"), self.tr("Abspielen"))
        self.play_btn.clicked.connect(self.play)
        self.stop_btn = QPushButton(icon("stop"), self.tr("Stopp"))
        self.stop_btn.clicked.connect(self.stop)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(70)
        self.volume.setMaximumWidth(140)
        self.volume.setToolTip(self.tr("Lautstärke"))
        self.name = QLabel()
        self.name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.volume)
        controls.addWidget(self.name, 1)
        lay.addLayout(controls)
        self.count = QLabel()
        self.count.setStyleSheet("color: #9aa4b2;")
        lay.addWidget(self.count)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel if choose else QDialogButtonBox.Close)
        if choose:
            buttons.button(QDialogButtonBox.Ok).setText(self.tr("Wählen"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.player, self._audio = _player()
        if self._audio is not None:
            self.volume.valueChanged.connect(lambda v: self._audio.setVolume(v / 100))
            self._audio.setVolume(0.7)
        self.last_played: str | None = None
        self._refilter()
        if current:
            self.select(current)
        self._update()

    # ---- Liste -------------------------------------------------------------------------
    def _refilter(self) -> None:
        folder = self.folder.currentData() or ""
        text = self.search.text().strip()
        # Ordner und Suchtext als ein Ausdruck: Ordner am Anfang, Text irgendwo
        pattern = (f"^{re.escape(folder)}/" if folder else "") + (".*" + re.escape(text) if text else "")
        self.proxy.setFilterRegularExpression(pattern)
        self.count.setText(self.tr("{0} von {1} Sounds").format(self.proxy.rowCount(), self.model.rowCount()))
        if self.proxy.rowCount() and not self.view.currentIndex().isValid():
            self.view.setCurrentIndex(self.proxy.index(0, 0))

    def select(self, name: str) -> bool:
        n = normalize(name)
        rows = self.model.stringList()
        if n not in rows:
            return False
        idx = self.proxy.mapFromSource(self.model.index(rows.index(n), 0))
        if idx.isValid():
            self.view.setCurrentIndex(idx)
            self.view.scrollTo(idx, QListView.PositionAtCenter)
        return idx.isValid()

    def chosen(self) -> str:
        idx = self.view.currentIndex()
        return idx.data() if idx.isValid() else ""

    def _update(self) -> None:
        name = self.chosen()
        self.name.setText(name)
        self.play_btn.setEnabled(bool(name) and self.player is not None)

    # ---- Abspielen ---------------------------------------------------------------------
    def play(self) -> bool:
        name = self.chosen()
        if not name:
            return False
        path = self.library.extract(name, data_dir() / "cache" / "sounds")
        self.last_played = name
        if path is None or self.player is None:
            return False
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()
        return True

    def stop(self) -> None:
        if self.player is not None:
            self.player.stop()

    def done(self, result: int) -> None:
        self.stop()
        super().done(result)


__all__ = ["SoundBrowser"]
