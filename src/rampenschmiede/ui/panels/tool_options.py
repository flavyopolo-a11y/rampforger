"""Werkzeug-Optionen: zeigt passende Einstellungen für das aktive Werkzeug."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..editor import EditorContext
from ..tools.entity_tool import POINT_ENTITIES, EntityTool
from ..tools.shape_tool import SHAPES, ShapeTool


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

    # ---- Formen -------------------------------------------------------------------------
    def _shape_page(self) -> QWidget:
        tool: ShapeTool = self.editor.tools["shape"]  # type: ignore[assignment]
        opts = tool.options
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        shape = QComboBox()
        for key, label in SHAPES.items():
            shape.addItem(self.tr(label), key)
        form.addRow(self.tr("Form"), shape)
        material = QLineEdit(opts.material)
        material.setToolTip(self.tr("Material für alle Seiten. Der Material-Browser folgt in Etappe 4."))
        material.editingFinished.connect(lambda: setattr(opts, "material", material.text().strip().upper() or opts.material))
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

        def on_shape(_: int) -> None:
            key = shape.currentData()
            opts.shape = key
            for name, (_, widget) in rows.items():
                form.setRowVisible(widget, name in visible[key])

        shape.currentIndexChanged.connect(on_shape)
        on_shape(0)
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

