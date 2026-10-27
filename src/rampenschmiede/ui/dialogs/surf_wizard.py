"""Assistent „Neue Surf-Map“: wenige Fragen, danach eine spielbare, dichte Map."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from ...core.surf.catalog import CATALOG
from ...core.templates import RAMP_KINDS, SurfMapSettings
from ...core.templates.surf_map import MAP_LIMIT, total_length

GAMES = (("css", "Counter-Strike: Source"), ("momentum", "Momentum Mod"), ("", "Beide (alle Spawns)"))


def _spin(lo: int, hi: int, value: int, step: int, suffix: str = " u") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(value)
    s.setSuffix(suffix)
    return s


class SurfWizard(QDialog):
    def __init__(self, game: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Neue Surf-Map"))
        lay = QVBoxLayout(self)
        intro = QLabel(self.tr(
            "Erzeugt eine lineare Surf-Map: Jede Stage hat eine Startplattform, Rampen, die nacheinander "
            "tiefer liegen, und einen Teleporter am Boden, der zurück zum Anfang der Stage bringt. "
            "Alles ist von einer dichten Skybox umhüllt und lässt sich sofort mit F9 testen. "
            "Rampen und Teleporter bleiben über ihre Regler änderbar."))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        d = SurfMapSettings()
        form = QFormLayout()
        self.game = QComboBox()
        for key, name in GAMES:
            self.game.addItem(self.tr(name), key)
        self.game.setCurrentIndex(max(0, self.game.findData(game or "")))
        self.stages = _spin(1, 12, d.stages, 1, "")
        self.ramps = _spin(1, 8, d.ramps_per_stage, 1, "")
        self.kind = QComboBox()
        for key in RAMP_KINDS:
            self.kind.addItem(self.tr(CATALOG[key].name), key)
        self.length = _spin(512, 8192, d.ramp_length, 256)
        self.width = _spin(256, 4096, d.ramp_width, 64)
        self.angle = QDoubleSpinBox()
        self.angle.setRange(45.5, 65)
        self.angle.setSingleStep(0.5)
        self.angle.setValue(d.angle)
        self.angle.setSuffix("°")
        self.gap = _spin(0, 2048, d.gap, 64)
        self.drop = _spin(0, 1024, d.drop, 32)
        form.addRow(self.tr("Spiel"), self.game)
        form.addRow(self.tr("Stages"), self.stages)
        form.addRow(self.tr("Rampen pro Stage"), self.ramps)
        form.addRow(self.tr("Rampenart"), self.kind)
        form.addRow(self.tr("Rampenlänge"), self.length)
        form.addRow(self.tr("Rampenbreite"), self.width)
        form.addRow(self.tr("Surf-Winkel"), self.angle)
        form.addRow(self.tr("Lücke zwischen Rampen"), self.gap)
        form.addRow(self.tr("Jede Rampe tiefer um"), self.drop)
        lay.addLayout(form)
        self.size_label = QLabel()
        self.size_label.setWordWrap(True)
        lay.addWidget(self.size_label)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText(self.tr("Map erzeugen"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        for w in (self.stages, self.ramps, self.length, self.gap):
            w.valueChanged.connect(self._update_size)
        self._update_size()

    def settings(self) -> SurfMapSettings:
        return SurfMapSettings(
            game=self.game.currentData() or None, stages=self.stages.value(), ramps_per_stage=self.ramps.value(),
            ramp_kind=self.kind.currentData(), ramp_length=self.length.value(), ramp_width=self.width.value(),
            angle=self.angle.value(), gap=self.gap.value(), drop=self.drop.value())

    def _update_size(self) -> None:
        length = total_length(self.settings())
        too_big = length + 1200 > 2 * MAP_LIMIT
        self.size_label.setText(self.tr("Länge der Strecke: {0} Units{1}").format(
            length, self.tr(" – zu lang für Source (höchstens {0})").format(2 * MAP_LIMIT) if too_big else ""))
        self.size_label.setStyleSheet("color: #d80; font-weight: bold;" if too_big else "")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(not too_big)
