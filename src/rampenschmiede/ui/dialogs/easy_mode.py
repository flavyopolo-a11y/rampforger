"""Easy Mode: eine Surf-Map Schritt für Schritt, ohne Vorwissen.

Der Assistent führt durch fünf Schritte: 1. Rampen (Textur und Form, mit Vorschau), 2. Welt-Stil,
3. Strecke (Stages oder linear, Bonusse, Schwierigkeit), 4. Layout-Manager (jede Stage benennen,
Rampen zählen, Anordnung, Plan von oben), 5. Malen. Danach baut das Hauptfenster die Map, wendet
Stil und Rampenfarben an und schaltet das Malen-Werkzeug ein.

Der normale Editor bleibt, wie er ist: Der Easy Mode ist nur ein geführter Einstieg.
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.materials.authoring import RGB
from ...core.materials.styles import STYLE_BY_KEY, STYLES, WorldStyle
from ...core.surf.catalog import CATALOG
from ...core.templates import CourseSpec, PlanItem, SurfMapSettings, plan_surf_map
from ...i18n import N_
from ..icons import ACTIVE
from .ramp_assistant import PRESETS, _ColorButton, pil_pixmap, textured_ramp
from .surf_wizard import GAMES
from .world_styles import StyleGallery, style_preview

#: Schritte des Easy Mode (Titel in der Leiste links)
STEPS = (N_("Rampen"), N_("Welt-Stil"), N_("Strecke"), N_("Layout"), N_("Malen"))

#: Formen, auf denen Schritt 1 die Textur zeigt
PREVIEW_KINDS = ("gerade", "banane", "welle", "ski")

#: Schwierigkeit -> Surf-Winkel, Lücke, Abfall je Rampe, Rampenlänge
DIFFICULTY: dict[str, tuple[str, float, int, int, int]] = {
    "leicht": (N_("Leicht"), 47.0, 128, 128, 2048),
    "mittel": (N_("Mittel"), 50.0, 256, 192, 2048),
    "schwer": (N_("Schwer"), 55.0, 512, 256, 1536),
}

PREVIEW_SIZE = QSize(360, 250)
THUMB = 96
KIND_COLORS = {
    "gerade": QColor(120, 150, 185), "ski": QColor(160, 165, 175), "banane": QColor(110, 190, 180),
    "welle": QColor(150, 200, 110), "trapez": QColor(185, 150, 200),
}
PLAN_COLORS = {
    "ramp": QColor(120, 150, 185), "platform": QColor(150, 150, 155), "start": QColor(80, 200, 110),
    "stage": QColor(70, 160, 240), "end": QColor(235, 80, 70), "teleport": QColor(190, 110, 240),
}


@dataclass
class EasyResult:
    """Was der Easy Mode gewählt hat: Rampenfarben, Welt-Stil und die geplante Strecke."""

    ramp: RGB
    lines: RGB
    style: str
    settings: SurfMapSettings
    clip: bool = True


def _backdrop(size: QSize, style: WorldStyle | None) -> QPixmap:
    """Hintergrund der Rampenvorschau: Himmel des Welt-Stils als Verlauf (oder neutral grau)."""
    if style is None:
        top, bottom = (58, 64, 74), (32, 34, 38)
    else:
        top = tuple(int(float(p)) for p in style.ambient.split()[:3])
        bottom = tuple(int(float(p)) for p in (style.fog.color if style.fog else style.sun).split()[:3])
    img = Image.new("RGB", (size.width(), size.height()))
    d = ImageDraw.Draw(img)
    for y in range(size.height()):
        t = y / max(1, size.height() - 1)
        d.line([(0, y), (size.width(), y)], fill=tuple(round(a + (b - a) * t * 0.8) for a, b in zip(top, bottom)))
    return pil_pixmap(img)


class RampPreview(QLabel):
    """Große Vorschau: So sieht die gewählte Rampe mit der gewählten Textur aus."""

    def __init__(self, size: QSize = PREVIEW_SIZE, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("border: 1px solid #444; border-radius: 6px;")
        self.setToolTip(self.tr("Vorschau: so sieht die Rampe mit dieser Textur aus"))

    def show_ramp(self, kind: str, ramp: RGB, lines: RGB, style: WorldStyle | None = None) -> None:
        self.show_ramps([kind], ramp, lines, style)

    def show_ramps(self, kinds: list[str], ramp: RGB, lines: RGB, style: WorldStyle | None = None) -> None:
        """Eine Rampe groß, mehrere nebeneinander: so sieht der Mix der Map aus."""
        canvas = _backdrop(self.size(), style)
        kinds = kinds or ["gerade"]
        cols = 1 if len(kinds) == 1 else 2
        rows = -(-len(kinds) // cols)
        w, h = self.width() // cols, self.height() // rows
        p = QPainter(canvas)
        for i, kind in enumerate(kinds):
            r, c = divmod(i, cols)
            p.drawPixmap(c * w, r * h, textured_ramp(kind, ramp, lines, QSize(w, h)))
        p.end()
        self.setPixmap(canvas)


def _gallery(icon_size: int, rows: int = 1) -> QListWidget:
    g = QListWidget()
    g.setViewMode(QListView.IconMode)
    g.setIconSize(QSize(icon_size, icon_size))
    g.setGridSize(QSize(icon_size + 26, icon_size + 34))
    g.setMovement(QListView.Static)
    g.setResizeMode(QListView.Adjust)
    g.setWordWrap(True)
    g.setFixedHeight(rows * (icon_size + 34) + 14)
    return g


def _plain_icon(pix: QPixmap) -> QIcon:
    """Symbol, das auch ausgewählt seine echten Farben zeigt (Qt färbt sonst mit der Auswahlfarbe)."""
    ic = QIcon(pix)
    ic.addPixmap(pix, QIcon.Selected)
    return ic


def _title(text: str) -> QLabel:
    label = QLabel(text)
    f = label.font()
    f.setPointSizeF(f.pointSizeF() * 1.45)
    f.setBold(True)
    label.setFont(f)
    label.setWordWrap(True)
    return label


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #aab0b8;")
    return label


# ---- Schritt 1: Rampen ---------------------------------------------------------------------

class RampPage(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_title(self.tr("1. Welche Textur sollen deine Rampen haben?")))
        lay.addWidget(_hint(self.tr("Rechts siehst du sofort, wie die Rampen damit im Spiel aussehen. "
                                    "Alles lässt sich später noch ändern.")))
        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel(self.tr("<b>Rampentextur</b>")))
        self.textures = _gallery(THUMB, rows=2)
        for name, ramp, lines, _wall in PRESETS:
            item = QListWidgetItem(_plain_icon(textured_ramp("gerade", ramp, lines, THUMB)), self.tr(name))
            item.setData(Qt.UserRole, (ramp, lines))
            self.textures.addItem(item)
        own = QListWidgetItem(_plain_icon(textured_ramp("gerade", (200, 200, 200), (255, 140, 40), THUMB)),
                              self.tr("Eigene Farben"))
        own.setData(Qt.UserRole, None)
        self.textures.addItem(own)
        left.addWidget(self.textures)
        self.colors = QWidget()
        row = QHBoxLayout(self.colors)
        row.setContentsMargins(0, 0, 0, 0)
        self.ramp_btn = _ColorButton(PRESETS[0][1], self.tr("Farbe der Rampen"))
        self.lines_btn = _ColorButton(PRESETS[0][2], self.tr("Farbe der Rampenlinien"))
        row.addWidget(QLabel(self.tr("Rampe")))
        row.addWidget(self.ramp_btn)
        row.addWidget(QLabel(self.tr("Linien")))
        row.addWidget(self.lines_btn)
        row.addStretch(1)
        left.addWidget(self.colors)
        left.addStretch(1)
        body.addLayout(left, 1)
        right = QVBoxLayout()
        self.preview = RampPreview()
        right.addWidget(self.preview)
        self.preview_label = _hint("")
        right.addWidget(self.preview_label)
        right.addStretch(1)
        body.addLayout(right)
        lay.addLayout(body, 1)

        self.textures.currentItemChanged.connect(self._texture_chosen)
        self.ramp_btn.changed.connect(self._update)
        self.lines_btn.changed.connect(self._update)
        self.style: WorldStyle | None = None
        self.textures.setCurrentRow(0)

    def _texture_chosen(self, item: QListWidgetItem | None, _prev=None) -> None:
        if item is None:
            return
        data = item.data(Qt.UserRole)
        own = data is None
        self.colors.setVisible(own)
        if not own:
            for b, c in ((self.ramp_btn, data[0]), (self.lines_btn, data[1])):
                b.blockSignals(True)
                b.set_color(c)
                b.blockSignals(False)
        self._update()

    def colors_chosen(self) -> tuple[RGB, RGB]:
        return self.ramp_btn.color(), self.lines_btn.color()

    def set_colors(self, ramp: RGB, lines: RGB) -> None:
        """Farben von außen (z. B. vom Welt-Stil) übernehmen, als eigene Farben."""
        self.textures.blockSignals(True)
        self.textures.setCurrentRow(self.textures.count() - 1)
        self.textures.blockSignals(False)
        self.colors.setVisible(True)
        self.ramp_btn.set_color(ramp)
        self.lines_btn.set_color(lines)

    def texture_name(self) -> str:
        item = self.textures.currentItem()
        return item.text() if item is not None else ""

    def _update(self) -> None:
        ramp, lines = self.colors_chosen()
        self.preview.show_ramps(list(PREVIEW_KINDS), ramp, lines, self.style)
        self.preview_label.setText(self.tr("Textur „{0}“ auf verschiedenen Rampen. Die Form jeder Rampe wählst du "
                                           "im Layout-Manager.").format(self.texture_name()))
        self.changed.emit()


# ---- Schritt 2: Welt-Stil ----------------------------------------------------------------

class StylePage(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_title(self.tr("2. Welchen Stil soll die Welt haben?")))
        lay.addWidget(_hint(self.tr("Der Stil setzt Himmel, Sonne, Nebel und die Wände der ganzen Map. Deine "
                                    "Rampentextur aus Schritt 1 bleibt, außer du nimmst die Rampenfarben vom Stil.")))
        body = QHBoxLayout()
        self.gallery = StyleGallery(QSize(150, 96))
        body.addWidget(self.gallery, 1)
        right = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(PREVIEW_SIZE)
        self.preview.setStyleSheet("border: 1px solid #444; border-radius: 6px;")
        right.addWidget(self.preview)
        self.description = _hint("")
        self.description.setFixedWidth(PREVIEW_SIZE.width())
        right.addWidget(self.description)
        self.take_ramps = QCheckBox(self.tr("Rampenfarben vom Stil übernehmen"))
        right.addWidget(self.take_ramps)
        right.addStretch(1)
        body.addLayout(right)
        lay.addLayout(body, 1)
        self.gallery.currentItemChanged.connect(self._show)
        self.take_ramps.toggled.connect(lambda _on: self.changed.emit())
        self.gallery.setCurrentRow(0)

    def style(self) -> WorldStyle:
        return STYLES[max(0, self.gallery.currentRow())]

    def _show(self, *_args) -> None:
        style = self.style()
        self.preview.setPixmap(pil_pixmap(style_preview(style, PREVIEW_SIZE.width(), PREVIEW_SIZE.height())))
        self.description.setText(f"<b>{self.tr(style.name)}</b><br>{self.tr(style.description)}")
        self.changed.emit()


# ---- Schritt 3: Strecke -------------------------------------------------------------------

def _spin(lo: int, hi: int, value: int, step: int = 1, suffix: str = "") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(value)
    s.setSuffix(suffix)
    return s


def _big_choice(text: str, hint: str) -> QRadioButton:
    b = QRadioButton(text)
    b.setToolTip(hint)
    f = b.font()
    f.setBold(True)
    b.setFont(f)
    return b


class CoursePage(QWidget):
    changed = Signal()

    def __init__(self, game: str | None = None, parent=None) -> None:
        super().__init__(parent)
        d = SurfMapSettings()
        lay = QVBoxLayout(self)
        lay.addWidget(_title(self.tr("3. Wie soll deine Strecke sein?")))
        lay.addWidget(_hint(self.tr("Stage-Maps sind in Abschnitte geteilt: Wer fällt, startet die Stage neu. "
                                    "Lineare Maps sind eine durchgehende Strecke. Bonusse sind kurze Extra-Strecken "
                                    "mit eigener Zeit.")))
        self.staged = _big_choice(self.tr("Mit Stages"), self.tr("Die Strecke ist in Stages geteilt, jede mit eigenem Start"))
        self.linear = _big_choice(self.tr("Linear (eine durchgehende Strecke)"),
                                  self.tr("Eine lange Strecke ohne Stages"))
        group = QButtonGroup(self)
        group.addButton(self.staged)
        group.addButton(self.linear)
        self.staged.setChecked(True)
        kind = QHBoxLayout()
        kind.addWidget(self.staged)
        kind.addWidget(self.linear)
        kind.addStretch(1)
        lay.addLayout(kind)

        form = QFormLayout()
        self.stages = _spin(1, 12, d.stages)
        self.ramps = _spin(1, 8, d.ramps_per_stage)
        self.ramps_label = QLabel(self.tr("Platz für Rampen pro Stage"))
        self.stages_label = QLabel(self.tr("Stages"))
        self.bonuses = _spin(0, 4, 0)
        self.difficulty = QComboBox()
        for key, (name, *_rest) in DIFFICULTY.items():
            self.difficulty.addItem(self.tr(name), key)
        self.difficulty.setCurrentIndex(1)
        self.game = QComboBox()
        for key, name in GAMES:
            self.game.addItem(self.tr(name), key)
        self.game.setCurrentIndex(max(0, self.game.findData(game or "")))
        form.addRow(self.stages_label, self.stages)
        form.addRow(self.ramps_label, self.ramps)
        form.addRow(self.tr("Bonusse"), self.bonuses)
        form.addRow(self.tr("Schwierigkeit"), self.difficulty)
        form.addRow(self.tr("Spiel"), self.game)
        lay.addLayout(form)

        self.fine = QGroupBox(self.tr("Feineinstellungen (für Profis)"))
        self.fine.setCheckable(True)
        self.fine.setChecked(False)
        fine = QFormLayout(self.fine)
        self.length = _spin(512, 8192, d.ramp_length, 256, " u")
        self.width = _spin(256, 4096, d.ramp_width, 64, " u")
        self.angle = QDoubleSpinBox()
        self.angle.setRange(45.5, 65)
        self.angle.setSingleStep(0.5)
        self.angle.setValue(d.angle)
        self.angle.setSuffix("°")
        self.gap = _spin(0, 2048, d.gap, 64, " u")
        self.drop = _spin(0, 1024, d.drop, 32, " u")
        fine.addRow(self.tr("Rampenlänge"), self.length)
        fine.addRow(self.tr("Rampenbreite"), self.width)
        fine.addRow(self.tr("Surf-Winkel"), self.angle)
        fine.addRow(self.tr("Lücke zwischen Rampen"), self.gap)
        fine.addRow(self.tr("Jede Rampe tiefer um"), self.drop)
        self._fine_widgets = (self.length, self.width, self.angle, self.gap, self.drop)
        lay.addWidget(self.fine)
        lay.addStretch(1)

        self.fine.toggled.connect(self._fine_toggled)
        self.difficulty.currentIndexChanged.connect(self._difficulty_chosen)
        self.staged.toggled.connect(self._kind_toggled)
        for w in (self.stages, self.ramps, self.bonuses, *self._fine_widgets):
            w.valueChanged.connect(lambda *_: self.changed.emit())
        self.game.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self._fine_toggled(False)
        self._difficulty_chosen()

    def is_linear(self) -> bool:
        return self.linear.isChecked()

    def _kind_toggled(self, staged: bool) -> None:
        self.stages.setVisible(staged)
        self.stages_label.setVisible(staged)
        self.ramps_label.setText(self.tr("Platz für Rampen pro Stage") if staged else self.tr("Platz für Rampen"))
        # Linear: eine lange Strecke mit mehr Rampen; zurück zu Stages: wieder wenige je Stage
        if not staged and self.ramps.value() < 4:
            self.ramps.setValue(6)
        elif staged and self.ramps.value() > 3:
            self.ramps.setValue(2)
        self.changed.emit()

    def _fine_toggled(self, on: bool) -> None:
        for w in self._fine_widgets:
            w.setEnabled(on)

    def _difficulty_chosen(self, *_args) -> None:
        _name, angle, gap, drop, length = DIFFICULTY[self.difficulty.currentData()]
        for w, v in ((self.angle, angle), (self.gap, gap), (self.drop, drop), (self.length, length)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self.changed.emit()

    def counts(self) -> tuple[int, int, int]:
        """(Stages, Rampen je Stage, Bonusse); linear ist eine Stage mit allen Rampen."""
        return (1 if self.is_linear() else self.stages.value()), self.ramps.value(), self.bonuses.value()

    def base_settings(self, kind: str) -> SurfMapSettings:
        return SurfMapSettings(game=self.game.currentData() or None, ramp_kind=kind,
                               ramp_length=self.length.value(), ramp_width=self.width.value(),
                               angle=self.angle.value(), gap=self.gap.value(), drop=self.drop.value())


# ---- Schritt 4: Layout-Manager ----------------------------------------------------------

class LayoutPlan(QWidget):
    """Plan der Map von oben: Plattformen, Rampen, Zonen und Teleporter mit Namen."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.items: list[PlanItem] = []
        self.error = ""
        self.setMinimumSize(380, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_plan(self, items: list[PlanItem], error: str) -> None:
        self.items, self.error = items, error
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(28, 30, 34))
        if not self.items:
            p.end()
            return
        x0 = min(i.rect[0] for i in self.items)
        y0 = min(i.rect[1] for i in self.items)
        x1 = max(i.rect[2] for i in self.items)
        y1 = max(i.rect[3] for i in self.items)
        margin = 24
        scale = min((self.width() - 2 * margin) / max(1.0, x1 - x0), (self.height() - 2 * margin) / max(1.0, y1 - y0))
        ox = (self.width() - (x1 - x0) * scale) / 2
        oy = (self.height() - (y1 - y0) * scale) / 2

        def rect(r) -> QRectF:
            # Norden (+Y) oben wie in der Ansicht von oben
            return QRectF(ox + (r[0] - x0) * scale, oy + (y1 - r[3]) * scale,
                          (r[2] - r[0]) * scale, (r[3] - r[1]) * scale)

        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() * 0.85))
        p.setFont(font)
        for item in self.items:
            color = PLAN_COLORS.get(item.kind, PLAN_COLORS["platform"])
            if item.kind == "ramp":
                # Jede Rampenform eigene Farbe: man sieht, dass die Rampen abwechseln
                color = KIND_COLORS.get(item.label, color)
            if item.kind == "space":
                # Leerer Platz, auf den man die Rampen selbst malt
                p.setPen(QPen(QColor(255, 140, 40, 200), 1.5, Qt.DashLine))
                p.setBrush(QColor(255, 140, 40, 28))
            else:
                p.setPen(QPen(color.darker(160), 1))
                p.setBrush(color)
            p.drawRoundedRect(rect(item.rect), 3, 3)
        p.setPen(QColor(235, 238, 242))
        for item in self.items:
            if item.kind == "space":
                r = rect(item.rect)
                if r.width() > 50:
                    p.setPen(QColor(255, 170, 90))
                    p.drawText(r, Qt.AlignCenter | Qt.TextWordWrap, self.tr("Rampe malen"))
                    p.setPen(QColor(235, 238, 242))
            elif item.kind == "ramp" and item.label in CATALOG:
                r = rect(item.rect)
                if r.width() > 40:
                    p.setPen(QColor(20, 22, 26))
                    p.drawText(r, Qt.AlignCenter, self.tr(CATALOG[item.label].name))
                    p.setPen(QColor(235, 238, 242))
            elif item.kind in ("start", "stage", "end", "teleport") and item.label:
                r = rect(item.rect)
                p.drawText(QRectF(r.left() - 40, r.bottom() + 2, r.width() + 80, 16), Qt.AlignHCenter | Qt.AlignTop,
                           item.label)
        if self.error:
            p.setPen(QColor(255, 120, 80))
            p.drawText(self.rect().adjusted(8, 8, -8, -8), Qt.AlignTop | Qt.AlignLeft | Qt.TextWordWrap, self.error)
        p.end()


