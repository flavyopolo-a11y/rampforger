"""Werkzeug-Optionen: zeigt passende Einstellungen für das aktive Werkzeug."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.geometry.displacement import BRUSH_MODES
from ...core.materials import texturing
from ...core.models.scatter import KITS, KITS_BY_KEY, STYLE_KITS
from ...core.surf.catalog import CATALOG
from ...core.terrain import POWER_LABELS
from ..editor import EditorContext
from ..icons import icon
from ..tools.entity_tool import POINT_ENTITIES, EntityTool
from ..tools.face_tool import FaceTool
from ..tools.scatter_tool import FROM_BROWSER, ScatterTool
from ..tools.shape_tool import SHAPE_HINTS, SHAPES, ShapeTool
from ..tools.terrain_tool import MODE_HELP, MODE_LABELS, TerrainTool
from ..widgets.scope_switch import ScopeSwitch
from ..widgets.template_preview import render, template_faces, template_icon
from .library_panel import CATEGORY_ICONS

#: Bildgröße in der Vorlagen-Galerie des Malen-Werkzeugs und der großen Vorschau
PAINT_ICON = 64
PAINT_PREVIEW = (240, 170)


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet("color: #9aa4b2;")
    return label


class ToolOptionsPanel(QStackedWidget):
    def __init__(self, editor: EditorContext, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        self._pages: dict[str, QWidget] = {}
        self._add("select", self._select_page())
        self._add("shape", self._shape_page())
        self._add("entity", self._entity_page())
        if "face" in editor.tools:
            self._add("face", self._face_page())
        if "terrain" in editor.tools:
            self._add("terrain", self._terrain_page())
        if "vertex" in editor.tools:
            self._add("vertex", self._vertex_page())
        if "wall" in editor.tools:
            self._add("wall", self._wall_page())
        if "path" in editor.tools:
            self._add("path", self._path_page())
        if "decal" in editor.tools:
            self._add("decal", self._sticker_page())
        if "cordon" in editor.tools:
            self._add("cordon", self._cordon_page())
        editor.tool_changed.connect(self._on_tool)

    def _add(self, name: str, page: QWidget) -> None:
        self._pages[name] = page
        self.addWidget(page)

    def _on_tool(self, name: str) -> None:
        if name in self._pages:
            self.setCurrentWidget(self._pages[name])

    # ---- Auswahl ------------------------------------------------------------------
    def _select_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lock = QCheckBox(self.tr("Texturen mitführen (Texture Lock)"))
        lock.setChecked(self.editor.texture_lock)
        lock.setToolTip(self.tr("Beim Verschieben, Drehen und Skalieren bleibt die Textur an der Fläche haften."))
        lock.toggled.connect(lambda v: setattr(self.editor, "texture_lock", v))
        lay.addWidget(lock)
        row = QHBoxLayout()
        for axis, label in ((0, "X"), (1, "Y"), (2, "Z")):
            b = QPushButton(self.tr("Spiegeln {0}").format(label))
            b.setToolTip(self.tr("Auswahl an ihrer Mitte entlang {0} spiegeln").format(label))
            b.clicked.connect(lambda _=False, a=axis: self.editor.mirror_selection(a))
            row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(_hint(self.tr(
            "Klick wählt aus, Strg+Klick ergänzt. Auswahl ziehen verschiebt sie, Shift+Ziehen kopiert. "
            "Ein zweiter Klick auf die Auswahl schaltet zwischen Skalier- und Drehgriffen um. "
            "Pfeiltasten verschieben um eine Rasterweite. Exakte Werte: Strg+M."
        )))
        lay.addStretch(1)
        return w

    # ---- Aufkleber ----------------------------------------------------------------------
    def _sticker_page(self) -> QWidget:
        opts = self.editor.tools["decal"].options  # type: ignore[attr-defined]
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        group = QButtonGroup(w)
        self.sticker_modes: dict[str, QPushButton] = {}
        for key, label, tip in (("overlay", "Overlay", "Beliebige Größe, jedes Material (auch Wege, Schilder)"),
                                ("decal", "Decal", "Bild aus decals/ in Originalgröße, z. B. Graffiti, Risse")):
            b = QPushButton(self.tr(label))
            b.setCheckable(True)
            b.setChecked(opts.mode == key)
            b.setToolTip(self.tr(tip))
            b.clicked.connect(lambda _=False, k=key: (setattr(opts, "mode", k), size.setEnabled(k == "overlay")))
            group.addButton(b)
            row.addWidget(b)
            self.sticker_modes[key] = b
        lay.addLayout(row)
        form = QFormLayout()
        size = QSpinBox()
        size.setRange(8, 4096)
        size.setSingleStep(16)
        size.setSuffix(" u")
        size.setValue(opts.size)
        size.setEnabled(opts.mode == "overlay")
        size.setToolTip(self.tr("Längere Seite des Overlays; das Seitenverhältnis kommt vom Bild"))
        size.valueChanged.connect(lambda v: setattr(opts, "size", v))
        self.sticker_size = size
        form.addRow(self.tr("Größe"), size)
        lay.addLayout(form)
        lay.addWidget(_hint(self.tr(
            "Material im Material-Browser wählen (Suche „decals“ oder „overlays“) und in der 3D-Ansicht auf eine "
            "Fläche klicken. Overlays über mehrere Brushes werden auf alle Flächen in derselben Ebene geklebt und "
            "wandern beim Verschieben mit.")))
        lay.addStretch(1)
        return w

    # ---- Bereich (Cordon) -------------------------------------------------------------
    def _cordon_page(self) -> QWidget:
        ed = self.editor
        w = QWidget()
        lay = QVBoxLayout(w)
        self.cordon_on = QCheckBox(self.tr("Nur den Bereich bauen"))
        self.cordon_on.setToolTip(self.tr("Aus: Der Bereich bleibt gespeichert, gebaut wird die ganze Map"))
        self.cordon_size = QLabel()
        row = QHBoxLayout()
        from_sel = QPushButton(self.tr("Um Auswahl"))
        from_sel.setToolTip(self.tr("Bereich um die ausgewählten Objekte legen, mit 64 Units Luft"))
        from_sel.clicked.connect(lambda: ed.cordon_from_selection())
        clear = QPushButton(self.tr("Löschen"))
        clear.clicked.connect(lambda: ed.set_cordon(None))
        row.addWidget(from_sel)
        row.addWidget(clear)

        def sync() -> None:
            box, on = ed.cordon()
            self.cordon_on.blockSignals(True)
            self.cordon_on.setChecked(box is not None and on)
            self.cordon_on.setEnabled(box is not None)
            self.cordon_on.blockSignals(False)
            clear.setEnabled(box is not None)
            self.cordon_size.setText(self.tr("Kein Bereich: es wird die ganze Map gebaut") if box is None else
                                     self.tr("Bereich: {0}").format(" × ".join(
                                         f"{b - a:.0f}" for a, b in zip(box.mins, box.maxs))))

        def toggled(on: bool) -> None:
            box, _ = ed.cordon()
            if box is not None:
                ed.set_cordon(box, on)
        self.cordon_on.toggled.connect(toggled)
        ed.cordon_changed.connect(sync)
        ed.document_replaced.connect(sync)
        sync()
        lay.addWidget(self.cordon_on)
        lay.addWidget(self.cordon_size)
        lay.addLayout(row)
        lay.addWidget(_hint(self.tr(
            "Große Maps brauchen zum Kompilieren lange. Zieh in einer 2D-Ansicht ein Rechteck um den Teil, an dem "
            "du gerade baust: Nur der wird kompiliert und automatisch mit Skybox abgedichtet. Kanten ziehen ändert "
            "die Größe, innen ziehen verschiebt, Entf löscht. Die Map selbst bleibt unverändert.")))
        lay.addStretch(1)
        return w

    # ---- Wände -----------------------------------------------------------------------
    def _wall_page(self) -> QWidget:
        opts = self.editor.tools["wall"].options  # type: ignore[attr-defined]
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()

        def spin(attr: str, lo: int, hi: int, step: int, tip: str) -> QSpinBox:
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setSuffix(" u")
            s.setValue(getattr(opts, attr))
            s.setToolTip(self.tr(tip))
            s.valueChanged.connect(lambda v: (setattr(opts, attr, v), self.editor.redraw_requested.emit()))
            return s

        self.wall_height = spin("height", 8, 16384, 16, "Höhe der Wände")
        self.wall_thickness = spin("thickness", 2, 1024, 8, "Dicke der Wände")
        self.wall_bottom = spin("bottom", -16384, 16384, 16, "Unterkante; in 3D setzt der erste Klick sie automatisch")
        form.addRow(self.tr("Höhe"), self.wall_height)
        form.addRow(self.tr("Dicke"), self.wall_thickness)
        form.addRow(self.tr("Unterkante"), self.wall_bottom)

        def sync_bottom() -> None:
            # Der erste Klick in 3D setzt die Unterkante: Feld nachziehen
            if self.wall_bottom.value() != opts.bottom:
                self.wall_bottom.blockSignals(True)
                self.wall_bottom.setValue(opts.bottom)
                self.wall_bottom.blockSignals(False)
        self.editor.redraw_requested.connect(sync_bottom)
        group = QCheckBox(self.tr("Wände als Gruppe"))
        group.setChecked(opts.group)
        group.toggled.connect(lambda v: setattr(opts, "group", v))
        form.addRow("", group)
        lay.addLayout(form)
        lay.addWidget(_hint(self.tr(
            "In „Oben“ oder in 3D Punkte klicken. Die Wände stoßen an den Ecken sauber aneinander. "
            "Klick auf den ersten Punkt schließt den Raum, Enter oder ein zweiter Klick auf den letzten "
            "Punkt beendet. Rücktaste nimmt den letzten Punkt zurück, Esc verwirft. "
            "Material: das aktuelle aus dem Material-Browser."
        )))
        lay.addStretch(1)
        return w

    # ---- Pfad ------------------------------------------------------------------------
    def _path_page(self) -> QWidget:
        opts = self.editor.tools["path"].options  # type: ignore[attr-defined]
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        self.path_class = QComboBox()
        self.path_class.addItem(self.tr("path_track (Züge, Plattformen)"), "path_track")
        self.path_class.addItem(self.tr("path_corner (NPCs, func_train)"), "path_corner")
        self.path_class.currentIndexChanged.connect(
            lambda _i: setattr(opts, "classname", self.path_class.currentData()))
        form.addRow(self.tr("Art"), self.path_class)
        self.path_name = QLineEdit(opts.base)
        self.path_name.setToolTip(self.tr("Die Punkte heißen <Name>_1, <Name>_2 …"))
        self.path_name.textChanged.connect(lambda t: setattr(opts, "base", t.strip() or "pfad"))
        form.addRow(self.tr("Name"), self.path_name)
        self.path_height = QSpinBox()
        self.path_height.setRange(-16384, 16384)
        self.path_height.setSingleStep(16)
        self.path_height.setSuffix(" u")
        self.path_height.setValue(opts.height)
        self.path_height.setToolTip(self.tr("In 3D: Abstand über der angeklickten Fläche. In „Oben“: Höhe des "
                                            "ersten Punkts"))
        self.path_height.valueChanged.connect(lambda v: setattr(opts, "height", v))
        form.addRow(self.tr("Höhe"), self.path_height)
        self.path_speed = QSpinBox()
        self.path_speed.setRange(0, 10000)
        self.path_speed.setSingleStep(50)
        self.path_speed.setSpecialValueText(self.tr("vom Zug"))
        self.path_speed.setValue(opts.speed)
        self.path_speed.valueChanged.connect(lambda v: setattr(opts, "speed", v))
        form.addRow(self.tr("Tempo"), self.path_speed)
        lay.addLayout(form)
        lay.addWidget(_hint(self.tr(
            "Punkte in einer beliebigen Ansicht klicken. Jeder Punkt zeigt auf den nächsten, die Namen "
            "stimmen automatisch. Klick auf den ersten Punkt macht einen Rundkurs, Enter oder ein zweiter "
            "Klick auf den letzten Punkt beendet, Rücktaste nimmt zurück, Esc verwirft. Einen Zug "
            "(func_tracktrain) lässt man dann mit „Erstes Ziel“ = <Name>_1 fahren."
        )))
        lay.addStretch(1)
        return w

    # ---- Ecken -----------------------------------------------------------------------
    def _vertex_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(_hint(self.tr(
            "Weiße Griffe sind Ecken, gelbe die Mitten der Kanten (ziehen bewegt beide Ecken), rot ist gewählt. "
            "Strg+Klick ergänzt, ein Rahmen wählt mehrere Ecken. Pfeiltasten schieben um eine Rasterweite, "
            "in 3D hebt Shift+Ziehen senkrecht.\n\n"
            "Der Brush bleibt immer konvex: Was ihn hohl machen würde, wird abgelehnt. Fallen zwei Ecken "
            "zusammen, verschmelzen sie, so entstehen Keile und Spitzen."
        )))
        lay.addStretch(1)
        return w

    # ---- Gelände ---------------------------------------------------------------------
    def _terrain_page(self) -> QWidget:
        tool: TerrainTool = self.editor.tools["terrain"]  # type: ignore[assignment]
        w = QWidget()
        lay = QVBoxLayout(w)
        grid = QGridLayout()
        grid.setSpacing(4)
        group = QButtonGroup(w)
        group.setExclusive(True)
        self.terrain_modes: dict[str, QToolButton] = {}
        for i, mode in enumerate(BRUSH_MODES):
            b = QToolButton()
            b.setText(self.tr(MODE_LABELS[mode]))
            b.setCheckable(True)
            b.setMinimumWidth(80)
            b.setToolTip(self.tr(MODE_HELP[mode]))
            b.clicked.connect(lambda _=False, m=mode: tool.set_mode(m))
            group.addButton(b)
            grid.addWidget(b, i // 3, i % 3)
            self.terrain_modes[mode] = b
        self.terrain_modes[tool.mode].setChecked(True)
        lay.addLayout(grid)
        form = QFormLayout()
        self.terrain_radius = QSpinBox()
        self.terrain_radius.setRange(8, 2048)
        self.terrain_radius.setSingleStep(16)
        self.terrain_radius.setSuffix(" u")
        self.terrain_radius.setValue(int(tool.radius))
        self.terrain_radius.setToolTip(self.tr("Halbmesser des Pinsels. Tasten [ und ] ändern ihn beim Malen."))
        self.terrain_radius.valueChanged.connect(lambda v: setattr(tool, "radius", float(v)))
        form.addRow(self.tr("Größe"), self.terrain_radius)
        self.terrain_strength = QSpinBox()
        self.terrain_strength.setRange(1, 255)
        self.terrain_strength.setValue(int(tool.strength))
        self.terrain_strength.setToolTip(self.tr(
            "Wie stark ein Abdruck wirkt: Units beim Heben und Senken, Stufen von 255 beim Textur-Malen"))
        self.terrain_strength.valueChanged.connect(lambda v: setattr(tool, "strength", float(v)))
        form.addRow(self.tr("Stärke"), self.terrain_strength)
        lay.addLayout(form)
        tool.on_change = lambda: self.terrain_radius.setValue(int(tool.radius))

        box = QHBoxLayout()
        power = QComboBox()
        for p, label in POWER_LABELS.items():
            power.addItem(self.tr(label), p)
        power.setCurrentIndex(list(POWER_LABELS).index(tool.power))
        power.setToolTip(self.tr("Wie fein das neue Gelände ist. 8 × 8 reicht meist; feiner kostet Leistung."))
        power.currentIndexChanged.connect(lambda _: setattr(tool, "power", power.currentData()))
        make = QPushButton(self.tr("Zu Gelände machen"))
        make.setToolTip(self.tr("Die Oberseite der ausgewählten Brushes wird formbares Gelände (Displacement)"))
        make.clicked.connect(tool.convert_selection)
        box.addWidget(make, 1)
        box.addWidget(power)
        lay.addLayout(box)
        row = QHBoxLayout()
        sew = QPushButton(self.tr("Nähte schließen"))
        sew.setToolTip(self.tr("Lücken zwischen benachbarten Gelände-Flächen schließen (passiert nach jedem Strich "
                               "von selbst)"))
        sew.clicked.connect(tool.sew)
        flat = QPushButton(self.tr("Gelände entfernen"))
        flat.setToolTip(self.tr("Die ausgewählten Brushes werden wieder normale Brushes"))
        flat.clicked.connect(tool.flatten_selection)
        row.addWidget(sew)
        row.addWidget(flat)
        lay.addLayout(row)
        lay.addWidget(_hint(self.tr(
            "In 3D über das Gelände ziehen, oder in 2D von oben. Shift kehrt um (Heben ↔ Senken). "
            "Textur malen braucht ein Überblend-Material mit zwei Texturen, z. B. nature/blendgrassgravel001a. "
            "Fertige Hügel, Berge und Felsen gibt es links in der Bibliothek unter „Gelände“."
        )))
        lay.addStretch(1)
        return w

    # ---- Streuen -------------------------------------------------------------------------
    def add_scatter_page(self) -> None:
        """Erst nach dem Modell-Browser möglich (das Werkzeug braucht ihn)."""
        if "scatter" in self.editor.tools and "scatter" not in self._pages:
            self._add("scatter", self._scatter_page())

    def add_paint_page(self, library) -> None:
        """Erst nach der Bibliothek möglich (das Malen-Werkzeug malt deren Vorlagen)."""
        if "paint" in self.editor.tools and "paint" not in self._pages:
            self._add("paint", self._paint_page(library))

    def _paint_page(self, library) -> QWidget:
        """Malen: alle Vorlagen als Bilder zum Anklicken, darunter die gewählte groß."""
        w = QWidget()
        lay = QVBoxLayout(w)
        category = QComboBox()
        category.addItem(self.tr("Alle"), "")
        for cat in dict.fromkeys(t.category for t in CATALOG.values()):
            category.addItem(icon(CATEGORY_ICONS.get(cat, "shape")), self.tr(cat), cat)
        gallery = QListWidget()
        gallery.setViewMode(QListWidget.IconMode)
        gallery.setIconSize(QSize(PAINT_ICON, PAINT_ICON))
        gallery.setGridSize(QSize(PAINT_ICON + 24, PAINT_ICON + 30))
        gallery.setResizeMode(QListWidget.Adjust)
        gallery.setMovement(QListWidget.Static)
        gallery.setWordWrap(True)
        gallery.setMinimumHeight(PAINT_ICON * 2 + 70)
        items: dict[str, QListWidgetItem] = {}
        for t in CATALOG.values():
            item = QListWidgetItem(self.tr(t.name))
            item.setData(Qt.UserRole, t.key)
            item.setToolTip(self.tr(t.description))
            item.setIcon(icon(CATEGORY_ICONS.get(t.category, "shape")))
            gallery.addItem(item)
            items[t.key] = item
        self.paint_gallery = gallery
        self.paint_preview = QLabel()
        self.paint_preview.setAlignment(Qt.AlignCenter)
        self.paint_preview.setStyleSheet("background: #22252b; border-radius: 4px;")
        self.paint_preview.setFixedHeight(PAINT_PREVIEW[1])
        self.paint_name = QLabel()
        self.paint_name.setStyleSheet("font-weight: bold;")
        self.paint_name.setWordWrap(True)
        pending = list(items.items())
        timer = QTimer(w)

        def draw_icons() -> None:
            # Bilder nach und nach zeichnen, damit der Start nicht wartet
            for _ in range(4):
                if not pending:
                    timer.stop()
                    return
                key, item = pending.pop(0)
                item.setIcon(template_icon(key, PAINT_ICON * 2))

        def filter_category() -> None:
            cat = category.currentData()
            for key, item in items.items():
                item.setHidden(bool(cat) and CATALOG[key].category != cat)

        def picked(item: QListWidgetItem) -> None:
            library.select_template(item.data(Qt.UserRole))

        def sync() -> None:
            t = library.current_template()
            gallery.blockSignals(True)
            gallery.setCurrentItem(items.get(t.key) if t else None)
            gallery.blockSignals(False)
            if t is None:
                self.paint_name.setText(self.tr("Keine Vorlage gewählt"))
                self.paint_preview.clear()
                return
            if t.key in items:
                gallery.scrollToItem(items[t.key])
            self.paint_name.setText(self.tr(t.name))
            faces = template_faces(t, library.insert_values(t))
            self.paint_preview.setPixmap(render(faces, QSize(*PAINT_PREVIEW)))

        category.currentIndexChanged.connect(filter_category)
        gallery.itemClicked.connect(picked)
        library.template_changed.connect(sync)
        self.editor.tool_changed.connect(lambda name: sync() if name == "paint" else None)
        timer.timeout.connect(draw_icons)
        timer.start(0)
        sync()
        lay.addWidget(category)
        lay.addWidget(gallery, 1)
        lay.addWidget(self.paint_name)
        lay.addWidget(self.paint_preview)
        lay.addWidget(_hint(self.tr(
            "Vorlage anklicken, dann in einer Ansicht vom Anfang zum Ende der Rampe ziehen. Ein Klick setzt sie so ab, "
            "wie sie ist. Länge, Höhe, Winkel und Material stellst du links in der Bibliothek ein; das Bild zeigt "
            "sofort, wie die Rampe aussieht. Esc beendet das Malen.")))
        return w

    def _scatter_page(self) -> QWidget:
        tool: ScatterTool = self.editor.tools["scatter"]  # type: ignore[assignment]
        opts = tool.settings
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        self.scatter_source = QComboBox()
        self.scatter_source.addItem(self.tr("Modell aus dem Modell-Browser"), FROM_BROWSER)
        for kit in KITS:
            self.scatter_source.addItem(self.tr("Kit: {0}").format(self.tr(kit.name)), kit.key)
            self.scatter_source.setItemData(self.scatter_source.count() - 1, self.tr(kit.description), Qt.ToolTipRole)
        self.scatter_source.setToolTip(self.tr("Welche Modelle gestreut werden. Kits nehmen passende Modelle "
                                               "aus dem Spiel (CS:S und HL2)."))
        form.addRow(self.tr("Modelle"), self.scatter_source)
        lay.addLayout(form)
        self.scatter_list = QListWidget()
        self.scatter_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.scatter_list.setMaximumHeight(150)
        self.scatter_list.setToolTip(self.tr("Haken weg: dieses Modell nicht streuen"))
        lay.addWidget(self.scatter_list)
        self.scatter_info = _hint("")
        lay.addWidget(self.scatter_info)

        form2 = QFormLayout()

        def spin(value: float, lo: int, hi: int, step: int, suffix: str, attr: str, tip: str) -> QSpinBox:
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            sp.setSuffix(suffix)
            sp.setValue(int(value))
            sp.setToolTip(tip)
            sp.valueChanged.connect(lambda v: setattr(opts, attr, type(getattr(opts, attr))(v)))
            return sp

        self.scatter_radius = spin(opts.radius, 32, 4096, 32, " u", "radius",
                                   self.tr("Halbmesser des Streu-Kreises. Tasten [ und ]."))
        form2.addRow(self.tr("Kreis"), self.scatter_radius)
        form2.addRow(self.tr("Anzahl je Klick"), spin(opts.count, 1, 50, 1, "", "count",
                                                      self.tr("So viele Props höchstens je Klick")))
        form2.addRow(self.tr("Mindestabstand"), spin(opts.spacing, 0, 2048, 16, " u", "spacing",
                                                     self.tr("Abstand zu anderen Props, damit nichts ineinander steht")))
        form2.addRow(self.tr("Steilste Stelle"), spin(opts.max_slope, 0, 89, 5, "°", "max_slope",
                                                      self.tr("Steilere Flächen (Wände, Surf-Rampen) bleiben frei")))
        lay.addLayout(form2)
        self.scatter_align = QCheckBox(self.tr("Am Hang ausrichten"))
        self.scatter_align.setToolTip(self.tr("Props kippen mit dem Boden (gut für Felsen; Bäume besser aufrecht)"))
        self.scatter_align.toggled.connect(lambda v: setattr(opts, "align", v))
        lay.addWidget(self.scatter_align)
        only = QCheckBox(self.tr("Nur auf Gelände"))
        only.setToolTip(self.tr("Nur auf Displacements streuen, nicht auf Brushes"))
        only.toggled.connect(lambda v: setattr(opts, "terrain_only", v))
        lay.addWidget(only)
        lay.addWidget(_hint(self.tr(
            "In 3D oder von oben klicken bzw. ziehen. Shift entfernt die Props dieser Modelle im Kreis. "
            "Ein Strich ist ein Rückgängig-Schritt.")))
        lay.addStretch(1)

        def refresh_list() -> None:
            self.scatter_list.blockSignals(True)
            self.scatter_list.clear()
            if tool.source == FROM_BROWSER:
                name = tool.browser.current_name()
                self.scatter_info.setText(self.tr("Gestreut wird: {0}").format(name) if name
                                          else self.tr("Im Modell-Browser (unten) ein Modell anklicken"))
                self.scatter_list.hide()
            else:
                names = tool.kit_names()
                for n in names:
                    item = QListWidgetItem(n.removeprefix("models/"))
                    item.setData(Qt.UserRole, n)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked if n in tool.disabled else Qt.Checked)
                    self.scatter_list.addItem(item)
                self.scatter_list.setVisible(bool(names))
                kit = KITS_BY_KEY[tool.source]
                self.scatter_info.setText(
                    self.tr("{0} Modelle im Spiel gefunden").format(len(names)) if names else
                    self.tr("Kein passendes Modell gefunden. Ist ein Spielprofil gewählt?") if self.editor.models is None
                    else self.tr("Im Spiel gibt es keine Modelle für „{0}“").format(self.tr(kit.name)))
            self.scatter_list.blockSignals(False)
            self.scatter_align.setChecked(opts.align)
            self.scatter_radius.setValue(int(opts.radius))

        def toggled(item: QListWidgetItem) -> None:
            name = item.data(Qt.UserRole)
            if item.checkState() == Qt.Checked:
                tool.disabled.discard(name)
            else:
                tool.disabled.add(name)

        self.scatter_list.itemChanged.connect(toggled)
        self.scatter_source.currentIndexChanged.connect(lambda _: tool.set_source(self.scatter_source.currentData()))
        tool.on_change = refresh_list
        tool.browser.view.selectionModel().currentChanged.connect(lambda *_: refresh_list())
        self.editor.tool_changed.connect(lambda name: name == "scatter" and refresh_list())
        refresh_list()
        return w

    def suggest_kit(self, style_key: str) -> None:
        """Nach einem Welt-Stil das passende Kit vorwählen."""
        kit = STYLE_KITS.get(style_key)
        if kit and "scatter" in self._pages:
            self.scatter_source.setCurrentIndex(self.scatter_source.findData(kit))

    # ---- Seiten (Face-Editor) ------------------------------------------------------------
    def _face_page(self) -> QWidget:
        tool: FaceTool = self.editor.tools["face"]  # type: ignore[assignment]
        w = QWidget()
        lay = QVBoxLayout(w)
        self.face_info = QLabel()
        self.face_info.setWordWrap(True)
        lay.addWidget(self.face_info)
        lay.addWidget(ScopeSwitch(self.editor))
        apply = QPushButton(self.tr("Aktuelles Material anwenden"))
        apply.setToolTip(self.tr("Die ausgewählten Seiten bekommen das Material aus dem Material-Browser"))
        apply.clicked.connect(lambda: tool.apply_material(self.editor.current_material))
        lay.addWidget(apply)

        form = QFormLayout()
        fields: dict[str, QDoubleSpinBox | QSpinBox] = {}

        def dspin(lo: float, hi: float, step: float, decimals: int, suffix: str = "") -> QDoubleSpinBox:
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            sp.setDecimals(decimals)
            sp.setSuffix(suffix)
            sp.setKeyboardTracking(False)
            return sp

        fields["scale_u"] = dspin(0.01, 64, 0.05, 3)
        fields["scale_v"] = dspin(0.01, 64, 0.05, 3)
        fields["shift_u"] = dspin(-8192, 8192, 1, 1)
        fields["shift_v"] = dspin(-8192, 8192, 1, 1)
        fields["rotation"] = dspin(-360, 360, 15, 1, "°")
        lm = QSpinBox()
        lm.setRange(1, 128)
        lm.setKeyboardTracking(False)
        fields["lightmap"] = lm
        for key, label in (("scale_u", "Skalierung X"), ("scale_v", "Skalierung Y"), ("shift_u", "Verschiebung X"),
                           ("shift_v", "Verschiebung Y"), ("rotation", "Drehung"), ("lightmap", "Lightmap-Skalierung")):
            form.addRow(self.tr(label), fields[key])
        lay.addLayout(form)

        def changed(key: str, value: float) -> None:
            kw: dict = {
                "scale_u": {"scale": (value, None)}, "scale_v": {"scale": (None, value)},
                "shift_u": {"shift": (value, None)}, "shift_v": {"shift": (None, value)},
                "rotation": {"rotation": value}, "lightmap": {"lightmapscale": int(value)},
            }[key]
            tool.edit(lambda f: texturing.set_values(f, **kw), self.tr("Textur ausrichten"),
                      merge_key=("face", key, tuple(tool.faces)))

        for key, field in fields.items():
            field.valueChanged.connect(lambda v, k=key: changed(k, v))

        just = QHBoxLayout()
        for mode, label, tip in (("fit", "Einpassen", "Textur genau einmal auf die Seite strecken"),
                                 ("left", "L", "Linke Kante bündig"), ("right", "R", "Rechte Kante bündig"),
                                 ("top", "O", "Obere Kante bündig"), ("bottom", "U", "Untere Kante bündig"),
                                 ("center", "M", "Mittig")):
            b = QPushButton(self.tr(label))
            b.setToolTip(self.tr(tip))
            if len(label) == 1:
                b.setFixedWidth(30)
            b.clicked.connect(lambda _=False, m=mode: tool.per_face(
                lambda f, poly, size: texturing.justify(f, poly, size, m), self.tr("Textur ausrichten")))
            just.addWidget(b)
        lay.addLayout(just)
        align = QHBoxLayout()
        world = QPushButton(self.tr("An Welt ausrichten"))
        world.setToolTip(self.tr("Textur nach der Weltachse projizieren, wie bei neuen Brushes"))
        world.clicked.connect(lambda: tool.edit(texturing.align_world, self.tr("An Welt ausrichten")))
        face = QPushButton(self.tr("An Fläche ausrichten"))
        face.setToolTip(self.tr("Textur liegt flach auf der Seite, gut für Rampen und Schrägen"))
        face.clicked.connect(lambda: tool.edit(texturing.align_face, self.tr("An Fläche ausrichten")))
        align.addWidget(world)
        align.addWidget(face)
        lay.addLayout(align)
        lay.addWidget(_hint(self.tr(
            "In der 3D-Ansicht: Klick wählt eine Seite, Strg+Klick ergänzt. Shift+Klick gibt einer Seite "
            "sofort das aktuelle Material, Strg+Shift+Klick färbt dieses Material in der ganzen Map um, "
            "Alt+Klick nimmt das Material einer Seite auf.")))
        lay.addStretch(1)

        def refresh() -> None:
            sel = tool.selected()
            for f in fields.values():
                f.setEnabled(bool(sel))
            if not sel:
                self.face_info.setText(self.tr("Keine Seite ausgewählt"))
                return
            mats = {face.material for _r, face in sel}
            self.face_info.setText(self.tr("{0} Seite(n): {1}").format(
                len(sel), mats.pop() if len(mats) == 1 else self.tr("verschiedene Materialien")))
            f0 = sel[0][1]
            values = {"scale_u": f0.uaxis.scale, "scale_v": f0.vaxis.scale, "shift_u": f0.uaxis.offset,
                      "shift_v": f0.vaxis.offset, "rotation": f0.rotation, "lightmap": f0.lightmapscale}
            for key, field in fields.items():
                field.blockSignals(True)
                field.setValue(values[key])
                field.blockSignals(False)

        tool.signals.faces_changed.connect(refresh)
        refresh()
        return w

    # ---- Formen -------------------------------------------------------------------------
    def _shape_page(self) -> QWidget:
        tool: ShapeTool = self.editor.tools["shape"]  # type: ignore[assignment]
        opts = tool.options
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        # Formen als Bilder zum Anklicken, wie die Rampen in der Bibliothek
        gallery = QGridLayout()
        gallery.setSpacing(4)
        buttons = QButtonGroup(w)
        buttons.setExclusive(True)
        shape_buttons: dict[str, QToolButton] = {}
        for i, (key, label) in enumerate(SHAPES.items()):
            b = QToolButton()
            b.setIcon(icon(f"shape_{key}"))
            b.setIconSize(QSize(36, 36))
            b.setText(self.tr(label))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setCheckable(True)
            b.setMinimumWidth(64)
            b.setToolTip(self.tr(SHAPE_HINTS[key]))
            b.clicked.connect(lambda _=False, k=key: tool.set_shape(k))
            buttons.addButton(b)
            gallery.addWidget(b, i // 3, i % 3)
            shape_buttons[key] = b
        lay.addLayout(gallery)
        material = QLineEdit(self.editor.current_material)
        material.setToolTip(self.tr("Material für alle Seiten. Im Material-Browser per Doppelklick wählen."))
        material.editingFinished.connect(lambda: self.editor.set_current_material(material.text()))
        self.editor.current_material_changed.connect(material.setText)
        form.addRow(self.tr("Material"), material)

        def spin(value: int, lo: int, hi: int, attr: str, tip: str) -> QSpinBox:
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setValue(value)
            s.setToolTip(tip)
            s.valueChanged.connect(lambda v: setattr(opts, attr, v))
            return s

        def dspin(value: float, lo: float, hi: float, attr: str, tip: str) -> QDoubleSpinBox:
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(1)
            s.setValue(value)
            s.setSuffix("°")
            s.setToolTip(tip)
            s.valueChanged.connect(lambda v: setattr(opts, attr, v))
            return s

        sides = spin(opts.sides, 3, 64, "sides", self.tr("Anzahl Seiten bzw. Segmente"))
        wall = spin(opts.wall, 1, 1024, "wall", self.tr("Wandstärke des Bogens in Units"))
        arc = dspin(opts.arc, 1, 360, "arc", self.tr("Wie weit der Bogen reicht (360° = Ring)"))
        start = dspin(opts.start_angle, -360, 360, "start_angle", self.tr("Wo der Bogen beginnt"))
        steps = spin(opts.steps, 1, 128, "steps", self.tr("Anzahl Stufen"))
        stairs_dir = QComboBox()
        for d in ("+y", "-y", "+x", "-x"):
            stairs_dir.addItem(self.tr("steigt nach {0}").format(d), d)
        stairs_dir.currentIndexChanged.connect(lambda _: setattr(opts, "stairs_direction", stairs_dir.currentData()))
        wedge_high = QComboBox()
        for d in ("-y", "+y", "-x", "+x"):
            wedge_high.addItem(self.tr("hoch bei {0}").format(d), d)
        wedge_high.currentIndexChanged.connect(lambda _: setattr(opts, "wedge_high", wedge_high.currentData()))

        rows = {
            "sides": (self.tr("Seiten"), sides),
            "wall": (self.tr("Wandstärke"), wall),
            "arc": (self.tr("Bogenwinkel"), arc),
            "start": (self.tr("Startwinkel"), start),
            "steps": (self.tr("Stufen"), steps),
            "stairs_dir": (self.tr("Richtung"), stairs_dir),
            "wedge_high": (self.tr("Schräge"), wedge_high),
        }
        for label, widget in rows.values():
            form.addRow(label, widget)
        visible = {
            "block": set(),
            "wedge": {"wedge_high"},
            "cylinder": {"sides"},
            "arch": {"sides", "wall", "arc", "start"},
            "stairs": {"steps", "stairs_dir"},
            "spike": {"sides"},
            "sphere": {"sides"},
            "torus": {"sides", "wall"},
        }

        def on_shape(key: str) -> None:
            shape_buttons[key].setChecked(True)
            for name, (_, widget) in rows.items():
                form.setRowVisible(widget, name in visible[key])

        tool.signals.shape_changed.connect(on_shape)
        on_shape(opts.shape)
        lay.addLayout(form)
        create = QPushButton(self.tr("Erstellen (Enter)"))
        create.clicked.connect(tool.create)
        lay.addWidget(create)
        lay.addWidget(_hint(self.tr(
            "Rahmen in einer 2D-Ansicht aufziehen, Höhe in einer zweiten Ansicht anpassen, Enter drücken. "
            "In der 3D-Ansicht setzt ein Klick den Rahmen direkt auf die angeklickte Fläche."
        )))
        lay.addStretch(1)
        return w

    # ---- Entity ----------------------------------------------------------------------------
    def _entity_page(self) -> QWidget:
        tool: EntityTool = self.editor.tools["entity"]  # type: ignore[assignment]
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        combo = QComboBox()
        for cls, (label, _, _) in POINT_ENTITIES.items():
            combo.addItem(f"{self.tr(label)}  ({cls})", cls)
        form.addRow(self.tr("Schnell"), combo)
        search = QComboBox()
        search.setEditable(True)
        search.setInsertPolicy(QComboBox.NoInsert)
        search.completer().setFilterMode(Qt.MatchContains)
        search.completer().setCompletionMode(QCompleter.PopupCompletion)
        search.lineEdit().setPlaceholderText(self.tr("Alle Entities: Namen tippen …"))
        self._entity_classes_loaded = False

        def load_classes() -> None:
            if not self._entity_classes_loaded:
                self._entity_classes_loaded = True
                text = search.currentText()
                search.addItems(self.editor.entity_catalog.classnames("point"))
                search.setEditText(text)

        def choose(cls: str) -> None:
            cls = cls.strip()
            if not cls:
                return
            tool.classname = cls
            idx = combo.findData(cls)
            combo.blockSignals(True)
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
            info = self.editor.entity_catalog.get(cls)
            desc.setText(info.desc if info and info.desc else "")

        def quick(_: int) -> None:
            tool.classname = combo.currentData()
            search.setEditText("")
            info = self.editor.entity_catalog.get(tool.classname)
            desc.setText(info.desc if info and info.desc else "")

        combo.currentIndexChanged.connect(quick)
        search.lineEdit().textEdited.connect(lambda _: load_classes())
        search.activated.connect(lambda _: choose(search.currentText()))
        search.lineEdit().editingFinished.connect(lambda: choose(search.currentText()))
        form.addRow(self.tr("Suche"), search)
        lay.addLayout(form)
        desc = _hint("")
        lay.addWidget(desc)
        lay.addWidget(_hint(self.tr(
            "Klick in die 3D-Ansicht setzt die Entity auf die angeklickte Fläche, Klick in eine 2D-Ansicht "
            "an die Mausposition. Eigenschaften und Ausgänge stehen danach rechts im Panel Auswahl."
        )))
        lay.addStretch(1)
        self.entity_search = search
        self.entity_quick = combo
        return w

