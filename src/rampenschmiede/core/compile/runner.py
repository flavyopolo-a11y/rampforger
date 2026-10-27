"""Führt einen CompilePlan aus: Compiler nacheinander, Ausgabe Zeile für Zeile.

`run()` blockiert. Die Oberfläche startet es in einem eigenen Thread und reicht die
Rückrufe per Signal an das Fenster weiter. `cancel()` darf aus jedem Thread kommen.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .logparse import Level, LineSplitter, LogLine, classify, parse_pointfile
from .plan import CompilePlan, CopyStep, LaunchStep, Step, ToolStep


@dataclass
class CompileResult:
    ok: bool = False
    cancelled: bool = False
    leaked: bool = False
    failed_step: str = ""
    errors: int = 0
    warnings: int = 0
    pointfile: list[tuple[float, float, float]] = field(default_factory=list)
    seconds: float = 0.0


class CompileRunner:
    def __init__(
        self,
        plan: CompilePlan,
        settings_stop_on_leak: bool = True,
        on_line: Callable[[LogLine], None] | None = None,
        on_step: Callable[[int, Step], None] | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self.plan = plan
        self.stop_on_leak = settings_stop_on_leak
        self.on_line = on_line or (lambda _l: None)
        self.on_step = on_step or (lambda _i, _s: None)
        self.on_progress = on_progress or (lambda _t: None)
        self._proc: subprocess.Popen | None = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    # ---- Steuerung -------------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # ---- Ablauf ----------------------------------------------------------------------
    def _emit(self, line: LogLine, result: CompileResult) -> None:
        if line.level is Level.ERROR:
            result.errors += 1
        elif line.level is Level.WARNING:
            result.warnings += 1
        if line.leak:
            result.leaked = True
        self.on_line(line)

    def run(self) -> CompileResult:
        result = CompileResult()
        start = time.monotonic()
        try:
            self._run(result)
        finally:
            result.seconds = time.monotonic() - start
        return result

    def _run(self, result: CompileResult) -> None:
        plan = self.plan
        if plan.problems:
            for p in plan.problems:
                self._emit(LogLine(p, Level.ERROR), result)
            result.failed_step = "Vorbereitung"
            return
        lin = Path(plan.pointfile_path)
        if lin.exists():
            lin.unlink()  # alte Leak-Spur darf nicht als neue erscheinen
        for index, step in enumerate(plan.steps):
            if self.cancelled:
                result.cancelled = True
                return
            self.on_step(index, step)
            if isinstance(step, ToolStep):
                self._emit(LogLine(f"==== {step.label} ====", Level.STEP), result)
                self._emit(LogLine(step.command_line(), Level.INFO), result)
                code = self._run_tool(step, result)
                if self.cancelled:
                    result.cancelled = True
                    return
                if step.tool == "vbsp" and lin.exists():
                    result.leaked = True
                    result.pointfile = parse_pointfile(lin.read_text(encoding="utf-8", errors="replace"))
                if code != 0:
                    self._emit(LogLine(f"{step.label} ist mit Code {code} abgebrochen", Level.ERROR), result)
                    result.failed_step = step.label
                    return
                if step.tool == "vbsp" and result.leaked and self.stop_on_leak:
                    self._emit(LogLine(
                        "Die Map hat ein Leck: Ein Weg führt von einer Entity ins Leere. "
                        "Die rote Linie in den Ansichten zeigt den Weg.", Level.ERROR, leak=True), result)
                    result.failed_step = step.label
                    return
            elif isinstance(step, CopyStep):
                if not self._copy(step, result):
                    result.failed_step = step.label
                    return
            elif isinstance(step, LaunchStep):
                self._emit(LogLine(f"==== {step.label} ====", Level.STEP), result)
                self._emit(LogLine(step.command_line(), Level.INFO), result)
                try:
                    _spawn_detached([step.program, *step.args])
                except OSError as exc:
                    self._emit(LogLine(f"Spiel konnte nicht gestartet werden: {exc}", Level.ERROR), result)
                    result.failed_step = step.label
                    return
        result.ok = True

    def _run_tool(self, step: ToolStep, result: CompileResult) -> int:
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        try:
            proc = subprocess.Popen(
                [step.program, *step.args], cwd=step.cwd, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs,
            )
        except OSError as exc:
            self._emit(LogLine(f"{step.program} lässt sich nicht starten: {exc}", Level.ERROR), result)
            return -1
        with self._lock:
            self._proc = proc
        if self.cancelled:  # cancel() kam zwischen Start und Merken
            proc.kill()
        splitter = LineSplitter()
        assert proc.stdout is not None
        fd = proc.stdout.fileno()
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                break
            for line in splitter.feed(chunk):
                self._emit(classify(line), result)
            self.on_progress(splitter.partial)
        for line in splitter.flush():
            self._emit(classify(line), result)
        self.on_progress("")
        code = proc.wait()
        proc.stdout.close()
        with self._lock:
            self._proc = None
        return code

    def _copy(self, step: CopyStep, result: CompileResult) -> bool:
        self._emit(LogLine(f"==== {step.label} ====", Level.STEP), result)
        src = Path(step.source)
        if not src.is_file():
            self._emit(LogLine(f"Keine BSP-Datei entstanden: {src}", Level.ERROR), result)
            return False
        try:
            Path(step.target).parent.mkdir(parents=True, exist_ok=True)
            if src.resolve() != Path(step.target).resolve():
                shutil.copy2(src, step.target)
        except OSError as exc:
            self._emit(LogLine(f"Kopieren fehlgeschlagen: {exc}", Level.ERROR), result)
            return False
        self._emit(LogLine(f"{src.name} -> {step.target}"), result)
        return True


def _spawn_detached(cmd: list[str]) -> None:
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)
