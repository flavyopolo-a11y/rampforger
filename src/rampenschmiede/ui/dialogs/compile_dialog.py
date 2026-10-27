"""Kompilieren & Testen (F9): Profil und Voreinstellung wählen, Details im Experten-Modus."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from ...core.compile import (
    PRESETS,
    CompilePlan,
    CompileSettings,
    CopyFilesStep,
    CopyStep,
    LaunchStep,
    ToolStep,
    WriteStep,
    preset,
)
from ...core.profiles import ProfileStore


class CompileDialog(QDialog):
    #: Profil-Dialog öffnen; der Aufrufer liefert danach über set_store() den neuen Stand
    profiles_requested = Signal()

    def __init__(self, store: ProfileStore, settings: CompileSettings, preview, expert: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Kompilieren und testen"))
        self.resize(720, 620 if expert else 420)
        self._preview = preview  # (profil, einstellungen) -> CompilePlan
        self.settings = replace(settings)
        self.store = store
        self._loading = False

        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("Spiel")))
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._on_profile)
        row.addWidget(self.profile_combo, 1)
        b = QPushButton(self.tr("Profile …"))
        b.clicked.connect(self.profiles_requested.emit)
        row.addWidget(b)
        lay.addLayout(row)

        box = QGroupBox(self.tr("Qualität"))
        bl = QVBoxLayout(box)
        self.preset_group = QButtonGroup(self)
        self.preset_buttons: dict[str, QRadioButton] = {}
        for key, (label, desc, _) in PRESETS.items():
            rb = QRadioButton(f"{self.tr(label)} – {self.tr(desc)}")
            self.preset_group.addButton(rb)
            self.preset_buttons[key] = rb
            rb.toggled.connect(lambda on, k=key: on and self._apply_preset(k))
            bl.addWidget(rb)
        lay.addWidget(box)

        opts = QHBoxLayout()
        self.c_copy = QCheckBox(self.tr("BSP in den maps-Ordner kopieren"))
        self.c_launch = QCheckBox(self.tr("Spiel starten"))
        self.c_leak = QCheckBox(self.tr("Bei Leck abbrechen"))
        self.c_cubemaps = QCheckBox(self.tr("Cubemaps bauen"))
        self.c_cubemaps.setToolTip(self.tr(
            "Startet das Spiel mit -buildcubemaps: Es baut die Spiegelungen aller env_cubemap in die BSP und "
            "schließt sich danach. Nötig für glänzende Materialien, sobald das Licht fertig ist."))
        for c in (self.c_copy, self.c_launch, self.c_leak, self.c_cubemaps):
            c.toggled.connect(self._store)
            opts.addWidget(c)
        lay.addLayout(opts)

        self.expert_box = QGroupBox(self.tr("Details (Experten-Modus)"))
        form = QFormLayout(self.expert_box)
        self.c_vbsp = QCheckBox("VBSP")
        self.c_vvis = QCheckBox("VVIS")
        self.c_vrad = QCheckBox("VRAD")
        self.e_vbsp = QLineEdit()
        self.e_vvis = QLineEdit()
        self.e_vrad = QLineEdit()
        self.e_launch = QLineEdit()
        for check, edit in ((self.c_vbsp, self.e_vbsp), (self.c_vvis, self.e_vvis), (self.c_vrad, self.e_vrad)):
            h = QHBoxLayout()
            h.addWidget(edit, 1)
            form.addRow(check, h)
            check.toggled.connect(self._store)
            edit.textEdited.connect(self._store)
        form.addRow(self.tr("Zusätzliche Startparameter"), self.e_launch)
        self.e_launch.textEdited.connect(self._store)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFixedHeight(120)
        form.addRow(self.tr("Befehle"), self.preview)
        lay.addWidget(self.expert_box)
        self.expert_box.setVisible(expert)

        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.setTextFormat(Qt.RichText)
        lay.addWidget(self.problems)
        lay.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.btn_run = buttons.addButton(self.tr("Kompilieren"), QDialogButtonBox.AcceptRole)
        self.btn_run.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.set_store(store)
        self._load_settings()

    # ---- Profile ----------------------------------------------------------------------------
    def set_store(self, store: ProfileStore) -> None:
        self.store = store
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in store.profiles:
            self.profile_combo.addItem(p.name)
        active = store.active_profile()
        if active is not None:
            self.profile_combo.setCurrentIndex(store.profiles.index(active))
        self.profile_combo.blockSignals(False)
        self._update_preview()

    def _on_profile(self, index: int) -> None:
        if 0 <= index < len(self.store.profiles):
            self.store.active = self.store.profiles[index].name
        self._update_preview()

    def profile(self):
        i = self.profile_combo.currentIndex()
        return self.store.profiles[i] if 0 <= i < len(self.store.profiles) else None

    # ---- Einstellungen ------------------------------------------------------------------------
    def _apply_preset(self, key: str) -> None:
        if self._loading:
            return
        keep = self.settings
        self.settings = replace(preset(key), copy_to_game=keep.copy_to_game, launch_game=keep.launch_game,
                                stop_on_leak=keep.stop_on_leak, extra_launch_args=keep.extra_launch_args,
                                build_cubemaps=keep.build_cubemaps)
        self._load_settings()

    def _load_settings(self) -> None:
        self._loading = True
        s = self.settings
        btn = self.preset_buttons.get(s.preset)
        if btn is not None:
            btn.setChecked(True)
        else:
            self.preset_group.setExclusive(False)
            for b in self.preset_buttons.values():
                b.setChecked(False)
            self.preset_group.setExclusive(True)
        self.c_copy.setChecked(s.copy_to_game)
        self.c_launch.setChecked(s.launch_game)
        self.c_leak.setChecked(s.stop_on_leak)
        self.c_cubemaps.setChecked(s.build_cubemaps)
        self.c_cubemaps.setEnabled(s.launch_game)
        self.c_vbsp.setChecked(s.run_vbsp)
        self.c_vvis.setChecked(s.run_vvis)
        self.c_vrad.setChecked(s.run_vrad)
        self.e_vbsp.setText(s.vbsp_args)
        self.e_vvis.setText(s.vvis_args)
        self.e_vrad.setText(s.vrad_args)
        self.e_launch.setText(s.extra_launch_args)
        self._loading = False
        self._update_preview()

    def _store(self, *_args) -> None:
        if self._loading:
            return
        s = self.settings
        new = replace(
            s, copy_to_game=self.c_copy.isChecked(), launch_game=self.c_launch.isChecked(),
            stop_on_leak=self.c_leak.isChecked(), build_cubemaps=self.c_cubemaps.isChecked(),
            run_vbsp=self.c_vbsp.isChecked(),
            run_vvis=self.c_vvis.isChecked(), run_vrad=self.c_vrad.isChecked(),
            vbsp_args=self.e_vbsp.text(), vvis_args=self.e_vvis.text(), vrad_args=self.e_vrad.text(),
            extra_launch_args=self.e_launch.text(),
        )
        # Eigene Werte bei den Compilern machen aus der Voreinstellung "Eigene"
        base = PRESETS.get(s.preset)
        if base is not None:
            b = base[2]
            if (new.run_vbsp, new.run_vvis, new.run_vrad, new.vbsp_args, new.vvis_args, new.vrad_args) != (
                    b.run_vbsp, b.run_vvis, b.run_vrad, b.vbsp_args, b.vvis_args, b.vrad_args):
                new = replace(new, preset="custom")
                self._loading = True
                self.preset_group.setExclusive(False)
                for btn in self.preset_buttons.values():
                    btn.setChecked(False)
                self.preset_group.setExclusive(True)
                self._loading = False
        self.settings = new
        self.c_cubemaps.setEnabled(new.launch_game)
        self._update_preview()

    # ---- Vorschau ---------------------------------------------------------------------------
    def _update_preview(self) -> None:
        prof = self.profile()
        if prof is None:
            self.problems.setText(f'<span style="color:#f0c85a">{self.tr("Kein Spielprofil. Über „Profile …“ anlegen oder suchen lassen.")}</span>')
            self.btn_run.setEnabled(False)
            self.preview.setPlainText("")
            return
        plan: CompilePlan = self._preview(prof, self.settings)
        lines = []
        for step in plan.steps:
            if isinstance(step, (ToolStep, LaunchStep)):
                lines.append(step.command_line())
            elif isinstance(step, CopyStep):
                lines.append(f"copy {step.source} -> {step.target}")
            elif isinstance(step, CopyFilesStep):
                lines.append(f"{step.label}: {len(step.files)} Dateien")
            elif isinstance(step, WriteStep):
                lines += [f"{step.label} -> {t}" for t in step.targets]
        self.preview.setPlainText("\n".join(lines))
        if plan.problems:
            items = "".join(f"<li>{p}</li>" for p in plan.problems)
            self.problems.setText(f'<span style="color:#ff6e64">{self.tr("So geht es noch nicht:")}</span><ul>{items}</ul>')
        else:
            self.problems.setText(self.tr("Map: {0}  ·  Ziel: {1}").format(plan.map_name, prof.game_dir))
        self.btn_run.setEnabled(not plan.problems)
