"""Easy Mode: der Rahmen einer Surf-Map in vier Schritten, die Rampen malt man danach selbst.

1. Welt-Stil (Himmel, Licht, Wände), 2. Rampentextur (passend zum Stil, Farben, jede Textur des Spiels
oder ein eigenes Bild), 3. Strecke (Stages oder linear, Bonusse; jede Stage ein eigener Raum mit
Namen und Größe, Plan von oben), 4. Bauen. Danach baut das Hauptfenster die Räume mit Start, Ziel,
Zonen und Teleportern, wendet Stil und Textur an und schaltet das Malen-Werkzeug ein. Welche Rampe
wohin kommt und wie die Strecke im Raum kurvt, entscheidet man beim Malen.

Der normale Editor bleibt, wie er ist: Der Easy Mode ist nur ein geführter Einstieg.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image, ImageDraw
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
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
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.materials.authoring import RGB
from ...core.materials.styles import STYLE_BY_KEY, STYLES, WorldStyle
from ...core.templates import (
    LINEAR_ROOMS,
    STAGE_ROOMS,
    PlanItem,
    RoomMapSettings,
    RoomSpec,
    plan_room_map,
)
from ...i18n import N_
from ..icons import ACTIVE
from ..widgets.template_preview import library_textures, template_pixmap
from .ramp_assistant import PRESETS, _ColorButton, pil_pixmap, textured_ramp
from .surf_wizard import GAMES
from .world_styles import StyleGallery, style_preview

#: Schritte des Easy Mode (Titel in der Leiste links)
STEPS = (N_("Welt-Stil"), N_("Rampentextur"), N_("Strecke"), N_("Bauen"))

MAX_STAGES = 12
MAX_BONUSES = 4

#: Formen, auf denen Schritt 2 die Textur zeigt
PREVIEW_KINDS = ("gerade", "banane", "welle", "ski")
PREVIEW_SIZE = QSize(360, 250)
THUMB = 96
PLAN_COLORS = {
    "ramp": QColor(120, 150, 185), "platform": QColor(150, 150, 155), "start": QColor(80, 200, 110),
    "stage": QColor(70, 160, 240), "end": QColor(235, 80, 70), "teleport": QColor(190, 110, 240),
}
#: Eintrag der Texturliste, der die Rampenfarben des Welt-Stils nimmt
FROM_STYLE = "style"
OWN = "own"
#: Daten eines Galerie-Eintrags mit einer Textur aus der Bibliothek: (MATERIAL, Name)
MATERIAL = "material"


@dataclass
class EasyResult:
    """Was der Easy Mode gewählt hat: Rampenfarben, Welt-Stil und die geplante Strecke."""

    ramp: RGB
    lines: RGB
    style: str
    settings: RoomMapSettings
    clip: bool = True
    #: Textur aus der Bibliothek für die Rampen (leer = Rampenfarben `ramp`/`lines`)
    material: str = ""


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


def material_ramp(kind: str, material: str, library, size: QSize | int = 200) -> QPixmap:
    """Rampe der Art `kind` mit einer Textur aus der Bibliothek (Spiel oder eigene) auf allen Seiten."""
    values: dict = {"mat_surf": material, "mat_seite": material}
    if kind == "ski":
        values["gefaelle"] = -256
    return template_pixmap(kind, values, size, library_textures(library))


class RampPreview(QLabel):
    """Vorschau: verschiedene Rampen mit der gewählten Textur vor dem Himmel des Stils."""

    def __init__(self, size: QSize = PREVIEW_SIZE, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("border: 1px solid #444; border-radius: 6px;")
        self.setToolTip(self.tr("Vorschau: so sehen Rampen mit dieser Textur aus"))

    def show_ramps(self, kinds: list[str], ramp: RGB, lines: RGB, style: WorldStyle | None = None,
                   material: str = "", library=None) -> None:
        canvas = _backdrop(self.size(), style)
        kinds = kinds or ["gerade"]
        cols = 1 if len(kinds) == 1 else 2
        rows = -(-len(kinds) // cols)
        w, h = self.width() // cols, self.height() // rows
        p = QPainter(canvas)
        for i, kind in enumerate(kinds):
            r, c = divmod(i, cols)
            pix = (material_ramp(kind, material, library, QSize(w, h)) if material
                   else textured_ramp(kind, ramp, lines, QSize(w, h)))
            p.drawPixmap(c * w, r * h, pix)
        p.end()
        self.setPixmap(canvas)


def _plain_icon(pix: QPixmap) -> QIcon:
    """Symbol, das auch ausgewählt seine echten Farben zeigt (Qt färbt sonst mit der Auswahlfarbe)."""
    ic = QIcon(pix)
    ic.addPixmap(pix, QIcon.Selected)
    return ic


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


# ---- Schritt 1: Welt-Stil ----------------------------------------------------------------

class StylePage(QWidget):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_title(self.tr("1. Wie soll deine Welt aussehen?")))
        lay.addWidget(_hint(self.tr("Der Stil setzt Himmel, Sonne, Nebel und Wände der ganzen Map. "
                                    "Die passende Rampentextur schlägt der nächste Schritt vor.")))
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
        right.addStretch(1)
        body.addLayout(right)
        lay.addLayout(body, 1)
        self.gallery.currentItemChanged.connect(self._show)
        self.gallery.setCurrentRow(0)

    def style(self) -> WorldStyle:
        return STYLES[max(0, self.gallery.currentRow())]

    def _show(self, *_args) -> None:
        style = self.style()
        self.preview.setPixmap(pil_pixmap(style_preview(style, PREVIEW_SIZE.width(), PREVIEW_SIZE.height())))
        self.description.setText(f"<b>{self.tr(style.name)}</b><br>{self.tr(style.description)}")
        self.changed.emit()


# ---- Schritt 2: Rampentextur ---------------------------------------------------------------

class TexturePage(QWidget):
    changed = Signal()

    def __init__(self, library=None, import_texture: Callable[[], list[str]] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.library = library
        self._import = import_texture
        lay = QVBoxLayout(self)
        lay.addWidget(_title(self.tr("2. Welche Textur sollen deine Rampen haben?")))
        lay.addWidget(_hint(self.tr("Vorgewählt ist die Textur, die zum Welt-Stil passt. Du kannst auch eigene Farben "
                                    "mischen, jede Textur des Spiels nehmen oder ein eigenes Bild importieren. Rechts "
                                    "siehst du, wie Rampen damit aussehen. Die Form jeder Rampe wählst du beim Malen.")))
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.textures = _gallery(THUMB, rows=2)
        self._style_item = QListWidgetItem(self.tr("Passend zum Stil"))
        self._style_item.setData(Qt.UserRole, FROM_STYLE)
        self.textures.addItem(self._style_item)
        for name, ramp, lines, _wall in PRESETS:
            item = QListWidgetItem(_plain_icon(textured_ramp("gerade", ramp, lines, THUMB)), self.tr(name))
            item.setData(Qt.UserRole, (ramp, lines))
            self.textures.addItem(item)
        own = QListWidgetItem(_plain_icon(textured_ramp("gerade", (200, 200, 200), (255, 140, 40), THUMB)),
                              self.tr("Eigene Farben"))
        own.setData(Qt.UserRole, OWN)
        self.textures.addItem(own)
        #: Textur aus der Bibliothek (erscheint, sobald man eine gewählt hat)
        self._material_item: QListWidgetItem | None = None
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
        more = QHBoxLayout()
        self.pick_btn = QPushButton(self.tr("Andere Textur wählen …"))
        self.pick_btn.setToolTip(self.tr("Jede Textur des Spiels oder eine eigene, mit Suche"))
        self.import_btn = QPushButton(self.tr("Eigenes Bild importieren …"))
        self.import_btn.setToolTip(self.tr("PNG, JPG, TGA oder BMP wird zur Textur, die du gleich auf die Rampen legst"))
        self.import_btn.setVisible(import_texture is not None)
        more.addWidget(self.pick_btn)
        more.addWidget(self.import_btn)
        more.addStretch(1)
        left.addLayout(more)
        left.addStretch(1)
        body.addLayout(left, 1)
        right = QVBoxLayout()
        self.preview = RampPreview()
        right.addWidget(self.preview)
        self.material_label = _hint("")
        self.material_label.setFixedWidth(PREVIEW_SIZE.width())
        right.addWidget(self.material_label)
        right.addStretch(1)
        body.addLayout(right)
        lay.addLayout(body, 1)

        self.style: WorldStyle = STYLES[0]
        self.textures.currentItemChanged.connect(lambda *_: self._update())
        self.ramp_btn.changed.connect(self._update)
        self.lines_btn.changed.connect(self._update)
        self.pick_btn.clicked.connect(self.pick_texture)
        self.import_btn.clicked.connect(self.import_image)
        self.set_style(STYLES[0])
        self.textures.setCurrentRow(0)

    def set_style(self, style: WorldStyle) -> None:
        """Neuer Welt-Stil: Der Eintrag „Passend zum Stil“ zeigt dessen Rampenfarben."""
        self.style = style
        self._style_item.setIcon(_plain_icon(textured_ramp("gerade", style.ramp, style.lines, THUMB)))
        self._update()

    def _data(self):
        item = self.textures.currentItem()
        return item.data(Qt.UserRole) if item is not None else FROM_STYLE

    def material(self) -> str:
        """Gewählte Textur aus der Bibliothek, sonst "" (dann gelten die Farben)."""
        data = self._data()
        return data[1] if isinstance(data, tuple) and data and data[0] == MATERIAL else ""

    def colors_chosen(self) -> tuple[RGB, RGB]:
        data = self._data()
        if data == OWN:
            return self.ramp_btn.color(), self.lines_btn.color()
        if isinstance(data, tuple) and len(data) == 2 and data[0] != MATERIAL:
            return data
        return self.style.ramp, self.style.lines

    def texture_name(self) -> str:
        item = self.textures.currentItem()
        return item.text() if item is not None else ""

    def use_material(self, name: str) -> None:
        """`name` aus der Bibliothek als Rampentextur: eigener Eintrag in der Galerie, gleich gewählt."""
        if self._material_item is None:
            self._material_item = QListWidgetItem()
            self.textures.addItem(self._material_item)
        self._material_item.setText(name.rsplit("/", 1)[-1].lower())
        self._material_item.setToolTip(name)
        self._material_item.setIcon(_plain_icon(material_ramp("gerade", name, self.library, THUMB)))
        self._material_item.setData(Qt.UserRole, (MATERIAL, name))
        self.textures.setCurrentItem(self._material_item)
        self._update()

    def pick_texture(self) -> str:
        from .texture_picker import TexturePicker

        dlg = TexturePicker(self.library, self.material(), self)
        if dlg.exec() != QDialog.Accepted or not dlg.chosen():
            return ""
        self.use_material(dlg.chosen())
        return dlg.chosen()

    def import_image(self) -> str:
        names = self._import() if self._import is not None else []
        if not names:
            return ""
        self.use_material(names[-1])
        return names[-1]

    def _update(self) -> None:
        self.colors.setVisible(self._data() == OWN)
        ramp, lines = self.colors_chosen()
        material = self.material()
        self.material_label.setText(self.tr("Textur: {0}").format(material) if material else "")
        self.preview.show_ramps(list(PREVIEW_KINDS), ramp, lines, self.style, material, self.library)
        self.changed.emit()


# ---- Schritt 3: Strecke (mit Plan) -----------------------------------------------------------

def _big_choice(text: str, hint: str) -> QRadioButton:
    b = QRadioButton(text)
    b.setToolTip(hint)
    f = b.font()
    f.setBold(True)
    b.setFont(f)
    return b


class LayoutPlan(QWidget):
    """Plan der Map von oben: Räume (freier Platz für Rampen), Start, Ziel und Teleporter mit Namen."""

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
            if item.kind == "room":
                # Ein Raum: freier Platz, in den man die Rampen selbst malt
                p.setPen(QPen(QColor(255, 140, 40, 200), 1.5, Qt.DashLine))
                p.setBrush(QColor(255, 140, 40, 22))
                p.drawRect(rect(item.rect).adjusted(2, 2, -2, -2))
                continue
            if item.kind == "space":
                # Leerer Platz, auf den man die Rampen selbst malt
                p.setPen(QPen(QColor(255, 140, 40, 200), 1.5, Qt.DashLine))
                p.setBrush(QColor(255, 140, 40, 28))
            else:
                color = PLAN_COLORS.get(item.kind, PLAN_COLORS["platform"])
                p.setPen(QPen(color.darker(160), 1))
                p.setBrush(color)
            p.drawRoundedRect(rect(item.rect), 3, 3)
        p.setPen(QColor(255, 190, 120))
        for item in self.items:
            if item.kind == "room" and item.label:
                p.drawText(rect(item.rect).adjusted(6, 4, -6, -4), Qt.AlignTop | Qt.AlignLeft, item.label)
        p.setPen(QColor(235, 238, 242))
        for item in self.items:
            if item.kind in ("start", "stage", "end", "teleport") and item.label:
                r = rect(item.rect)
                p.drawText(QRectF(r.left() - 40, r.bottom() + 2, r.width() + 80, 16), Qt.AlignHCenter | Qt.AlignTop,
                           item.label)
        if self.error:
            p.setPen(QColor(255, 120, 80))
            p.drawText(self.rect().adjusted(8, 8, -8, -8), Qt.AlignTop | Qt.AlignLeft | Qt.TextWordWrap, self.error)
        p.end()


class _Course:
    """Eine Zeile der Liste: Stage oder Bonus mit Name und Raumgröße."""

    def __init__(self, track: int, item: QTreeWidgetItem, name: QLineEdit, size: QComboBox) -> None:
        self.track = track
        self.item = item
        self.name = name
        self.size = size


class CoursePage(QWidget):
    changed = Signal()

    def __init__(self, game: str | None = None, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_title(self.tr("3. Wie soll deine Strecke sein?")))
        lay.addWidget(_hint(self.tr("Jede Stage und jeder Bonus bekommt einen eigenen Raum. Darin steht nur der Start "
                                    "und das Ziel, dazwischen ist alles frei: Du malst die Rampen in jede Richtung, "
                                    "mit Kurven, wie du willst. Wer fällt, startet den Raum neu. Eine lineare Map ist "
                                    "ein einziger großer Raum.")))
        top = QHBoxLayout()
        self.staged = _big_choice(self.tr("Mit Stages"), self.tr("Jede Stage ein eigener Raum, mit Teleporter zur nächsten"))
        self.linear = _big_choice(self.tr("Linear"), self.tr("Eine durchgehende Strecke in einem großen Raum"))
        group = QButtonGroup(self)
        group.addButton(self.staged)
        group.addButton(self.linear)
        self.staged.setChecked(True)
        top.addWidget(self.staged)
        top.addWidget(self.linear)
        top.addSpacing(24)
        top.addWidget(QLabel(self.tr("Spiel")))
        self.game = QComboBox()
        for key, name in GAMES:
            self.game.addItem(self.tr(name), key)
        self.game.setCurrentIndex(max(0, self.game.findData(game or "")))
        top.addWidget(self.game)
        top.addStretch(1)
        lay.addLayout(top)

        body = QHBoxLayout()
        left = QVBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([self.tr("Name"), self.tr("Raumgröße")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumWidth(400)
        left.addWidget(self.tree, 1)
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
        #: Stages vor dem Umschalten auf linear, damit „Mit Stages“ sie zurückbringt
        self._saved_stages: list[RoomSpec] = []
        for _ in range(3):
            self._insert(0, RoomSpec())
        self.staged.toggled.connect(self._kind_toggled)
        self.game.currentIndexChanged.connect(lambda *_: self.changed.emit())
        self.add_stage.clicked.connect(lambda: self._add(0))
        self.remove_stage.clicked.connect(lambda: self._remove(0))
        self.add_bonus.clicked.connect(lambda: self._add(1))
        self.remove_bonus.clicked.connect(lambda: self._remove(1))
        self._relabel()

    # Zeilen ------------------------------------------------------------------------------
    def is_linear(self) -> bool:
        return self.linear.isChecked()

    def _of(self, bonus: bool) -> list[_Course]:
        return [c for c in self.courses if bool(c.track) == bonus]

    def _label(self, course: _Course) -> str:
        if course.track:
            return self.tr("Bonus {0}").format(self._of(True).index(course) + 1)
        if self.is_linear():
            return self.tr("Strecke")
        return self.tr("Stage {0}").format(self._of(False).index(course) + 1)

    def _relabel(self) -> None:
        for c in self.courses:
            c.name.setPlaceholderText(self._label(c))
        stages = len(self._of(False))
        linear = self.is_linear()
        self.add_stage.setVisible(not linear)
        self.remove_stage.setVisible(not linear)
        self.add_stage.setEnabled(stages < MAX_STAGES)
        self.remove_stage.setEnabled(stages > 1)
        self.add_bonus.setEnabled(len(self._of(True)) < MAX_BONUSES)
        self.remove_bonus.setEnabled(bool(self._of(True)))

    def _size_combo(self, big: bool, size: int) -> QComboBox:
        combo = QComboBox()
        for name, edge, _height in (LINEAR_ROOMS if big else STAGE_ROOMS):
            combo.addItem(self.tr("{0} ({1} × {1})").format(self.tr(name), edge), edge)
        index = combo.findData(size)
        combo.setCurrentIndex(index if index >= 0 else 1 if not big else 0)
        combo.currentIndexChanged.connect(lambda *_: self.changed.emit())
        return combo

    def _insert(self, track: int, spec: RoomSpec) -> None:
        index = len(self.courses) if track else len(self._of(False))
        item = QTreeWidgetItem()
        self.tree.insertTopLevelItem(index, item)
        name = QLineEdit(spec.name)
        name.textChanged.connect(lambda *_: self.changed.emit())
        size = self._size_combo(self.is_linear() and not track, spec.size)
        course = _Course(1 if track else 0, item, name, size)
        self.courses.insert(index, course)
        self.tree.setItemWidget(item, 0, name)
        self.tree.setItemWidget(item, 1, size)

    def _take(self, course: _Course) -> RoomSpec:
        spec = RoomSpec(course.name.text().strip(), course.size.currentData())
        self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(course.item))
        self.courses.remove(course)
        return spec

    def _add(self, track: int) -> None:
        self._insert(track, RoomSpec(size=STAGE_ROOMS[0][1] if track else STAGE_ROOMS[1][1]))
        self._relabel()
        self.changed.emit()

    def _remove(self, track: int) -> None:
        rows = self._of(bool(track))
        if rows and (track or len(rows) > 1):
            self._take(rows[-1])
            self._relabel()
            self.changed.emit()

    def _kind_toggled(self, staged: bool) -> None:
        """Linear: ein großer Raum statt der Stages (die Stages kommen beim Zurückschalten wieder)."""
        mains = self._of(False)
        if staged:
            first = self._take(mains[0])
            for spec in self._saved_stages or [RoomSpec(first.name), RoomSpec(), RoomSpec()]:
                self._insert(0, spec)
        else:
            self._saved_stages = [self._take(c) for c in mains]
            self._insert(0, RoomSpec(self._saved_stages[0].name, LINEAR_ROOMS[0][1]))
        self._relabel()
        self.changed.emit()

    def specs(self) -> tuple[tuple[RoomSpec, ...], tuple[RoomSpec, ...]]:
        stages, bonuses = [], []
        for c in self.courses:
            spec = RoomSpec(c.name.text().strip(), c.size.currentData())
            (bonuses if c.track else stages).append(spec)
        return tuple(stages), tuple(bonuses)

    def settings(self) -> RoomMapSettings:
        stages, bonuses = self.specs()
        return RoomMapSettings(game=self.game.currentData() or None, stages=stages, bonuses=bonuses,
                               linear=self.is_linear())

    def show_plan(self) -> str:
        items, error = plan_room_map(self.settings())
        self.plan.set_plan(items, error)
        if error:
            self.size_label.setText(self.tr("So geht es nicht: {0}").format(error))
            self.size_label.setStyleSheet("color: #e85; font-weight: bold;")
        else:
            rooms = [i for i in items if i.kind == "room"]
            xs = [c for i in rooms for c in (i.rect[0], i.rect[2])]
            ys = [c for i in rooms for c in (i.rect[1], i.rect[3])]
            text = (self.tr("✓ Passt: 1 Raum") if len(rooms) == 1
                    else self.tr("✓ Passt: {0} Räume").format(len(rooms)))
            self.size_label.setText(text + self.tr(", zusammen etwa {0} × {1} Units (Source erlaubt 32768)").format(
                round(max(xs) - min(xs)), round(max(ys) - min(ys))))
            self.size_label.setStyleSheet("color: #6c6; font-weight: bold;")
        return error


# ---- Schritt 4: Bauen ---------------------------------------------------------------------

class BuildPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_title(self.tr("4. Alles bereit")))
        lay.addWidget(_hint(self.tr("„Map bauen“ legt für jede Stage einen Raum an, mit Start, Ziel, Zonen und "
                                    "Teleportern, und eine dichte Skybox. Danach malst du deine Rampen in die Räume, "
                                    "jede mit der Form und Richtung, die du gerade willst, und schiebst das Ziel "
                                    "dorthin, wo deine Strecke endet. Eine Leiste oben im Fenster sagt dir, was als "
                                    "Nächstes kommt.")))
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        self.summary.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        left.addWidget(self.summary)
        self.plan = LayoutPlan()
        left.addWidget(self.plan, 1)
        body.addLayout(left, 1)
        self.preview = RampPreview(QSize(300, 210))
        body.addWidget(self.preview, 0, Qt.AlignTop)
        lay.addLayout(body, 1)


# ---- Der Assistent ---------------------------------------------------------------------

class EasyModeWizard(QDialog):
    def __init__(self, game: str | None = None, parent=None, library=None,
                 import_texture: Callable[[], list[str]] | None = None) -> None:
        super().__init__(parent)
        self.library = library
        self.setWindowTitle(self.tr("Easy Mode: neue Map Schritt für Schritt"))
        self.resize(1120, 700)
        outer = QHBoxLayout(self)
        self.steps = QListWidget()
        self.steps.setFixedWidth(170)
        self.steps.setStyleSheet(
            "QListWidget { border: none; background: transparent; font-size: 11pt; }"
            f"QListWidget::item {{ padding: 10px 6px; }} QListWidget::item:selected {{ color: {ACTIVE}; "
            "font-weight: bold; background: rgba(255,140,40,0.12); border-radius: 6px; }")
        for name in STEPS:
            self.steps.addItem(self.tr(name))
        outer.addWidget(self.steps)
        main = QVBoxLayout()
        self.stack = QStackedWidget()
        self.style_page = StylePage()
        self.texture = TexturePage(library, import_texture)
        self.course = CoursePage(game)
        self.build = BuildPage()
        for page in (self.style_page, self.texture, self.course, self.build):
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
        self.steps.currentRowChanged.connect(self.go)
        self.style_page.changed.connect(lambda: self.texture.set_style(self.style_page.style()))
        self.course.changed.connect(self._plan_timer.start)
        self._update_plan()
        self.go(0)

    # Navigation -----------------------------------------------------------------------
    def go(self, index: int) -> None:
        index = max(0, min(index, self.stack.count() - 1))
        self.stack.setCurrentIndex(index)
        self.steps.blockSignals(True)
        self.steps.setCurrentRow(index)
        self.steps.blockSignals(False)
        for i in range(self.steps.count()):
            self.steps.item(i).setText(f"{'✓' if i < index else i + 1}  {self.tr(STEPS[i])}")
        last = index == self.stack.count() - 1
        self.back_btn.setEnabled(index > 0)
        self.next_btn.setText(self.tr("Map bauen") if last else self.tr("Weiter →"))
        if index >= 2:
            self._update_plan()
        if last:
            self._update_summary()
        self._update_next()

    def _next(self) -> None:
        if self.stack.currentIndex() == self.stack.count() - 1:
            if not self._error:
                self.accept()
            return
        self.go(self.stack.currentIndex() + 1)

    def _update_next(self) -> None:
        self.next_btn.setEnabled(not (self._error and self.stack.currentIndex() >= 2))

    def settings(self) -> RoomMapSettings:
        return self.course.settings()

    def _update_plan(self) -> None:
        self._error = self.course.show_plan()
        self._update_next()

    def _update_summary(self) -> None:
        stages, bonuses = self.course.specs()
        ramp, lines = self.texture.colors_chosen()
        style = self.style_page.style()
        names = ", ".join(spec.name or self.tr("Stage {0}").format(i) for i, spec in enumerate(stages, 1))
        rows = [
            (self.tr("Welt-Stil"), self.tr(style.name)),
            (self.tr("Rampentextur"), self.texture.texture_name()),
            (self.tr("Strecke"), self.tr("Linear") if self.course.is_linear()
             else self.tr("{0} Stages: {1}").format(len(stages), names)),
            (self.tr("Bonusse"), ", ".join(b.name or self.tr("Bonus {0}").format(i) for i, b in enumerate(bonuses, 1))
             or self.tr("keine")),
            (self.tr("Spiel"), self.course.game.currentText()),
        ]
        self.build.summary.setText("<table cellspacing=6>" + "".join(
            f"<tr><td><b>{k}</b></td><td>{v}</td></tr>" for k, v in rows) + "</table>")
        self.build.preview.show_ramps(list(PREVIEW_KINDS), ramp, lines, style, self.texture.material(), self.library)
        self.build.plan.set_plan(self.course.plan.items, self.course.plan.error)

    def choice(self) -> EasyResult:
        ramp, lines = self.texture.colors_chosen()
        return EasyResult(ramp, lines, self.style_page.style().key, self.settings(), material=self.texture.material())


def style_of(result: EasyResult) -> WorldStyle:
    return STYLE_BY_KEY.get(result.style, STYLES[0])


__all__ = ["STEPS", "EasyModeWizard", "EasyResult", "LayoutPlan", "RampPreview", "style_of"]
