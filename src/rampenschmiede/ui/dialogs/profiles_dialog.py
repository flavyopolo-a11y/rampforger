"""Spielprofile verwalten: automatisch finden, prüfen, von Hand anpassen."""
from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.profiles import KNOWN_GAMES, GameProfile, ProfileStore, detect_profiles


class _PathEdit(QWidget):
    def __init__(self, directory: bool, caption: str, file_filter: str = "", parent=None) -> None:
        super().__init__(parent)
        self.directory = directory
        self.caption = caption
        self.file_filter = file_filter
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        lay.addWidget(self.edit, 1)
        b = QPushButton("…")
        b.setFixedWidth(32)
        b.clicked.connect(self._browse)
        lay.addWidget(b)

    def _browse(self) -> None:
        start = self.edit.text() or str(Path.home())
        if self.directory:
            path = QFileDialog.getExistingDirectory(self, self.caption, start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, self.caption, start, self.file_filter)
        if path:
            self.edit.setText(str(Path(path)))
            self.edit.editingFinished.emit()

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, text: str) -> None:
        self.edit.setText(text)


class ProfilesDialog(QDialog):
    def __init__(self, store: ProfileStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Spielprofile"))
        self.resize(900, 560)
        self.store = copy.deepcopy(store)
        self._current = -1
        self._loading = False

        root = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        left.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.btn_detect = QPushButton(self.tr("Automatisch suchen"))
        self.btn_detect.setToolTip(self.tr("Sucht CS:S und Momentum Mod in allen Steam-Bibliotheken"))
        self.btn_detect.clicked.connect(self.detect)
        row.addWidget(self.btn_detect)
        b_add = QPushButton(self.tr("Neu"))
        b_add.clicked.connect(self.add_profile)
        row.addWidget(b_add)
        self.btn_remove = QPushButton(self.tr("Entfernen"))
        self.btn_remove.clicked.connect(self.remove_profile)
        row.addWidget(self.btn_remove)
        left.addLayout(row)
        self.info = QLabel()
        self.info.setWordWrap(True)
        left.addWidget(self.info)
        root.addLayout(left, 1)

        right = QVBoxLayout()
        self.form_widget = QWidget()
        form = QFormLayout(self.form_widget)
        self.f_name = QLineEdit()
        self.f_kind = QComboBox()
        for spec in KNOWN_GAMES.values():
            self.f_kind.addItem(spec.name, spec.key)
        self.f_kind.addItem(self.tr("Anderes Source-Spiel"), "custom")
        self.f_game = _PathEdit(True, self.tr("Spielordner (mit gameinfo.txt)"))
        self.f_bin = _PathEdit(True, self.tr("Ordner mit vbsp.exe"))
        self.f_exe = _PathEdit(False, self.tr("Spiel-Exe"), "Programme (*.exe);;Alle Dateien (*)")
        self.f_steam = _PathEdit(False, self.tr("Steam"), "steam.exe (steam.exe);;Alle Dateien (*)")
        self.f_appid = QSpinBox()
        self.f_appid.setRange(0, 99_999_999)
        self.f_via_steam = QCheckBox(self.tr("Über Steam starten (empfohlen)"))
        self.f_args = QLineEdit()
        self.f_fgds = QPlainTextEdit()
        self.f_fgds.setPlaceholderText(self.tr("Eine FGD-Datei pro Zeile"))
        self.f_fgds.setFixedHeight(70)
        form.addRow(self.tr("Name"), self.f_name)
        form.addRow(self.tr("Spiel"), self.f_kind)
        form.addRow(self.tr("Spielordner"), self.f_game)
        form.addRow(self.tr("Compiler (bin)"), self.f_bin)
        form.addRow(self.tr("Spiel-Exe"), self.f_exe)
        form.addRow(self.tr("Steam"), self.f_steam)
        form.addRow(self.tr("Steam-App-ID"), self.f_appid)
        form.addRow("", self.f_via_steam)
        form.addRow(self.tr("Startparameter"), self.f_args)
        form.addRow(self.tr("FGD-Dateien"), self.f_fgds)
        right.addWidget(self.form_widget)
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setTextFormat(Qt.RichText)
        right.addWidget(self.problems)
        right.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)
        root.addLayout(right, 2)

        for w in (self.f_name, self.f_args):
            w.editingFinished.connect(self._store_form)
        for pe in (self.f_game, self.f_bin, self.f_exe, self.f_steam):
            pe.edit.editingFinished.connect(self._store_form)
        self.f_kind.currentIndexChanged.connect(self._store_form)
        self.f_appid.valueChanged.connect(self._store_form)
        self.f_via_steam.toggled.connect(self._store_form)
        self.f_fgds.textChanged.connect(self._store_form)

        self._fill_list()
        active = self.store.active_profile()
        self.list.setCurrentRow(self.store.profiles.index(active) if active else -1)
        self._update_enabled()

    # ---- Liste ---------------------------------------------------------------------------
    def _fill_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for p in self.store.profiles:
            ok = not p.problems()
            mark = "✓" if ok else "⚠"
            label = f"{mark}  {p.name}"
            if p.name == self.store.active:
                label += self.tr("  (aktiv)")
            self.list.addItem(label)
        self.list.blockSignals(False)

    def _refresh_list_keep_row(self) -> None:
        row = self.list.currentRow()
        self._fill_list()
        self.list.blockSignals(True)
        self.list.setCurrentRow(row)
        self.list.blockSignals(False)

    def _update_enabled(self) -> None:
        has = 0 <= self._current < len(self.store.profiles)
        self.form_widget.setEnabled(has)
        self.btn_remove.setEnabled(has)
        if not has:
            self.problems.setText(self.tr(
                "Noch kein Spielprofil. „Automatisch suchen“ findet installierte Spiele, "
                "„Neu“ legt eines von Hand an."))

    def _select(self, row: int) -> None:
        self._current = row
        self._update_enabled()
        if 0 <= row < len(self.store.profiles):
            self._load_form(self.store.profiles[row])
            self.store.active = self.store.profiles[row].name
            self._refresh_list_keep_row()

    def detect(self) -> int:
        added = self.store.merge_detected(detect_profiles())
        self._fill_list()
        if self.store.profiles and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        if added:
            self.info.setText(self.tr("{0} Spiel(e) gefunden.").format(added))
        elif not self.store.profiles:
            self.info.setText(self.tr(
                "Kein unterstütztes Spiel gefunden. Lege ein Profil mit „Neu“ an und trage die Pfade ein."))
        else:
            self.info.setText(self.tr("Keine neuen Spiele gefunden."))
        return added

    def add_profile(self) -> None:
        names = {p.name for p in self.store.profiles}
        name, n = self.tr("Neues Profil"), 2
        while name in names:
            name = self.tr("Neues Profil {0}").format(n)
            n += 1
        self.store.profiles.append(GameProfile(key="custom", name=name, launch_via_steam=False))
        self._fill_list()
        self.list.setCurrentRow(len(self.store.profiles) - 1)

    def remove_profile(self) -> None:
        if 0 <= self._current < len(self.store.profiles):
            removed = self.store.profiles.pop(self._current)
            if self.store.active == removed.name:
                self.store.active = self.store.profiles[0].name if self.store.profiles else ""
            self._current = -1
            self._fill_list()
            self.list.setCurrentRow(min(len(self.store.profiles) - 1, 0) if self.store.profiles else -1)
            self._update_enabled()

    # ---- Formular -----------------------------------------------------------------------
    def _load_form(self, p: GameProfile) -> None:
        self._loading = True
        self.f_name.setText(p.name)
        i = self.f_kind.findData(p.key)
        self.f_kind.setCurrentIndex(i if i >= 0 else self.f_kind.count() - 1)
        self.f_game.setText(p.game_dir)
        self.f_bin.setText(p.bin_dir)
        self.f_exe.setText(p.game_exe)
        self.f_steam.setText(p.steam_exe)
        self.f_appid.setValue(p.app_id)
        self.f_via_steam.setChecked(p.launch_via_steam)
        self.f_args.setText(p.launch_args)
        self.f_fgds.setPlainText("\n".join(p.fgds))
        self._loading = False
        self._show_problems(p)

    def _store_form(self, *_args) -> None:
        if self._loading or not (0 <= self._current < len(self.store.profiles)):
            return
        p = self.store.profiles[self._current]
        old_name = p.name
        new_name = self.f_name.text().strip() or old_name
        if new_name != old_name and any(o.name == new_name for o in self.store.profiles):
            new_name = old_name  # Namen müssen eindeutig bleiben
            self.f_name.setText(old_name)
        p.name = new_name
        if self.store.active == old_name:
            self.store.active = new_name
        p.key = self.f_kind.currentData()
        p.game_dir = self.f_game.text()
        p.bin_dir = self.f_bin.text()
        p.game_exe = self.f_exe.text()
        p.steam_exe = self.f_steam.text()
        p.app_id = self.f_appid.value()
        p.launch_via_steam = self.f_via_steam.isChecked()
        p.launch_args = self.f_args.text().strip()
        p.fgds = [line.strip() for line in self.f_fgds.toPlainText().splitlines() if line.strip()]
        self._show_problems(p)
        self._refresh_list_keep_row()

    def _show_problems(self, p: GameProfile) -> None:
        probs = p.problems()
        if probs:
            items = "".join(f"<li>{self.tr(x)}</li>" for x in probs)
            self.problems.setText(f'<span style="color:#f0c85a">{self.tr("Noch nicht bereit:")}</span><ul>{items}</ul>')
        else:
            self.problems.setText(f'<span style="color:#7fd67f">{self.tr("Bereit zum Kompilieren und Testen.")}</span>')

    def result_store(self) -> ProfileStore:
        return self.store
