"""Auswahl-Panel: Position und Größe der Auswahl mit exakter Zahleneingabe,
bei einer einzelnen Entity zusätzlich ihre Keyvalues."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.commands import SetWorldKeyvalues
from ...core.model import Entity
from ...core.scene import kind_of
from ...core.scene import label as object_label
from ...i18n import N_
from ...render.sky import available_skies
from ..editor import EditorContext
from .entity_panel import EntityPanel

LIMIT = 32768
#: Map-Eigenschaften (worldspawn) wie in Hammer: (Schlüssel, Beschriftung, Art, Standard, Hinweis)
WORLD_FIELDS = (
    ("message", N_("Titel der Map"), "text", "", N_("Wird beim Laden der Map angezeigt")),
    ("skyname", N_("Himmel"), "sky", "sky_day01_01", N_("Name der 2D-Skybox (materials/skybox/<Name>rt …)")),
    ("detailmaterial", N_("Detail-Material"), "text", "detail/detailsprites", N_("Bild für Gras-Sprites auf Displacements")),
    ("detailvbsp", N_("Detail-Datei"), "text", "detail.vbsp", N_("Welche Detail-Sprites auf welchen Materialien wachsen")),
    ("maxpropscreenwidth", N_("Props ausblenden ab"), "int", "-1",
     N_("Props verschwinden, wenn sie schmaler als so viele Pixel sind (-1 = nie)")),
    ("coldworld", N_("Kalte Welt"), "bool", "0", N_("Atemwolken und kalter Hauch (nur manche Spiele)")),
)


def set_world_kv(kvs: tuple[tuple[str, str], ...], key: str, value: str) -> tuple[tuple[str, str], ...]:
    out = [(k, value) if k == key else (k, v) for k, v in kvs]
    if not any(k == key for k, _ in kvs):
        out.append((key, value))
    return tuple(out)


def _spin() -> QSpinBox:
    s = QSpinBox()
    s.setRange(-LIMIT, LIMIT)
    s.setKeyboardTracking(False)
    return s


class SelectionPanel(QWidget):
    def __init__(self, editor: EditorContext, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        self._updating = False
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-size: 11pt; padding: 2px 0 4px 0;")
        lay.addWidget(self.summary)

        box = QGroupBox(self.tr("Position und Größe"))
        form = QFormLayout(box)
        self.pos = [_spin() for _ in range(3)]
        self.size = [_spin() for _ in range(3)]
        for s in self.size:
            s.setRange(1, LIMIT * 2)
        for label, spins in ((self.tr("Position (min)"), self.pos), (self.tr("Größe"), self.size)):
            row = QHBoxLayout()
            for axis, s in zip("XYZ", spins):
                s.setPrefix(f"{axis} ")
                row.addWidget(s)
            form.addRow(label, row)
        for s in self.pos:
            s.valueChanged.connect(self._apply_position)
        for s in self.size:
            s.valueChanged.connect(self._apply_size)
        lay.addWidget(box)
        self.geom_box = box

        self.world_box = QGroupBox(self.tr("Map-Eigenschaften"))
        world_form = QFormLayout(self.world_box)
        self.world_fields: dict[str, QWidget] = {}
        for key, label, kind, default, hint in WORLD_FIELDS:
            if kind == "sky":
                w = QComboBox()
                w.setEditable(True)
                w.lineEdit().editingFinished.connect(lambda k=key: self._world_changed(k))
                w.activated.connect(lambda _i, k=key: self._world_changed(k))
            elif kind == "bool":
                w = QCheckBox()
                w.toggled.connect(lambda _on, k=key: self._world_changed(k))
            elif kind == "int":
                w = QSpinBox()
                w.setRange(-1, 4096)
                w.setKeyboardTracking(False)
                w.valueChanged.connect(lambda _v, k=key: self._world_changed(k))
            else:
                w = QLineEdit()
                w.setPlaceholderText(default)
                w.editingFinished.connect(lambda k=key: self._world_changed(k))
            w.setToolTip(self.tr(hint))
            self.world_fields[key] = w
            world_form.addRow(self.tr(label), w)
        lay.addWidget(self.world_box)

        self.kv_box = QGroupBox(self.tr("Entity"))
        kv_lay = QVBoxLayout(self.kv_box)
        kv_lay.setContentsMargins(4, 4, 4, 4)
        self.entity_panel = EntityPanel(editor, lambda: editor.entity_catalog)
        kv_lay.addWidget(self.entity_panel)
        lay.addWidget(self.kv_box, 1)
        self.stretch = QWidget()
        lay.addWidget(self.stretch, 1)

        editor.selection_changed.connect(self.refresh)
        editor.document_changed.connect(self.refresh)
        editor.document_replaced.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._updating = True
        try:
            objs = self.editor.selected_objects()
            bb = self.editor.selection_bbox()
            if not objs:
                self.summary.setText(self.tr("Nichts ausgewählt"))
            elif len(objs) == 1:
                o = objs[0]
                self.summary.setText(f"<b>{self.tr(kind_of(self.editor.doc, o))}</b> · {object_label(o)}")
            else:
                self.summary.setText(self.tr("{0} Objekte ausgewählt").format(len(objs)))
            self.geom_box.setEnabled(bb is not None)
            if bb is not None:
                for i in range(3):
                    self.pos[i].setValue(round(bb.mins[i]))
                    self.size[i].setValue(max(1, round(bb.size[i])))
            ent = objs[0] if len(objs) == 1 and isinstance(objs[0], Entity) else None
            self.kv_box.setVisible(ent is not None)
            self.stretch.setVisible(ent is None)
            self.entity_panel.show_entity(ent)
            self.world_box.setVisible(not objs)
            self.geom_box.setVisible(bool(objs))
            if not objs:
                self._show_world()
        finally:
            self._updating = False

    # ---- Map-Eigenschaften ------------------------------------------------------------
    def _show_world(self) -> None:
        kvs = dict(self.editor.doc.world_keyvalues)
        for key, _label, kind, default, _hint in WORLD_FIELDS:
            w = self.world_fields[key]
            value = kvs.get(key, "")
            w.blockSignals(True)
            if kind == "sky":
                skies = available_skies(self.editor.materials)
                if [w.itemText(i) for i in range(w.count())] != skies:
                    w.clear()
                    w.addItems(skies)
                w.setEditText(value or default)
            elif kind == "bool":
                w.setChecked(value == "1")
            elif kind == "int":
                try:
                    w.setValue(int(float(value or default)))
                except ValueError:
                    w.setValue(int(default))
            else:
                w.setText(value)
            w.blockSignals(False)

    def world_value(self, key: str) -> str:
        w = self.world_fields[key]
        if isinstance(w, QComboBox):
            return w.currentText().strip()
        if isinstance(w, QCheckBox):
            return "1" if w.isChecked() else "0"
        if isinstance(w, QSpinBox):
            return str(w.value())
        return w.text().strip()  # type: ignore[attr-defined]

    def _world_changed(self, key: str) -> None:
        if self._updating:
            return
        value = self.world_value(key)
        kvs = self.editor.doc.world_keyvalues
        if dict(kvs).get(key, "") == value:
            return
        self.editor.run(SetWorldKeyvalues(set_world_kv(kvs, key, value), self.tr("Map-Eigenschaften")))

    def _apply_position(self) -> None:
        if self._updating:
            return
        bb = self.editor.selection_bbox()
        if bb is None:
            return
        delta = tuple(self.pos[i].value() - bb.mins[i] for i in range(3))
        if any(delta):
            self.editor.move_selection(delta)  # type: ignore[arg-type]
            self.editor.stack.end_merge()

    def _apply_size(self) -> None:
        if self._updating:
            return
        bb = self.editor.selection_bbox()
        if bb is None:
            return
        factors = tuple(self.size[i].value() / bb.size[i] if bb.size[i] > 0 else 1.0 for i in range(3))
        if any(abs(f - 1.0) > 1e-9 for f in factors):
            self.editor.scale_selection(bb.mins, factors)  # type: ignore[arg-type]
            self.editor.stack.end_merge()
