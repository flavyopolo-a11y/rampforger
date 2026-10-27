"""Rampen-Assistent: zwei, drei Farben wählen, den Rest erledigt die Rampenschmiede.

Erzeugt passende Texturen (Rampe mit Linien, dunklere Rampenseiten, Wände mit Raster),
legt sie als eigene Materialien ab und färbt die Map in einem Undo-Schritt um. Neue Rampen
aus der Bibliothek übernehmen das Thema. Der Playerclip auf Rampen lässt sich hier mit
einem Haken an- und abschalten.
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
)

from ...core.materials.authoring import RGB, ramp_image, wall_image

#: Fertige Farbkombinationen: Name, Rampe, Linien, Wände
PRESETS: tuple[tuple[str, RGB, RGB, RGB], ...] = (
    ("Klassisch", (214, 218, 224), (47, 111, 214), (90, 95, 102)),
    ("Neon", (27, 27, 43), (255, 43, 214), (42, 36, 64)),
    ("Lava", (58, 26, 18), (255, 106, 26), (43, 37, 34)),
    ("Eis", (207, 233, 255), (74, 163, 255), (143, 167, 191)),
    ("Wald", (79, 122, 58), (232, 210, 122), (90, 74, 58)),
    ("Grau", (128, 128, 128), (32, 32, 32), (176, 176, 176)),
)

SIDE_SHADE = 0.7


def to_hex(c: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*c)


def from_hex(text: str, fallback: RGB) -> RGB:
    c = QColor(text)
    return (c.red(), c.green(), c.blue()) if c.isValid() else fallback


def side_color(ramp: RGB) -> RGB:
    """Rampenseiten etwas dunkler als die Fahrfläche, damit die Kante gut lesbar ist."""
    return tuple(round(v * SIDE_SHADE) for v in ramp)  # type: ignore[return-value]


def pil_pixmap(img: Image.Image, size: int | None = None) -> QPixmap:
    img = img.convert("RGBA")
    if size:
        img = img.resize((size, size), Image.Resampling.BILINEAR)
    qimg = QImage(img.tobytes("raw", "RGBA"), img.width, img.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


@dataclass
class AssistantChoice:
    ramp: RGB
    lines: RGB
    wall: RGB
    clip: bool = True
    walls: bool = True
    only_selection: bool = False
    remember: bool = True


class _ColorButton(QPushButton):
    changed = Signal()

    def __init__(self, color: RGB, title: str, parent=None) -> None:
        super().__init__(parent)
        self.title = title
        self.setMinimumWidth(130)
        self.clicked.connect(self._pick)
        self.set_color(color)

    def color(self) -> RGB:
        return self._color

    def set_color(self, color: RGB) -> None:
        self._color = tuple(int(v) for v in color)  # type: ignore[assignment]
        pix = QPixmap(18, 18)
        pix.fill(QColor(*self._color))
        self.setIcon(QIcon(pix))
        self.setText(to_hex(self._color))
        self.changed.emit()

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(*self._color), self, self.title)
        if c.isValid():
            self.set_color((c.red(), c.green(), c.blue()))


class RampAssistant(QDialog):
    def __init__(self, start: AssistantChoice | None = None, has_selection: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Rampen-Assistent"))
        start = start or AssistantChoice(*PRESETS[0][1:])
        lay = QVBoxLayout(self)
        intro = QLabel(self.tr(
            "Farben wählen, fertig. Die Rampenschmiede baut daraus passende Texturen für Rampen, "
            "Rampenseiten und Wände und färbt die Map um. Neue Rampen bekommen die Farben automatisch."))
        intro.setWordWrap(True)
        lay.addWidget(intro)

        presets = QHBoxLayout()
        presets.setSpacing(6)
        for name, ramp, lines, wall in PRESETS:
            b = QToolButton()
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIcon(QIcon(pil_pixmap(ramp_image(ramp, lines, 64))))
            b.setIconSize(pil_pixmap(ramp_image(ramp, lines, 64)).size())
            b.setText(self.tr(name))
            b.setToolTip(self.tr("Farben von „{0}“ übernehmen").format(self.tr(name)))
            b.clicked.connect(lambda _=False, r=ramp, li=lines, w=wall: self.set_colors(r, li, w))
            presets.addWidget(b)
        presets.addStretch(1)
        lay.addLayout(presets)

        body = QHBoxLayout()
        form = QFormLayout()
        self.ramp_btn = _ColorButton(start.ramp, self.tr("Farbe der Rampen"))
        self.lines_btn = _ColorButton(start.lines, self.tr("Farbe der Rampenlinien"))
        self.wall_btn = _ColorButton(start.wall, self.tr("Farbe der Wände"))
        form.addRow(self.tr("Rampen"), self.ramp_btn)
        form.addRow(self.tr("Rampenlinien"), self.lines_btn)
        form.addRow(self.tr("Wände und Böden"), self.wall_btn)
        body.addLayout(form, 1)
        self.preview = QLabel()
        self.preview.setFixedSize(200, 136)
        self.preview.setToolTip(self.tr("Vorschau: Rampe, Rampenseite und Wand"))
        body.addWidget(self.preview)
        lay.addLayout(body)
        for b in (self.ramp_btn, self.lines_btn, self.wall_btn):
            b.changed.connect(self._update_preview)

        self.clip = QCheckBox(self.tr("Playerclip auf Rampen (empfohlen, damit das Surfen glatt ist)"))
        self.clip.setChecked(start.clip)
        self.clip.setToolTip(self.tr(
            "An: Jede Rampe bekommt eine glatte Playerclip-Hülle über der sichtbaren Rampe (func_detail). "
            "Aus: Die Rampe selbst ist die Kollision (func_detail)."))
        self.walls = QCheckBox(self.tr("Wände, Böden und Bhop-Blöcke mitfärben"))
        self.walls.setChecked(start.walls)
        self.remember = QCheckBox(self.tr("Für neue Rampen merken"))
        self.remember.setChecked(start.remember)
        lay.addWidget(self.clip)
        lay.addWidget(self.walls)
        lay.addWidget(self.remember)

        scope = QHBoxLayout()
        self.whole = QRadioButton(self.tr("Ganze Map"))
        self.selection = QRadioButton(self.tr("Nur Auswahl"))
        self.selection.setEnabled(has_selection)
        (self.selection if has_selection and start.only_selection else self.whole).setChecked(True)
        scope.addWidget(QLabel(self.tr("Anwenden auf:")))
        scope.addWidget(self.whole)
        scope.addWidget(self.selection)
        scope.addStretch(1)
        lay.addLayout(scope)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self.tr("Anwenden"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self._update_preview()

    def set_colors(self, ramp: RGB, lines: RGB, wall: RGB) -> None:
        self.ramp_btn.set_color(ramp)
        self.lines_btn.set_color(lines)
        self.wall_btn.set_color(wall)

    def choice(self) -> AssistantChoice:
        return AssistantChoice(self.ramp_btn.color(), self.lines_btn.color(), self.wall_btn.color(),
                               clip=self.clip.isChecked(), walls=self.walls.isChecked(),
                               only_selection=self.selection.isChecked(), remember=self.remember.isChecked())

    def _update_preview(self) -> None:
        if not hasattr(self, "preview"):
            return
        ramp, lines, wall = self.ramp_btn.color(), self.lines_btn.color(), self.wall_btn.color()
        img = Image.new("RGB", (200, 136), wall)
        img.paste(wall_image(wall, 64).resize((200, 136)), (0, 0))
        img.paste(ramp_image(ramp, lines, 128).resize((120, 120)), (8, 8))
        img.paste(wall_image(side_color(ramp), 64).resize((24, 120)), (128, 8))
        self.preview.setPixmap(pil_pixmap(img))


__all__ = ["PRESETS", "AssistantChoice", "RampAssistant", "from_hex", "side_color", "to_hex"]
