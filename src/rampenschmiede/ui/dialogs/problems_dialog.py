"""Probleme suchen (Alt+P): Liste mit Hinspringen und Reparieren, bleibt beim Arbeiten offen."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ...core.validation.problems import ERROR, INFO, WARNING, Problem, fix_all

if TYPE_CHECKING:
    from ..main_window import MainWindow

LEVEL_COLORS = {ERROR: QColor(235, 80, 70), WARNING: QColor(230, 180, 40), INFO: QColor(140, 150, 165)}


class ProblemsDialog(QDialog):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window_ = window
        self.problems: list[Problem] = []
        self.setWindowTitle(self.tr("Probleme suchen"))
        self.setModal(False)
        self.resize(760, 420)
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        lay.addWidget(self.summary)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([self.tr("Art"), self.tr("Thema"), self.tr("Problem")])
        self.tree.setRootIsDecorated(False)
        self.tree.setWordWrap(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setStretchLastSection(True)
        self.tree.currentItemChanged.connect(lambda *_: self._on_current())
        self.tree.itemDoubleClicked.connect(lambda *_: self.jump())
        lay.addWidget(self.tree, 1)
        lay.addWidget(QLabel(self.tr("Klick auf eine Zeile wählt die Objekte aus und zeigt sie. "
                                     "„Reparieren“ ist ein normaler Undo-Schritt.")))
        row = QHBoxLayout()
        self.btn_fix = QPushButton(self.tr("Reparieren"))
        self.btn_fix.clicked.connect(self.fix_current)
        self.btn_fix_all = QPushButton(self.tr("Alle reparieren"))
        self.btn_fix_all.clicked.connect(self.fix_everything)
        again = QPushButton(self.tr("Neu prüfen"))
        again.clicked.connect(self.refresh)
        close = QPushButton(self.tr("Schließen"))
        close.clicked.connect(self.close)
        for b in (self.btn_fix, self.btn_fix_all, again):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)

    # ---- Inhalt -----------------------------------------------------------------------------
    def refresh(self) -> None:
        self.problems = self.window_.find_problems()
        self.tree.clear()
        for i, p in enumerate(self.problems):
            item = QTreeWidgetItem([self.tr(p.level), p.area, p.text])
            item.setForeground(0, LEVEL_COLORS[p.level])
            item.setData(0, Qt.UserRole, i)
            tip = p.text + (self.tr("\nReparieren: {0}").format(p.fix_label) if p.fix is not None else "")
            item.setToolTip(2, tip)
            self.tree.addTopLevelItem(item)
        errors = sum(p.level == ERROR for p in self.problems)
        warnings = sum(p.level == WARNING for p in self.problems)
        hints = len(self.problems) - errors - warnings
        if not self.problems:
            self.summary.setText(self.tr("Keine Probleme gefunden."))
        else:
            self.summary.setText(self.tr("{0} Fehler, {1} Warnungen, {2} Hinweise").format(errors, warnings, hints))
        self.btn_fix_all.setEnabled(any(p.fix is not None for p in self.problems))
        self._on_current()

    def current(self) -> Problem | None:
        item = self.tree.currentItem()
        return self.problems[item.data(0, Qt.UserRole)] if item is not None else None

    def _on_current(self) -> None:
        p = self.current()
        self.btn_fix.setEnabled(p is not None and p.fix is not None)
        self.btn_fix.setText(p.fix_label if p is not None and p.fix is not None else self.tr("Reparieren"))
        if p is not None:
            self.jump()

    # ---- Aktionen ---------------------------------------------------------------------------
    def jump(self) -> None:
        p = self.current()
        if p is None:
            return
        ed = self.window_.editor
        if "leak" in p.extra:
            ed.set_leak_path(p.extra["leak"])
        ids = [i for i in p.ids if i in ed.doc]
        if ids:
            ed.set_selection(ids)
            self.window_.center_on_selection()
        elif p.position is not None:
            for vp in self.window_.grid_view.viewports():
                vp.center_on(p.position, 512)

    def fix_current(self) -> bool:
        p = self.current()
        if p is None or p.fix is None:
            return False
        cmd = p.fix(self.window_.editor.doc)
        ok = cmd is not None and self.window_.editor.run(cmd)
        self.refresh()
        return ok

    def fix_everything(self) -> bool:
        cmd = fix_all(self.window_.editor.doc, self.problems)
        ok = cmd is not None and self.window_.editor.run(cmd)
        self.refresh()
        return ok
