"""Entity-Eigenschaften wie im Hammer-Objekteditor, aber aus den FGD-Daten mit passenden
Eingabefeldern: Auswahllisten, Häkchen für Flags, Farbwähler für Lichter, Namenslisten für
Ziele. Dazu die Ausgänge (I/O) zum Bearbeiten und die Eingänge, die andere Entities hierher
schicken."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.commands import ReplaceObjects
from ...core.entities.fgd import EntityCatalog, EntityClass, KeyDef, builtin_catalog, flag_bits
from ...core.entities.io import entities_named, incoming, target_names
from ...core.lights import LIGHT_CLASSES
from ...core.model import Entity, Output
from ...core.models.props import (
    PROP_CLASSES,
    PROP_HELP,
    PROP_LABELS,
    change_class,
    class_problem,
    is_model_entity,
)
from ..editor import EditorContext
from ..icons import ACTIVE

#: Breite der Beschriftungen; längere brechen um
LABEL_WIDTH = 120
#: Keys, die das Auswahl-Panel über Position und Größe schon abdeckt
GEOMETRY_KEYS = {"origin"}
PROP_STYLE = (f"QPushButton {{ padding: 3px 8px; }} QPushButton:checked {{ background: {ACTIVE}; color: #111; "
              "font-weight: bold; border: 1px solid #ffb070; }")
#: Lichter mit Richtung (bekommen den Knopf „In Blickrichtung ausrichten“)
AIMED_LIGHTS = {"light_spot", "light_environment"}


class ColorField(QWidget):
    """Farbe (R G B) mit optionaler Helligkeit als vierte Zahl, wie bei Lichtern."""

    changed = Signal(str)

    def __init__(self, value: str, parent=None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton()
        self.button.setMinimumWidth(40)
        self.button.clicked.connect(self._pick)
        lay.addWidget(self.button)
        self.brightness = QSpinBox()
        self.brightness.setRange(-1, 100000)
        self.brightness.setToolTip(self.tr("Helligkeit"))
        self.brightness.setKeyboardTracking(False)
        self.brightness.valueChanged.connect(lambda _: self.changed.emit(self.value()))
        lay.addWidget(self.brightness, 1)
        self.set_value(value)

    def set_value(self, value: str) -> None:
        parts = (value or "255 255 255").split()
        try:
            nums = [int(float(p)) for p in parts]
        except ValueError:
            nums = [255, 255, 255]
        self._rgb = [max(0, min(255, c)) for c in (nums + [255, 255, 255])[:3]]
        self._has_brightness = len(nums) >= 4
        self.brightness.blockSignals(True)
        self.brightness.setVisible(self._has_brightness)
        if self._has_brightness:
            self.brightness.setValue(nums[3])
        self.brightness.blockSignals(False)
        r, g, b = self._rgb
        self.button.setStyleSheet(f"background: rgb({r},{g},{b}); border: 1px solid #777;")
        self.button.setToolTip(f"{r} {g} {b}")

    def value(self) -> str:
        rgb = " ".join(str(c) for c in self._rgb)
        return f"{rgb} {self.brightness.value()}" if self._has_brightness else rgb

    def _pick(self) -> None:
        c = QColorDialog.getColor(QColor(*self._rgb), self, self.tr("Farbe wählen"))
        if c.isValid():
            self._rgb = [c.red(), c.green(), c.blue()]
            self.set_value(self.value())
            self.changed.emit(self.value())


class EntityPanel(QWidget):
    def __init__(self, editor: EditorContext, catalog: Callable[[], EntityCatalog] = builtin_catalog,
                 parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        self._catalog_fn = catalog
        self._ent_id: int | None = None
        self._updating = False
        self._editors: dict[str, Callable[[str], None]] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        top = QFormLayout()
        self.classname = QComboBox()
        self.classname.setEditable(True)
        self.classname.setInsertPolicy(QComboBox.NoInsert)
        self.classname.completer().setFilterMode(Qt.MatchContains)
        self.classname.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.classname.lineEdit().editingFinished.connect(self._class_edited)
        self.classname.activated.connect(lambda _: self._class_edited())
        top.addRow(self.tr("Klasse"), self.classname)
        lay.addLayout(top)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet("color: #9aa0a6;")
        lay.addWidget(self.desc)

        self.tabs = QTabWidget()
        lay.addWidget(self.tabs, 1)
        # Eigenschaften
        self.props_area = QScrollArea()
        self.props_area.setWidgetResizable(True)
        # Das Panel ist schmal: lieber Zeilen umbrechen als seitlich scrollen
        self.props_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tabs.addTab(self.props_area, self.tr("Eigenschaften"))
        # Ausgänge
        out_w = QWidget()
        out_l = QVBoxLayout(out_w)
        out_l.setContentsMargins(4, 4, 4, 4)
        self.outputs = QTableWidget(0, 6)
        self.outputs.setHorizontalHeaderLabels([self.tr("Ausgang"), self.tr("Ziel"), self.tr("Eingang"),
                                                self.tr("Parameter"), self.tr("Verz."), self.tr("Mal")])
        self.outputs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.outputs.horizontalHeader().setStretchLastSection(True)
        self.outputs.verticalHeader().hide()
        self.outputs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.outputs.setSelectionMode(QAbstractItemView.SingleSelection)
        self.outputs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.outputs.itemSelectionChanged.connect(self._load_output_row)
        out_l.addWidget(self.outputs, 1)
        form = QFormLayout()
        self.out_name = QComboBox()
        self.out_name.setEditable(True)
        self.out_target = QComboBox()
        self.out_target.setEditable(True)
        self.out_input = QComboBox()
        self.out_input.setEditable(True)
        self.out_param = QLineEdit()
        self.out_delay = QDoubleSpinBox()
        self.out_delay.setRange(0, 3600)
        self.out_delay.setDecimals(2)
        self.out_delay.setSuffix(" s")
        self.out_once = QCheckBox(self.tr("Nur einmal auslösen"))
        form.addRow(self.tr("Ausgang"), self.out_name)
        form.addRow(self.tr("Ziel"), self.out_target)
        form.addRow(self.tr("Eingang"), self.out_input)
        form.addRow(self.tr("Parameter"), self.out_param)
        form.addRow(self.tr("Verzögerung"), self.out_delay)
        form.addRow("", self.out_once)
        out_l.addLayout(form)
        for w in (self.out_name, self.out_target, self.out_input):
            w.lineEdit().editingFinished.connect(self._save_output_row)
            w.activated.connect(lambda _: self._save_output_row())
        self.out_target.lineEdit().editingFinished.connect(self._fill_inputs)
        self.out_target.activated.connect(lambda _: self._fill_inputs())
        self.out_param.editingFinished.connect(self._save_output_row)
        self.out_delay.editingFinished.connect(self._save_output_row)
        self.out_once.toggled.connect(lambda _: self._save_output_row())
        btns = QHBoxLayout()
        self.out_add = QPushButton(self.tr("Neu"))
        self.out_add.clicked.connect(self.add_output)
        self.out_copy = QPushButton(self.tr("Kopieren"))
        self.out_copy.clicked.connect(self.copy_output)
        self.out_del = QPushButton(self.tr("Löschen"))
        self.out_del.clicked.connect(self.delete_output)
        for b in (self.out_add, self.out_copy, self.out_del):
            btns.addWidget(b)
        out_l.addLayout(btns)
        self.tabs.addTab(out_w, self.tr("Ausgänge"))
        # Eingänge
        self.inputs = QTableWidget(0, 4)
        self.inputs.setHorizontalHeaderLabels([self.tr("Von"), self.tr("Ausgang"), self.tr("Eingang"),
                                               self.tr("Parameter")])
        self.inputs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.inputs.horizontalHeader().setStretchLastSection(True)
        self.inputs.verticalHeader().hide()
        self.inputs.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.inputs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.inputs.cellDoubleClicked.connect(self._jump_to_source)
        self.tabs.addTab(self.inputs, self.tr("Eingänge"))
        self._sources: list[int] = []

    # ---- Daten ------------------------------------------------------------------
    @property
    def catalog(self) -> EntityCatalog:
        return self._catalog_fn()

    def entity(self) -> Entity | None:
        obj = self.editor.doc.get(self._ent_id) if self._ent_id is not None else None
        return obj if isinstance(obj, Entity) else None

    def entity_class(self) -> EntityClass | None:
        ent = self.entity()
        return self.catalog.get(ent.classname) if ent is not None else None

    def _run(self, new: Entity, text: str) -> None:
        self.editor.run(ReplaceObjects([new], text))

    def set_value(self, key: str, value: str) -> None:
        ent = self.entity()
        if ent is None or self._updating:
            return
        existing = _existing_key(ent, key)
        if existing is not None and ent.get(existing) == value:
            return
        self._run(ent.with_keyvalue(existing or key, value), self.tr("Eigenschaft ändern"))

    # ---- Anzeige ------------------------------------------------------------------
    def show_entity(self, ent: Entity | None) -> None:
        changed = ent is None or ent.id != self._ent_id
        self._ent_id = ent.id if ent is not None else None
        if ent is None:
            return
        self._updating = True
        try:
            solid = bool(self.editor.doc.children(ent.id))
            names = self.catalog.classnames("solid" if solid else "point")
            if changed or self.classname.count() != len(names):
                self.classname.blockSignals(True)
                self.classname.clear()
                self.classname.addItems(names)
                self.classname.blockSignals(False)
            self.classname.setEditText(ent.classname)
            cls = self.catalog.get(ent.classname)
            self.desc.setText(cls.desc if cls and cls.desc else (
                "" if cls else self.tr("Unbekannte Klasse: Die Keyvalues stehen unten als Text.")))
            self.desc.setVisible(bool(self.desc.text()))
            self._build_props(ent, cls)
            self._fill_outputs(ent, cls)
            self._fill_incoming(ent)
        finally:
            self._updating = False

    def _build_props(self, ent: Entity, cls: EntityClass | None) -> None:
        w = QWidget()
        form = QFormLayout(w)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self._editors = {}
        known: set[str] = set()
        names = target_names(self.editor.doc)
        if ent.classname.lower() in LIGHT_CLASSES:
            hint = QLabel(self.tr("Vorschau: 3D-Ansicht oben links auf „Licht-Vorschau“ stellen."))
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #9aa0a6;")
            form.addRow(hint)
        if is_model_entity(ent) or ent.classname.lower() in PROP_CLASSES:
            form.addRow(self._prop_box(ent))
        if ent.classname.lower() in AIMED_LIGHTS:
            aim = QPushButton(self.tr("In Blickrichtung der 3D-Kamera ausrichten"))
            aim.setToolTip(self.tr("Schau in der 3D-Ansicht dorthin, wohin das Licht scheinen soll, und klick hier."))
            aim.clicked.connect(self.aim_at_camera)
            form.addRow(aim)
        keys = list(cls.keys) if cls else []
        if is_model_entity(ent) or ent.classname.lower() in PROP_CLASSES:
            keys = _prop_keys(keys)
        for k in keys:
            if k.name.lower() in GEOMETRY_KEYS:
                continue
            known.add(k.name.lower())
            existing = _existing_key(ent, k.name)
            value = ent.get(existing) if existing is not None else k.default
            if k.kind == "flags":
                form.addRow(self._flags_box(k, value))
                continue
            field_w = self._field(k, value, names)
            label = QLabel(k.label)
            label.setWordWrap(True)
            label.setMaximumWidth(LABEL_WIDTH)
            label.setToolTip(f"{k.name}: {k.desc}" if k.desc else k.name)
            field_w.setToolTip(label.toolTip())
            form.addRow(label, field_w)
        extras = [(key, v) for key, v in ent.keyvalues if key.lower() not in known and key.lower() not in GEOMETRY_KEYS]
        if extras:
            sep = QLabel(self.tr("Weitere Keyvalues") if cls else self.tr("Keyvalues"))
            sep.setStyleSheet("color: #9aa0a6; margin-top: 6px;")
            form.addRow(sep)
            for key, v in extras:
                edit = QLineEdit(v)
                edit.editingFinished.connect(lambda key=key, edit=edit: self.set_value(key, edit.text()))
                label = QLabel(key)
                label.setWordWrap(True)
                label.setMaximumWidth(LABEL_WIDTH)
                form.addRow(label, edit)
        add_row = QHBoxLayout()
        self.new_key = QLineEdit()
        self.new_key.setPlaceholderText(self.tr("neuer Key"))
        self.new_val = QLineEdit()
        self.new_val.setPlaceholderText(self.tr("Wert"))
        add = QPushButton(self.tr("Hinzufügen"))
        add.clicked.connect(self._add_key)
        add_row.addWidget(self.new_key)
        add_row.addWidget(self.new_val)
        add_row.addWidget(add)
        form.addRow(add_row)
        self.props_area.setWidget(w)

    # ---- Props ------------------------------------------------------------------------
    def _loaded_model(self, ent: Entity):
        lib = getattr(self.editor, "models", None)
        name = ent.get("model", "")
        return lib.load(name) if lib is not None and name else None

    def _prop_box(self, ent: Entity) -> QWidget:
        """Prop-Art als drei Knöpfe und, wenn das Modell nicht zur Art passt, warum."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 4)
        row = QHBoxLayout()
        row.setSpacing(0)
        model = self._loaded_model(ent)
        self.prop_buttons: dict[str, QPushButton] = {}
        for cls in PROP_CLASSES:
            b = QPushButton(self.tr(PROP_LABELS[cls]))
            b.setCheckable(True)
            b.setChecked(ent.classname.lower() == cls)
            b.setStyleSheet(PROP_STYLE)
            problem = class_problem(cls, model)
            b.setToolTip(f"{cls}: {self.tr(PROP_HELP[cls])}" + (f"\n\n{self.tr(problem)}" if problem else ""))
            if problem:
                b.setText(b.text() + " ⚠")
            b.clicked.connect(lambda _=False, c=cls: self.set_prop_class(c))
            self.prop_buttons[cls] = b
            row.addWidget(b)
        lay.addLayout(row)
        problem = class_problem(ent.classname, model)
        self.prop_warning = QLabel(self.tr(problem))
        self.prop_warning.setWordWrap(True)
        self.prop_warning.setStyleSheet("color: #e5a050;")
        self.prop_warning.setVisible(bool(problem))
        lay.addWidget(self.prop_warning)
        if ent.get("model") and model is None and getattr(self.editor, "models", None) is not None:
            missing = QLabel(self.tr("Modell nicht gefunden: Im Spiel fehlt es, oder der Pfad ist falsch."))
            missing.setWordWrap(True)
            missing.setStyleSheet("color: #e57373;")
            lay.addWidget(missing)
        return box

    def set_prop_class(self, classname: str) -> None:
        ent = self.entity()
        if ent is None or ent.classname == classname:
            if ent is not None:
                self.show_entity(ent)
            return
        cls = self.catalog.get(classname)
        new = change_class(ent, classname)
        if cls is not None:
            have = {k.lower() for k, _ in new.keyvalues}
            new = new.replace(keyvalues=new.keyvalues + tuple((k, v) for k, v in cls.defaults() if k.lower() not in have))
        self._run(new, self.tr("Prop-Art ändern"))

    def choose_model(self) -> bool:
        from ..dialogs.model_dialog import ModelDialog

        ent = self.entity()
        if ent is None:
            return False
        dlg = ModelDialog(getattr(self.editor, "models", None), ent.get("model", ""), self)
        if dlg.exec() != ModelDialog.Accepted or not dlg.chosen():
            return False
        self.set_value("model", dlg.chosen())
        return True

    def aim_at_camera(self) -> bool:
        """Spot oder Sonne in die Richtung drehen, in die die 3D-Kamera schaut."""
        ent = self.entity()
        cam = getattr(self.editor, "camera3d", None)
        if ent is None or cam is None:
            return False
        pitch, yaw = round(cam.pitch), round(cam.yaw) % 360
        new = ent
        for key, value in (("pitch", str(pitch)), ("angles", f"{pitch} {yaw} 0")):
            new = new.with_keyvalue(_existing_key(new, key) or key, value)
        if new != ent:
            self._run(new, self.tr("Licht ausrichten"))
        return True

    def _field(self, k: KeyDef, value: str, names: list[str]) -> QWidget:
        if k.kind == "model":
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            edit = QLineEdit(value)
            edit.editingFinished.connect(lambda key=k.name, e=edit: self.set_value(key, e.text().strip()))
            pick = QPushButton(self.tr("Wählen …"))
            pick.setToolTip(self.tr("Modell aus dem Spiel mit Vorschau wählen"))
            pick.clicked.connect(self.choose_model)
            row.addWidget(edit, 1)
            row.addWidget(pick)
            self.model_edit = edit
            return w
        if k.name.lower() == "skin":
            ent = self.entity()
            model = self._loaded_model(ent) if ent is not None else None
            if model is not None:
                spin = QSpinBox()
                spin.setRange(0, model.skin_count - 1)
                try:
                    spin.setValue(int(float(value or 0)))
                except ValueError:
                    spin.setValue(0)
                spin.setEnabled(model.skin_count > 1)
                spin.setSuffix(self.tr(" von {0}").format(model.skin_count))
                spin.valueChanged.connect(lambda v, key=k.name: self.set_value(key, str(v)))
                return spin
        if k.kind == "boolean":
            box = QCheckBox()
            box.setChecked(value not in ("", "0"))
            box.toggled.connect(lambda on, key=k.name: self.set_value(key, "1" if on else "0"))
            return box
        if k.kind == "choices" and k.choices:
            combo = QComboBox()
            for val, text in k.choices:
                combo.addItem(f"{text}", val)
            idx = combo.findData(value)
            if idx < 0:
                combo.addItem(value, value)
                idx = combo.count() - 1
            combo.setCurrentIndex(idx)
            combo.activated.connect(lambda _, key=k.name, c=combo: self.set_value(key, str(c.currentData())))
            return combo
        if k.kind == "color":
            color = ColorField(value or k.default)
            color.changed.connect(lambda v, key=k.name: self.set_value(key, v))
            return color
        if k.kind == "target":
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItems(names)
            combo.setEditText(value)
            combo.lineEdit().editingFinished.connect(
                lambda key=k.name, c=combo: self.set_value(key, c.currentText().strip()))
            combo.activated.connect(lambda _, key=k.name, c=combo: self.set_value(key, c.currentText().strip()))
            return combo
        edit = QLineEdit(value)
        if k.kind == "integer":
            edit.setValidator(QIntValidator())
        elif k.kind == "float":
            edit.setValidator(QDoubleValidator())
        edit.editingFinished.connect(lambda key=k.name, e=edit: self.set_value(key, e.text()))
        return edit

    def _flags_box(self, k: KeyDef, value: str) -> QGroupBox:
        box = QGroupBox(self.tr("Flags"))
        lay = QVBoxLayout(box)
        lay.setContentsMargins(4, 4, 4, 4)
        bits = flag_bits(value) if value else sum(b for b, _, on in k.flags if on)
        # Liste statt Häkchen-Widgets: lange Flag-Namen werden gekürzt statt das Panel zu sprengen
        flags = QListWidget()
        flags.setTextElideMode(Qt.ElideRight)
        flags.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for bit, text, _ in k.flags:
            item = QListWidgetItem(text)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if bits & bit else Qt.Unchecked)
            item.setData(Qt.UserRole, bit)
            item.setToolTip(f"{text} ({k.name} {bit})")
            flags.addItem(item)
        rows = min(len(k.flags), 8)
        flags.setFixedHeight(rows * flags.sizeHintForRow(0) + 6 if rows else 0)
        flags.itemChanged.connect(
            lambda item, key=k.name: self._toggle_flag(key, item.data(Qt.UserRole), item.checkState() == Qt.Checked))
        lay.addWidget(flags)
        self.flag_list = flags
        return box

    def _toggle_flag(self, key: str, bit: int, on: bool) -> None:
        ent = self.entity()
        if ent is None or self._updating:
            return
        cls = self.entity_class()
        k = cls.key(key) if cls else None
        existing = _existing_key(ent, key)
        bits = flag_bits(ent.get(existing)) if existing else (sum(b for b, _, d in k.flags if d) if k else 0)
        bits = bits | bit if on else bits & ~bit
        self.set_value(key, str(bits))

    def _add_key(self) -> None:
        key = self.new_key.text().strip()
        if key:
            self.set_value(key, self.new_val.text())

    def _class_edited(self) -> None:
        ent = self.entity()
        name = self.classname.currentText().strip()
        if ent is None or self._updating or not name or name == ent.classname:
            return
        cls = self.catalog.get(name)
        kvs = list(ent.keyvalues)
        if cls is not None:
            have = {k.lower() for k, _ in kvs}
            kvs += [(k, v) for k, v in cls.defaults() if k.lower() not in have]
        self._run(ent.replace(classname=name, keyvalues=tuple(kvs)), self.tr("Klasse ändern"))

    # ---- Ausgänge -------------------------------------------------------------------
    def _fill_outputs(self, ent: Entity, cls: EntityClass | None) -> None:
        row = self.outputs.currentRow()
        self.outputs.setRowCount(0)
        for o in ent.outputs:
            r = self.outputs.rowCount()
            self.outputs.insertRow(r)
            times = self.tr("1×") if o.times == 1 else ("∞" if o.times < 0 else f"{o.times}×")
            for c, text in enumerate((o.output, o.target, o.input, o.parameter, f"{o.delay:g}", times)):
                self.outputs.setItem(r, c, QTableWidgetItem(text))
            if not any(e for e in entities_named(self.editor.doc, o.target)) and not o.target.startswith("!"):
                for c in (1,):
                    self.outputs.item(r, c).setForeground(QColor("#e06c60"))
                    self.outputs.item(r, c).setToolTip(self.tr("Kein Objekt mit diesem Namen in der Map"))
        self.out_name.clear()
        self.out_name.addItems([d.name for d in (cls.outputs if cls else [])])
        self.out_target.clear()
        self.out_target.addItems(["!activator", "!self", "!player", *target_names(self.editor.doc)])
        if ent.outputs:
            self.outputs.selectRow(min(max(row, 0), len(ent.outputs) - 1))
        self._load_output_row()

    def _current_output(self) -> int:
        rows = self.outputs.selectionModel().selectedRows() if self.outputs.selectionModel() else []
        return rows[0].row() if rows else -1

    def _load_output_row(self) -> None:
        ent = self.entity()
        i = self._current_output()
        has = ent is not None and 0 <= i < len(ent.outputs)
        for w in (self.out_name, self.out_target, self.out_input, self.out_param, self.out_delay, self.out_once,
                  self.out_copy, self.out_del):
            w.setEnabled(has)
        if not has:
            return
        o = ent.outputs[i]
        was = self._updating
        self._updating = True
        try:
            self.out_name.setEditText(o.output)
            self.out_target.setEditText(o.target)
            self._fill_inputs()
            self.out_input.setEditText(o.input)
            self.out_param.setText(o.parameter)
            self.out_delay.setValue(o.delay)
            self.out_once.setChecked(o.times == 1)
        finally:
            self._updating = was

    def _fill_inputs(self) -> None:
        current = self.out_input.currentText()
        names: set[str] = set()
        for t in entities_named(self.editor.doc, self.out_target.currentText().strip()):
            cls = self.catalog.get(t.classname)
            if cls:
                names |= {d.name for d in cls.inputs}
        self.out_input.blockSignals(True)
        self.out_input.clear()
        self.out_input.addItems(sorted(names, key=str.lower))
        self.out_input.setEditText(current)
        self.out_input.blockSignals(False)
        if not self._updating:
            self._save_output_row()

    def _save_output_row(self) -> None:
        ent = self.entity()
        i = self._current_output()
        if ent is None or self._updating or not 0 <= i < len(ent.outputs):
            return
        old = ent.outputs[i]
        times = 1 if self.out_once.isChecked() else (-1 if old.times == 1 else old.times)
        new = Output(self.out_name.currentText().strip(), self.out_target.currentText().strip(),
                     self.out_input.currentText().strip(), self.out_param.text(), round(self.out_delay.value(), 3),
                     times)
        if new != old:
            outs = list(ent.outputs)
            outs[i] = new
            self._run(ent.replace(outputs=tuple(outs)), self.tr("Ausgang ändern"))

    def add_output(self) -> None:
        ent = self.entity()
        if ent is None:
            return
        cls = self.entity_class()
        first = cls.outputs[0].name if cls and cls.outputs else "OnUser1"
        self._run(ent.replace(outputs=(*ent.outputs, Output(first, "", ""))), self.tr("Ausgang hinzufügen"))
        self.outputs.selectRow(len(ent.outputs))

    def copy_output(self) -> None:
        ent = self.entity()
        i = self._current_output()
        if ent is None or not 0 <= i < len(ent.outputs):
            return
        self._run(ent.replace(outputs=(*ent.outputs, ent.outputs[i])), self.tr("Ausgang kopieren"))
        self.outputs.selectRow(len(ent.outputs))

    def delete_output(self) -> None:
        ent = self.entity()
        i = self._current_output()
        if ent is None or not 0 <= i < len(ent.outputs):
            return
        outs = ent.outputs[:i] + ent.outputs[i + 1:]
        self._run(ent.replace(outputs=outs), self.tr("Ausgang löschen"))

    # ---- Eingänge -------------------------------------------------------------------
    def _fill_incoming(self, ent: Entity) -> None:
        rows = incoming(self.editor.doc, ent)
        self._sources = [src.id for src, _ in rows]
        self.inputs.setRowCount(0)
        for src, o in rows:
            r = self.inputs.rowCount()
            self.inputs.insertRow(r)
            who = src.get("targetname") or src.classname
            for c, text in enumerate((who, o.output, o.input, o.parameter)):
                self.inputs.setItem(r, c, QTableWidgetItem(text))
        self.tabs.setTabText(2, self.tr("Eingänge ({0})").format(len(rows)) if rows else self.tr("Eingänge"))

    def _jump_to_source(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._sources):
            self.editor.set_selection([self._sources[row]])


MODEL_KEY = KeyDef("model", "Modell", "model", desc="Pfad des Modells, z. B. models/props_c17/oildrum001.mdl")
SOLID_KEY = KeyDef("solid", "Kollision", "choices", "6", "Wie Spieler mit dem Prop zusammenstoßen",
                   (("0", "Keine (durchlässig)"), ("2", "Kasten (Bounding Box)"), ("6", "Modell (VPhysics)")))


def _prop_keys(keys: list[KeyDef]) -> list[KeyDef]:
    """Props zeigen immer zuerst das Modell; manche FGDs (engine_dbase bei prop_static)
    führen es nicht. Kollision als Auswahl statt als nackte Zahl."""
    out = [k for k in keys if k.name.lower() != "model"]
    out = [SOLID_KEY if k.name.lower() == "solid" and k.kind == "integer" else k for k in out]
    model = next((k for k in keys if k.name.lower() == "model"), MODEL_KEY)
    return [model, *out]


def _existing_key(ent: Entity, key: str) -> str | None:
    """Keys sind in Source unabhängig von Groß-/Kleinschreibung; die vorhandene Schreibweise gilt."""
    low = key.lower()
    return next((k for k, _ in ent.keyvalues if k.lower() == low), None)
