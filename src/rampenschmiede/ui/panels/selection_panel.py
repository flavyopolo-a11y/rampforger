"""Auswahl-Panel: Position und Größe der Auswahl mit exakter Zahleneingabe,
bei einer einzelnen Entity zusätzlich ihre Keyvalues."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.model import Entity
from ...core.scene import kind_of
from ...core.scene import label as object_label
from ..editor import EditorContext
from .entity_panel import EntityPanel

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
