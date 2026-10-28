"""Entity-Bericht (wie „Entity Report“ in Hammer): alle Entities der Map als Tabelle mit
Filter nach Text, Klasse und Art. Doppelklick wählt aus und springt hin, „Auswählen“ nimmt
alle gefilterten, „Löschen“ entfernt sie (mit Strg+Z zurück)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...core.commands import RemoveObjects
from ...core.entities.io import entity_center
from ...core.model import Entity
from ...i18n import N_

if TYPE_CHECKING:
    from ..main_window import MainWindow

KINDS = (("alle", N_("Alle")), ("punkt", N_("Punkt-Entities")), ("brush", N_("Brush-Entities")))


def report_rows(doc, text: str = "", classname: str = "", kind: str = "alle") -> list[Entity]:
    """Entities, die zum Filter passen: Text in Klasse, Name oder irgendeinem Wert."""
    low = text.strip().lower()
    parents = {s.parent_id for s in doc.solids() if s.parent_id is not None}
    out = []
    for e in doc.entities():
        brush = e.id in parents
        if kind == "punkt" and brush or kind == "brush" and not brush:
            continue
        if classname and e.classname.lower() != classname.lower():
            continue
        if low and low not in e.classname.lower() and not any(low in v.lower() for _k, v in e.keyvalues):
            continue
        out.append(e)
    return sorted(out, key=lambda e: (e.classname.lower(), e.get("targetname").lower(), e.id))


class EntityReport(QDialog):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window_ = window
        self.editor = window.editor
        self.setWindowTitle(self.tr("Entity-Bericht"))
        self.resize(760, 520)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Filter: Klasse, Name oder Wert …"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self.refresh())
        row.addWidget(self.search, 1)
        self.classes = QComboBox()
        self.classes.currentIndexChanged.connect(lambda _i: self.refresh())
        row.addWidget(self.classes)
        self.kind = QComboBox()
        for key, label in KINDS:
            self.kind.addItem(self.tr(label), key)
        self.kind.currentIndexChanged.connect(lambda _i: self.refresh())
        row.addWidget(self.kind)
        lay.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([self.tr("Klasse"), self.tr("Name"), self.tr("Position"),
                                              self.tr("Ausgänge"), self.tr("ID")])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSortIndicator(0, Qt.AscendingOrder)
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(lambda r, _c: self.go_to_row(r))
        lay.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.count = QLabel()
        bottom.addWidget(self.count, 1)
        self.select_btn = QPushButton(self.tr("Alle gefilterten auswählen"))
        self.select_btn.clicked.connect(self.select_filtered)
        self.delete_btn = QPushButton(self.tr("Markierte löschen"))
        self.delete_btn.clicked.connect(self.delete_marked)
        close = QPushButton(self.tr("Schließen"))
        close.clicked.connect(self.accept)
        for b in (self.select_btn, self.delete_btn, close):
            bottom.addWidget(b)
        lay.addLayout(bottom)
        self._rows: list[Entity] = []
        self.editor.document_changed.connect(self._doc_changed)
        self.editor.document_replaced.connect(self._doc_changed)
        self._fill_classes()
        self.refresh()

    def _doc_changed(self) -> None:
        if self.isVisible():
            self._fill_classes()
            self.refresh()

    def _fill_classes(self) -> None:
        current = self.classes.currentData() or ""
        names = sorted({e.classname for e in self.editor.doc.entities()}, key=str.lower)
        self.classes.blockSignals(True)
        self.classes.clear()
        self.classes.addItem(self.tr("Alle Klassen"), "")
        for n in names:
            self.classes.addItem(n, n)
        idx = self.classes.findData(current)
        self.classes.setCurrentIndex(max(idx, 0))
        self.classes.blockSignals(False)

    def refresh(self) -> None:
        doc = self.editor.doc
        self._rows = report_rows(doc, self.search.text(), self.classes.currentData() or "",
                                 self.kind.currentData() or "alle")
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._rows))
        for r, e in enumerate(self._rows):
            c = entity_center(doc, e)
            pos = " ".join(f"{v:.0f}" for v in c) if c else ""
            values = (e.classname, e.get("targetname"), pos, str(len(e.outputs)) if e.outputs else "",
                      str(e.vmf_id or e.id))
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, e.id)
                self.table.setItem(r, col, item)
        self.table.setSortingEnabled(True)
        total = sum(1 for _ in doc.entities())
        self.count.setText(self.tr("{0} von {1} Entities").format(len(self._rows), total))

    def _id_at(self, row: int) -> int | None:
        item = self.table.item(row, 0)
        return item.data(Qt.UserRole) if item is not None else None

    def go_to_row(self, row: int) -> None:
        oid = self._id_at(row)
        if oid is not None:
            self.editor.set_selection([oid])
            self.window_.center_on_selection()

    def select_filtered(self) -> None:
        self.editor.set_selection([e.id for e in self._rows])
        self.window_.center_on_selection()

    def marked_ids(self) -> list[int]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [oid for r in rows if (oid := self._id_at(r)) is not None]

    def delete_marked(self) -> int:
        ids = self.marked_ids()
        if not ids:
            return 0
        self.editor.run(RemoveObjects(ids, self.tr("Entities löschen")))  # Brushes gehen mit
        return len(ids)


__all__ = ["EntityReport", "report_rows"]