class _Course:
    """Eine Zeile im Layout-Manager: Stage oder Bonus mit Name und Platz für Rampen."""

    def __init__(self, track: int, item: QTreeWidgetItem, name: QLineEdit, count: QSpinBox) -> None:
        self.track = track
        self.item = item
        self.name = name
        self.count = count


class LayoutPage(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_title(self.tr("4. Layout-Manager: So liegt deine Map")))
        lay.addWidget(_hint(self.tr("Gib jeder Stage und jedem Bonus einen Namen und sag, wie viel Platz sie für "
                                    "Rampen braucht. Die Rampen selbst malst du danach, so wie du sie haben willst. "
                                    "Gestrichelt im Plan: dort malst du.")))
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([self.tr("Name"), self.tr("Platz für Rampen")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumWidth(420)
        left.addWidget(self.tree, 1)
        arrange = QFormLayout()
        self.layout_combo = QComboBox()
        self.layout_combo.addItem(self.tr("Hintereinander (man surft von Stage zu Stage)"), "linie")
        self.layout_combo.addItem(self.tr("In Reihen nebeneinander (Teleporter zur nächsten Stage)"), "reihen")
        arrange.addRow(self.tr("Anordnung"), self.layout_combo)
        left.addLayout(arrange)
        buttons = QHBoxLayout()
        self.add_stage = QPushButton(self.tr("+ Stage"))
        self.remove_stage = QPushButton(self.tr("− Stage"))
        self.add_bonus = QPushButton(self.tr("+ Bonus"))
        self.remove_bonus = QPushButton(self.tr("− Bonus"))
        for b in (self.add_stage, self.remove_stage, self.add_bonus, self.remove_bonus):
            buttons.addWidget(b)
        buttons.addStretch(1)
        left.addLayout(buttons)
        body.addLayout(left, 1)
        right = QVBoxLayout()
        self.plan = LayoutPlan()
        right.addWidget(self.plan, 1)
        self.size_label = QLabel()
        self.size_label.setWordWrap(True)
        right.addWidget(self.size_label)
        body.addLayout(right, 1)
        lay.addLayout(body, 1)

        self.courses: list[_Course] = []
        self.linear = False
        self.layout_combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.add_stage.clicked.connect(lambda: self._add(0))
        self.remove_stage.clicked.connect(lambda: self._remove(0))
        self.add_bonus.clicked.connect(lambda: self._add(1))
        self.remove_bonus.clicked.connect(lambda: self._remove(1))

    # Zeilen ------------------------------------------------------------------------------
    def _of(self, bonus: bool) -> list[_Course]:
        return [c for c in self.courses if bool(c.track) == bonus]

    def _label(self, course: _Course) -> str:
        if course.track:
            return self.tr("Bonus {0}").format(self._of(True).index(course) + 1)
        if self.linear:
            return self.tr("Strecke")
        return self.tr("Stage {0}").format(self._of(False).index(course) + 1)

    def _relabel(self) -> None:
        for c in self.courses:
            c.name.setPlaceholderText(self._label(c))
            c.item.setToolTip(0, self._label(c))
        stages = len(self._of(False))
        self.remove_stage.setEnabled(stages > 1)
        self.add_stage.setEnabled(not self.linear and stages < 12)
        self.add_stage.setVisible(not self.linear)
        self.remove_stage.setVisible(not self.linear)
        self.remove_bonus.setEnabled(bool(self._of(True)))
        self.add_bonus.setEnabled(len(self._of(True)) < 4)
        self.layout_combo.setEnabled(not self.linear and stages > 1)

    def _insert(self, track: int, spec: CourseSpec) -> None:
        index = len(self.courses) if track else len(self._of(False))
        item = QTreeWidgetItem()
        self.tree.insertTopLevelItem(index, item)
        name = QLineEdit(spec.name)
        name.textChanged.connect(lambda *_: self.changed.emit())
        count = _spin(1, 12 if self.linear and not track else 8, spec.ramps, suffix=self.tr(" Rampen"))
        count.setToolTip(self.tr("So viel Platz bekommt die Stage: je Rampe eine Rampenlänge"))
        course = _Course(1 if track else 0, item, name, count)
        self.courses.insert(index, course)
        self.tree.setItemWidget(item, 0, name)
        self.tree.setItemWidget(item, 1, count)
        count.valueChanged.connect(lambda *_: self.changed.emit())

    def _add(self, track: int) -> None:
        self._insert(track, CourseSpec(ramps=1 if track else 2))
        self._relabel()
        self.changed.emit()

    def _remove(self, track: int) -> None:
        rows = self._of(bool(track))
        if not rows or (not track and len(rows) <= 1):
            return
        self._remove_course(rows[-1])
        self._relabel()
        self.changed.emit()

    def _remove_course(self, course: _Course) -> None:
        self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(course.item))
        self.courses.remove(course)

    def sync(self, stages: int, ramps: int, bonuses: int, linear: bool) -> None:
        """Zeilen an Schritt 3 anpassen; Namen und Formen vorhandener Zeilen bleiben."""
        self.linear = linear
        for c in self._of(False):
            c.count.setMaximum(12 if linear else 8)
        while len(self._of(False)) < stages:
            self._insert(0, CourseSpec(ramps=ramps))
        while len(self._of(False)) > stages:
            self._remove_course(self._of(False)[-1])
        while len(self._of(True)) < bonuses:
            self._insert(1, CourseSpec(ramps=1))
        while len(self._of(True)) > bonuses:
            self._remove_course(self._of(True)[-1])
        self._relabel()

    def set_ramps(self, ramps: int) -> None:
        """Rampen pro Stage aus Schritt 3 auf alle Stages übertragen."""
        for c in self._of(False):
            c.count.setValue(ramps)

    def specs(self) -> tuple[tuple[CourseSpec, ...], tuple[CourseSpec, ...]]:
        stages, bonuses = [], []
        for c in self.courses:
            spec = CourseSpec(c.name.text().strip(), c.count.value())
            (bonuses if c.track else stages).append(spec)
        return tuple(stages), tuple(bonuses)

    def layout_key(self) -> str:
        return "linie" if self.linear else self.layout_combo.currentData()

    def show_plan(self, settings: SurfMapSettings) -> str:
        items, error = plan_surf_map(settings)
        self.plan.set_plan(items, error)
        if error:
            self.size_label.setText(self.tr("So geht es nicht: {0}").format(error))
            self.size_label.setStyleSheet("color: #e85; font-weight: bold;")
        else:
            xs = [c for i in items for c in (i.rect[0], i.rect[2])]
            ys = [c for i in items for c in (i.rect[1], i.rect[3])]
            ramps = sum(1 for i in items if i.kind in ("ramp", "space"))
            self.size_label.setText(self.tr("✓ Passt: Platz für {0} Rampen, etwa {1} × {2} Units (Source erlaubt 32768)").format(
                ramps, round(max(xs) - min(xs)), round(max(ys) - min(ys))))
            self.size_label.setStyleSheet("color: #6c6; font-weight: bold;")
        return error


# ---- Schritt 5: Malen ---------------------------------------------------------------------

class PaintPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_title(self.tr("5. Jetzt deine Map malen")))
        lay.addWidget(_hint(self.tr("Mit „Map bauen“ entsteht der Rahmen deiner Map: Start mit Spawn, Stages mit "
                                    "Zonen und Teleportern, eine dichte Skybox. Die Rampen malst du selbst: Form links "
                                    "anklicken, in der Ansicht vom Anfang zum Ende ziehen. Für jede Rampe kannst du "
                                    "eine andere Form nehmen. Oben führt dich eine Leiste durch die nächsten Schritte.")))
        body = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        left = QVBoxLayout()
        left.addWidget(self.summary)
        self.plan = LayoutPlan()
        left.addWidget(self.plan, 1)
        body.addLayout(left, 1)
        self.preview = RampPreview(QSize(300, 210))
        body.addWidget(self.preview, 0, Qt.AlignTop)
        lay.addLayout(body, 1)


