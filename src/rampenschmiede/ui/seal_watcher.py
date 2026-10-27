"""Prüft nach jeder Änderung im Hintergrund, ob die Map dicht ist."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.validation.seal import SealResult, check_seal
from .editor import EditorContext

DELAY_MS = 700
#: Kleineres Raster als vor dem Kompilieren, damit die Prüfung auch bei großen Maps flott bleibt
LIVE_MAX_CELLS = 600_000


class SealWatcher(QObject):
    checked = Signal(object)  # SealResult
    _done = Signal(int, object)

    def __init__(self, editor: EditorContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.result: SealResult | None = None
        self.enabled = True
        self._generation = 0
        self._running = False
        self._pending = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DELAY_MS)
        self._timer.timeout.connect(self._start)
        self._done.connect(self._finish)
        editor.document_changed.connect(self.schedule)
        editor.document_replaced.connect(self.schedule)

    def schedule(self) -> None:
        self._generation += 1
        if self.enabled:
            self._timer.start()

    def check_now(self, max_cells: int | None = None) -> SealResult:
        """Blockierend, für die Vorab-Prüfung beim Kompilieren."""
        kwargs = {} if max_cells is None else {"max_cells": max_cells}
        return check_seal(self.editor.doc, **kwargs)

    def _start(self) -> None:
        if self._running:
            self._pending = True
            return
        self._running = True
        gen = self._generation
        snap = self.editor.doc.snapshot()

        def work() -> None:
            try:
                res = check_seal(snap, max_cells=LIVE_MAX_CELLS)
            except Exception:  # eine kaputte Geometrie darf die Prüfung nicht abstürzen lassen
                res = None
            self._done.emit(gen, res)

        threading.Thread(target=work, daemon=True, name="dicht-pruefung").start()

    def _finish(self, gen: int, res: SealResult | None) -> None:
        self._running = False
        if self._pending:
            self._pending = False
            self._start()
            return
        if gen != self._generation or res is None:
            return  # inzwischen geändert, die nächste Prüfung läuft schon
        self.result = res
        self.checked.emit(res)
