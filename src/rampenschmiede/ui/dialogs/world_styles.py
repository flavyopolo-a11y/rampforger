"""Welt-Stile: Himmel, Sonne, Nebel und Farben der ganzen Map mit einem Klick wählen."""
from __future__ import annotations

from PIL import Image, ImageDraw
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from ...core.materials.authoring import ramp_image, wall_image
from ...core.materials.styles import STYLES, WorldStyle
from .ramp_assistant import pil_pixmap

PREVIEW = QSize(168, 108)


def _rgb(text: str) -> tuple[int, int, int]:
    parts = [int(float(p)) for p in text.split()[:3]]
    return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]


def style_preview(style: WorldStyle, w: int = PREVIEW.width(), h: int = PREVIEW.height()) -> Image.Image:
    """Kleines Bild: Himmel als Verlauf, Sonne, darunter Wand und eine Rampe."""
    sun = _rgb(style.sun)
    top = _rgb(style.ambient)
    bottom = _rgb(style.fog.color) if style.fog else tuple(min(255, (a + b) // 2) for a, b in zip(sun, top))
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    horizon = h * 3 // 5
    for y in range(horizon):
        t = y / max(1, horizon - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    sx = w * (0.2 + 0.6 * ((style.yaw % 360) / 360))
    sy = horizon * (1 - min(90, -style.pitch) / 100)
    d.ellipse([sx - 8, sy - 8, sx + 8, sy + 8], fill=sun)
    img.paste(wall_image(style.wall, 64).resize((w, h - horizon)), (0, horizon))
    ramp = ramp_image(style.ramp, style.lines, 64).resize((w // 2, h - horizon + 18))
    mask = Image.new("L", ramp.size, 0)
    ImageDraw.Draw(mask).polygon([(0, ramp.height), (ramp.width * 0.45, 0), (ramp.width, 0), (ramp.width, ramp.height)],
                                 fill=255)
    img.paste(ramp, (w // 4, horizon - 18), mask)
    return img


class WorldStylesDialog(QDialog):
    def __init__(self, clip: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Welt-Stil"))
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        intro = QLabel(self.tr(
            "Ein Stil setzt Himmel, Sonne, Nebel, Wand-Texturen und Rampenfarben der ganzen Map auf einmal. "
            "Texturen aus CS:S und HL2 werden genommen, wenn das Spiel sie hat. Alles ist ein Undo-Schritt "
            "und lässt sich danach frei ändern."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setIconSize(PREVIEW)
        self.list.setGridSize(QSize(PREVIEW.width() + 20, PREVIEW.height() + 34))
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        for style in STYLES:
            item = QListWidgetItem(QIcon(pil_pixmap(style_preview(style))), self.tr(style.name))
            item.setData(Qt.UserRole, style.key)
            item.setToolTip(self.tr(style.description))
            self.list.addItem(item)
        self.list.currentItemChanged.connect(self._show)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())
        lay.addWidget(self.list, 1)
        self.description = QLabel()
        self.description.setWordWrap(True)
        lay.addWidget(self.description)
        self.clip = QCheckBox(self.tr("Playerclip auf Rampen (empfohlen)"))
        self.clip.setChecked(clip)
        lay.addWidget(self.clip)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(self.tr("Stil anwenden"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.list.setCurrentRow(0)

    def chosen(self) -> WorldStyle:
        return STYLES[max(0, self.list.currentRow())]

    def _show(self, *_args) -> None:
        self.description.setText(self.tr(self.chosen().description))


__all__ = ["WorldStylesDialog", "style_preview"]