# ---- Der Assistent ---------------------------------------------------------------------

class EasyModeWizard(QDialog):
    def __init__(self, game: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Easy Mode: neue Map Schritt für Schritt"))
        self.resize(1120, 700)
        outer = QHBoxLayout(self)
        self.steps = QListWidget()
        self.steps.setFixedWidth(170)
        self.steps.setStyleSheet(
            "QListWidget { border: none; background: transparent; font-size: 11pt; }"
            f"QListWidget::item {{ padding: 10px 6px; }} QListWidget::item:selected {{ color: {ACTIVE}; "
            "font-weight: bold; background: rgba(255,140,40,0.12); border-radius: 6px; }")
        for i, name in enumerate(STEPS, start=1):
            self.steps.addItem(f"{i}  {self.tr(name)}")
        outer.addWidget(self.steps)
        main = QVBoxLayout()
        self.stack = QStackedWidget()
        self.ramps = RampPage()
        self.style_page = StylePage()
        self.course = CoursePage(game)
        self.layout_page = LayoutPage()
        self.paint = PaintPage()
        for page in (self.ramps, self.style_page, self.course, self.layout_page, self.paint):
            self.stack.addWidget(page)
        main.addWidget(self.stack, 1)
        nav = QHBoxLayout()
        self.cancel_btn = QPushButton(self.tr("Abbrechen"))
        self.back_btn = QPushButton(self.tr("← Zurück"))
        self.next_btn = QPushButton(self.tr("Weiter →"))
        self.next_btn.setDefault(True)
        self.next_btn.setStyleSheet(f"QPushButton {{ background: {ACTIVE}; color: #111; font-weight: bold; "
                                    "padding: 6px 18px; border-radius: 4px; } QPushButton:disabled { background: #555; }")
        nav.addWidget(self.cancel_btn)
        nav.addStretch(1)
        nav.addWidget(self.back_btn)
        nav.addWidget(self.next_btn)
        main.addLayout(nav)
        outer.addLayout(main, 1)

        self._plan_timer = QTimer(self)
        self._plan_timer.setSingleShot(True)
        self._plan_timer.setInterval(120)
        self._plan_timer.timeout.connect(self._update_plan)
        self._error = ""
        self.cancel_btn.clicked.connect(self.reject)
        self.back_btn.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        self.next_btn.clicked.connect(self._next)
        self.steps.currentRowChanged.connect(self._step_clicked)
        self.style_page.changed.connect(self._style_changed)
        self.ramps.changed.connect(self._plan_timer.start)
        self.course.changed.connect(self._course_changed)
        self.course.ramps.valueChanged.connect(self.layout_page.set_ramps)
        self.layout_page.changed.connect(self._plan_timer.start)
        self._course_changed()
        self.go(0)

    # Navigation -----------------------------------------------------------------------
    def go(self, index: int) -> None:
        index = max(0, min(index, self.stack.count() - 1))
        self.stack.setCurrentIndex(index)
        self.steps.blockSignals(True)
        self.steps.setCurrentRow(index)
        self.steps.blockSignals(False)
        for i in range(self.steps.count()):
            item = self.steps.item(i)
            done = i < index
            item.setText(f"{'✓' if done else i + 1}  {self.tr(STEPS[i])}")
        last = index == self.stack.count() - 1
        self.back_btn.setEnabled(index > 0)
        self.next_btn.setText(self.tr("Map bauen und malen") if last else self.tr("Weiter →"))
        if index >= 3:
            self._update_plan()
        if last:
            self._update_summary()
        self._update_next()

    def _step_clicked(self, row: int) -> None:
        self.go(row)

    def _next(self) -> None:
        if self.stack.currentIndex() == self.stack.count() - 1:
            if not self._error:
                self.accept()
            return
        self.go(self.stack.currentIndex() + 1)

    def _update_next(self) -> None:
        self.next_btn.setEnabled(not (self._error and self.stack.currentIndex() >= 3))

    # Abhängigkeiten zwischen den Schritten -----------------------------------------------
    def _style_changed(self) -> None:
        style = self.style_page.style()
        self.ramps.style = style
        if self.style_page.take_ramps.isChecked():
            self.ramps.set_colors(style.ramp, style.lines)
        else:
            self.ramps._update()

    def _course_changed(self) -> None:
        stages, ramps, bonuses = self.course.counts()
        self.layout_page.sync(stages, ramps, bonuses, self.course.is_linear())
        if self.course.is_linear():
            self.layout_page.set_ramps(ramps)
        self._plan_timer.start()

    def settings(self) -> SurfMapSettings:
        s = self.course.base_settings("gerade")
        s.with_ramps = False  # nur der Rahmen, die Rampen malt man selbst
        stages, bonuses = self.layout_page.specs()
        s.stage_specs = stages
        s.stages = len(stages)
        s.bonuses = bonuses
        s.layout = self.layout_page.layout_key()
        return s

    def _update_plan(self) -> None:
        self._error = self.layout_page.show_plan(self.settings())
        self._update_next()

    def _update_summary(self) -> None:
        s = self.settings()
        ramp, lines = self.ramps.colors_chosen()
        style = self.style_page.style()
        stages, bonuses = s.stage_specs, s.bonuses
        names = ", ".join(spec.name or self.tr("Stage {0}").format(i) for i, spec in enumerate(stages, 1))
        rows = [
            (self.tr("Rampen"), self.tr("Textur „{0}“, du malst sie selbst").format(self.ramps.texture_name())),
            (self.tr("Welt-Stil"), self.tr(style.name)),
            (self.tr("Strecke"), self.tr("Linear mit {0} Rampen").format(stages[0].ramps) if self.course.is_linear()
             else self.tr("{0} Stages: {1}").format(len(stages), names)),
            (self.tr("Bonusse"), ", ".join(b.name or self.tr("Bonus {0}").format(i) for i, b in enumerate(bonuses, 1))
             or self.tr("keine")),
            (self.tr("Schwierigkeit"), self.course.difficulty.currentText()),
            (self.tr("Spiel"), self.course.game.currentText()),
        ]
        self.paint.summary.setText("<table cellspacing=6>" + "".join(
            f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows) + "</table>")
        self.paint.preview.show_ramps(list(PREVIEW_KINDS), ramp, lines, style)
        self.paint.plan.set_plan(self.layout_page.plan.items, self.layout_page.plan.error)

    def choice(self) -> EasyResult:
        ramp, lines = self.ramps.colors_chosen()
        return EasyResult(ramp, lines, self.style_page.style().key, self.settings())


def style_of(result: EasyResult) -> WorldStyle:
    return STYLE_BY_KEY.get(result.style, STYLES[0])


__all__ = ["DIFFICULTY", "STEPS", "EasyModeWizard", "EasyResult", "LayoutPlan", "RampPreview", "style_of",
           "textured_ramp"]
