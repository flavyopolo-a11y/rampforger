"""Startet Kompiliervorgänge im Hintergrund und meldet Fortschritt per Signal."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..core.compile import (
    CompilePlan,
    CompileResult,
    CompileRunner,
    CompileSettings,
    Level,
    LogLine,
    Target,
    build_plan,
    map_name_for,
    resolve,
)
from ..core.io.vmf import ExportResult, save_vmf
from ..core.profiles import GameProfile
from ..core.zones import collect_zones, momentum_zones
from .editor import EditorContext
from .paths import compile_dir


class CompileController(QObject):
    started = Signal(object)        # CompilePlan
    line = Signal(object)           # LogLine
    progress = Signal(str)          # angefangene Zeile ("0...1...2")
    step = Signal(str)              # Name des laufenden Schritts
    finished = Signal(object)       # CompileResult

    def __init__(self, editor: EditorContext, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.runner: CompileRunner | None = None
        self.thread: threading.Thread | None = None
        self.export: ExportResult | None = None
        self.plan: CompilePlan | None = None
        self.last_result: CompileResult | None = None
        self.finished.connect(self._on_finished)
        editor.document_replaced.connect(self._forget_export)

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def map_name(self) -> str:
        path = self.editor.file_path or self.editor.import_path
        return map_name_for(path.stem if path else "unbenannt")

    def prepare(self, profile: GameProfile, settings: CompileSettings) -> CompilePlan:
        """Plan ohne Seiteneffekte, für die Vorschau im Dialog."""
        folder = compile_dir(self.editor.file_path or self.editor.import_path, create=False)
        vmf = folder / f"{self.map_name()}.vmf"
        zones = momentum_zones(collect_zones(self.editor.doc))
        text = json.dumps(zones, indent=2) if zones else None
        return build_plan(profile, vmf, settings, momentum_zones=text)

    def start(self, profile: GameProfile, settings: CompileSettings, notes: list[LogLine] | None = None) -> bool:
        """`notes` erscheinen nach dem Start oben im Log (z. B. Ergebnis der Vorab-Prüfung)."""
        if self.running:
            return False
        plan = self.prepare(profile, settings)
        self.editor.set_leak_path([])
        self.plan = plan
        self.started.emit(plan)
        for note in notes or ():
            self.line.emit(note)
        if not plan.problems:
            try:
                Path(plan.vmf_path).parent.mkdir(parents=True, exist_ok=True)
                self.export = save_vmf(self.editor.doc, plan.vmf_path, for_compile=True)
            except OSError as exc:
                self.line.emit(LogLine(f"VMF konnte nicht geschrieben werden: {exc}", Level.ERROR))
                self.finished.emit(CompileResult(failed_step="VMF schreiben"))
                return False
            self.line.emit(LogLine(f"VMF geschrieben: {plan.vmf_path}"))
        self.runner = CompileRunner(
            plan, settings.stop_on_leak,
            on_line=self.line.emit,
            on_step=lambda _i, s: self.step.emit(s.label),
            on_progress=self.progress.emit,
        )
        runner = self.runner
        self.thread = threading.Thread(target=lambda: self.finished.emit(runner.run()), daemon=True,
                                       name="kompilieren")
        self.thread.start()
        return True

    def cancel(self) -> None:
        if self.runner is not None:
            self.runner.cancel()

    def wait(self, timeout: float | None = None) -> None:
        if self.thread is not None:
            self.thread.join(timeout)

    def resolve(self, line: LogLine) -> Target | None:
        return resolve(line, self.export, self.editor.doc)

    def _on_finished(self, result: CompileResult) -> None:
        self.last_result = result
        if result.pointfile:
            self.editor.set_leak_path(result.pointfile)

    def _forget_export(self) -> None:
        self.export = None


def load_pointfile(editor: EditorContext, path: Path) -> int:
    from ..core.compile import parse_pointfile

    points = parse_pointfile(path.read_text(encoding="utf-8", errors="replace"))
    editor.set_leak_path(points)
    return len(points)
