"""Werkzeug-Optionen: zeigt passende Einstellungen für das aktive Werkzeug."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.materials import texturing
from ..editor import EditorContext
from ..icons import icon
from ..tools.entity_tool import POINT_ENTITIES, EntityTool
from ..tools.face_tool import FaceTool
from ..tools.shape_tool import SHAPE_HINTS, SHAPES, ShapeTool


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

    # ---- Seiten (Face-Editor) ------------------------------------------------------------
    def _face_page(self) -> QWidget:
        tool: FaceTool = self.editor.tools["face"]  # type: ignore[assignment]
        w = QWidget()
        lay = QVBoxLayout(w)
        self.face_info = QLabel()
        self.face_info.setWordWrap(True)
        lay.addWidget(self.face_info)
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
        combo.currentIndexChanged.connect(lambda _: setattr(tool, "classname", combo.currentData()))
        form.addRow(self.tr("Entity"), combo)
        lay.addLayout(form)
        lay.addWidget(_hint(self.tr(
            "Klick in die 3D-Ansicht setzt die Entity auf die angeklickte Fläche, Klick in eine 2D-Ansicht "
            "an die Mausposition. Alle Entities aus den FGD-Dateien folgen in Etappe 5, "
            "die Licht-Vorschau in Etappe 6."
        )))
        lay.addStretch(1)
        return w

