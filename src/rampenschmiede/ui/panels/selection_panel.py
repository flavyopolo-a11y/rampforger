"""Auswahl-Panel: Position und Größe der Auswahl mit exakter Zahleneingabe,
bei einer einzelnen Entity zusätzlich ihre Keyvalues."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.commands import ReplaceObjects
from ...core.model import Entity
from ..editor import EditorContext

LIMIT = 32768


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

        self.kv_box = QGroupBox(self.tr("Eigenschaften (Keyvalues)"))
        kv_lay = QVBoxLayout(self.kv_box)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels([self.tr("Schlüssel"), self.tr("Wert")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.itemChanged.connect(self._kv_changed)
        kv_lay.addWidget(self.table)
        btns = QHBoxLayout()
        add = QPushButton(self.tr("Hinzufügen"))
        add.clicked.connect(self._kv_add)
        rem = QPushButton(self.tr("Entfernen"))
        rem.clicked.connect(self._kv_remove)
        btns.addWidget(add)
        btns.addWidget(rem)
        kv_lay.addLayout(btns)
        lay.addWidget(self.kv_box)
        lay.addStretch(1)

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
                if isinstance(o, Entity):
                    self.summary.setText(self.tr("Entity: {0}").format(o.classname))
                else:
                    self.summary.setText(self.tr("Brush mit {0} Seiten").format(len(o.faces)))
            else:
                self.summary.setText(self.tr("{0} Objekte ausgewählt").format(len(objs)))
            self.geom_box.setEnabled(bb is not None)
            if bb is not None:
                for i in range(3):
                    self.pos[i].setValue(round(bb.mins[i]))
                    self.size[i].setValue(max(1, round(bb.size[i])))
            ent = objs[0] if len(objs) == 1 and isinstance(objs[0], Entity) else None
            self.kv_box.setVisible(ent is not None)
            self.table.setRowCount(0)
            if ent is not None:
                for k, v in ent.keyvalues:
                    r = self.table.rowCount()
                    self.table.insertRow(r)
                    ki = QTableWidgetItem(k)
                    if k in ("origin",):
                        ki.setFlags(ki.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(r, 0, ki)
                    self.table.setItem(r, 1, QTableWidgetItem(v))
        finally:
            self._updating = False

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

    def _entity(self) -> Entity | None:
        objs = self.editor.selected_objects()
        return objs[0] if len(objs) == 1 and isinstance(objs[0], Entity) else None

    def _kv_changed(self, _item: QTableWidgetItem) -> None:
        if self._updating:
            return
        ent = self._entity()
        if ent is None:
            return
        kvs = []
        for r in range(self.table.rowCount()):
            k = self.table.item(r, 0)
            v = self.table.item(r, 1)
            if k is not None and k.text().strip():
                kvs.append((k.text().strip(), v.text() if v is not None else ""))
        if tuple(kvs) != ent.keyvalues:
            self.editor.run(ReplaceObjects([ent.replace(keyvalues=tuple(kvs))], self.tr("Eigenschaft ändern")))

    def _kv_add(self) -> None:
        ent = self._entity()
        if ent is None:
            return
        n = 1
        while ent.get(f"neu{n}"):
            n += 1
        self.editor.run(ReplaceObjects([ent.with_keyvalue(f"neu{n}", "")], self.tr("Eigenschaft hinzufügen")))

    def _kv_remove(self) -> None:
        ent = self._entity()
        row = self.table.currentRow()
        if ent is None or row < 0:
            return
        key = self.table.item(row, 0).text()
        if key == "origin":
            return
        kvs = tuple(kv for kv in ent.keyvalues if kv[0] != key)
        self.editor.run(ReplaceObjects([ent.replace(keyvalues=kvs)], self.tr("Eigenschaft entfernen")))
