"""Kompilier-Log: Live-Ausgabe, farbige Fehler, Klick springt zum Objekt."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.compile import CompilePlan, CompileResult, Level, LogLine
from ..compile_controller import CompileController

COLORS = {
    Level.ERROR: QColor(255, 110, 100),
    Level.WARNING: QColor(240, 200, 90),
    Level.STEP: QColor(120, 180, 255),
    Level.INFO: QColor(200, 204, 210),
}
MAX_LINES = 20000


class CompileLogPanel(QWidget):
    def __init__(self, controller: CompileController, center_on, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._center_on = center_on  # Rückruf: Ansichten auf Punkt/Box zentrieren
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)

        head = QHBoxLayout()
        self.status = QLabel(self.tr("Noch nicht kompiliert. F9 startet."))
        head.addWidget(self.status, 1)
        self.only_problems = QCheckBox(self.tr("Nur Probleme"))
        self.only_problems.toggled.connect(self._apply_filter)
        head.addWidget(self.only_problems)
        self.btn_leak = QPushButton(self.tr("Zum Leck"))
        self.btn_leak.setToolTip(self.tr("Ansichten auf den Anfang der Leck-Spur zentrieren"))
        self.btn_leak.clicked.connect(self.go_to_leak)
        self.btn_leak.setEnabled(False)
        head.addWidget(self.btn_leak)
        self.btn_copy = QPushButton(self.tr("Kopieren"))
        self.btn_copy.clicked.connect(self.copy_log)
        head.addWidget(self.btn_copy)
        self.btn_cancel = QPushButton(self.tr("Abbrechen"))
        self.btn_cancel.clicked.connect(controller.cancel)
        self.btn_cancel.setEnabled(False)
        head.addWidget(self.btn_cancel)
        lay.addLayout(head)

        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        self.list.setFont(mono)
        self.list.itemActivated.connect(self._activate)
        self.list.itemClicked.connect(self._activate)
        lay.addWidget(self.list, 1)
        self.progress = QLabel()
        self.progress.setStyleSheet("color: #9aa4b2;")
        lay.addWidget(self.progress)

        controller.started.connect(self._on_started)
        controller.line.connect(self.add_line)
        controller.progress.connect(self.progress.setText)
        controller.step.connect(lambda s: self.status.setText(self.tr("Läuft: {0} …").format(s)))
        controller.finished.connect(self._on_finished)
        controller.editor.redraw_requested.connect(self._update_leak_button)

    # ---- Einträge ------------------------------------------------------------------------
    def add_line(self, line: LogLine) -> None:
        if self.list.count() >= MAX_LINES:
            self.list.takeItem(0)
        item = QListWidgetItem(line.text)
        item.setForeground(QBrush(COLORS[line.level]))
        item.setData(Qt.UserRole, line)
        if line.level is Level.STEP:
            f = item.font()
            f.setBold(True)
            item.setFont(f)
        if line.level in (Level.ERROR, Level.WARNING) and line.has_target:
            item.setToolTip(self.tr("Klicken springt zum betroffenen Objekt"))
        item.setHidden(self._filtered(line))
        self.list.addItem(item)
        if not item.isHidden():
            self.list.scrollToItem(item)

    def _filtered(self, line: LogLine) -> bool:
        return self.only_problems.isChecked() and line.level not in (Level.ERROR, Level.WARNING, Level.STEP)

    def _apply_filter(self) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(self._filtered(item.data(Qt.UserRole)))

    def lines(self) -> list[LogLine]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def copy_log(self) -> None:
        QGuiApplication.clipboard().setText("\n".join(line.text for line in self.lines()))

    # ---- Springen ----------------------------------------------------------------------------
    def _activate(self, item: QListWidgetItem) -> None:
        line: LogLine = item.data(Qt.UserRole)
        self.jump_to(line)

    def jump_to(self, line: LogLine) -> bool:
        target = self.controller.resolve(line)
        if target is None:
            return False
        editor = self.controller.editor
        if target.object_ids:
            editor.set_selection(target.object_ids)
            bb = editor.selection_bbox()
            if bb is not None:
                self._center_on(bb.center, max(max(bb.size), 64))
                return True
        if target.position is not None:
            self._center_on(target.position, 256)
            return True
        return False

    def go_to_leak(self) -> None:
        pts = self.controller.editor.leak_points
        if pts:
            self._center_on(pts[0], 512)

    def _update_leak_button(self) -> None:
        self.btn_leak.setEnabled(bool(self.controller.editor.leak_points))

    # ---- Ablauf --------------------------------------------------------------------------
    def _on_started(self, plan: CompilePlan) -> None:
        self.list.clear()
        self.progress.clear()
        self.btn_cancel.setEnabled(True)
        self.status.setText(self.tr("Starte {0} …").format(plan.map_name))

    def _on_finished(self, result: CompileResult) -> None:
        self.btn_cancel.setEnabled(False)
        self.progress.clear()
        secs = f"{result.seconds:.1f} s"
        if result.cancelled:
            text, color = self.tr("Abgebrochen nach {0}").format(secs), "#f0c85a"
        elif result.ok:
            text = self.tr("Fertig in {0}. {1} Warnungen.").format(secs, result.warnings)
            if result.leaked:
                text += " " + self.tr("Achtung: Die Map hat ein Leck.")
            color = "#7fd67f" if not result.leaked else "#f0c85a"
        elif result.leaked:
            text, color = self.tr("Leck gefunden. Die rote Linie zeigt den Weg ins Leere."), "#ff6e64"
        else:
            text = self.tr("Fehlgeschlagen bei {0}. {1} Fehler.").format(result.failed_step, result.errors)
            color = "#ff6e64"
        self.status.setText(f'<span style="color:{color}">{text}</span>')
        self._update_leak_button()
