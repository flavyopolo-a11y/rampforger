"""Automatische Sicherung und Sicherungskopien.

- Alle paar Minuten wird eine geänderte Map in den Ordner „sicherungen“ im Datenordner
  geschrieben (je Map die letzten KEEP_AUTOSAVES).
- Vor dem Überschreiben eines Projekts beim Speichern landet die alte Fassung ebenfalls dort
  (die letzten KEEP_BACKUPS).
- Endete die letzte Sitzung nicht sauber, bietet das Fenster beim Start die neueste
  automatische Sicherung an.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from ..core.io import rsmap
from .paths import data_dir

KEEP_AUTOSAVES = 10
KEEP_BACKUPS = 5
DEFAULT_MINUTES = 5
AUTO_TAG = "auto"
BACKUP_TAG = "vorher"


def backups_dir() -> Path:
    d = data_dir() / "sicherungen"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stem(path: Path | None) -> str:
    return path.stem if path is not None else "unbenannt"


def _prune(stem: str, tag: str, keep: int) -> None:
    files = sorted(backups_dir().glob(f"{stem}_{tag}_*{rsmap.FILE_SUFFIX}"), key=lambda p: p.stat().st_mtime)
    for old in files[:-keep] if keep else files:
        try:
            old.unlink()
        except OSError:
            pass


def _stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"


def backup_before_save(path: Path) -> Path | None:
    """Alte Fassung einer Projektdatei sichern, bevor sie überschrieben wird."""
    if not path.is_file():
        return None
    target = backups_dir() / f"{path.stem}_{BACKUP_TAG}_{_stamp()}{rsmap.FILE_SUFFIX}"
    try:
        shutil.copy2(path, target)
    except OSError:
        return None
    _prune(path.stem, BACKUP_TAG, KEEP_BACKUPS)
    return target


def latest_autosave() -> Path | None:
    files = sorted(backups_dir().glob(f"*_{AUTO_TAG}_*{rsmap.FILE_SUFFIX}"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


class Autosaver(QObject):
    def __init__(self, editor, minutes: int = DEFAULT_MINUTES, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.dirty = False
        self.last_path: Path | None = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.autosave_now)
        editor.history_changed.connect(self._changed)
        editor.document_replaced.connect(lambda: setattr(self, "dirty", False))
        self.set_minutes(minutes)

    def _changed(self) -> None:
        self.dirty = not self.editor.stack.is_clean()

    def set_minutes(self, minutes: int) -> None:
        self.minutes = max(0, int(minutes))
        if self.minutes:
            self.timer.start(self.minutes * 60_000)
        else:
            self.timer.stop()

    def autosave_now(self) -> Path | None:
        """Sichern, wenn sich seit dem letzten Mal etwas geändert hat."""
        if not self.dirty or self.editor.stack.is_clean():
            return None
        stem = _stem(self.editor.file_path)
        target = backups_dir() / f"{stem}_{AUTO_TAG}_{_stamp()}{rsmap.FILE_SUFFIX}"
        try:
            rsmap.save(self.editor.doc, target)
        except OSError as exc:
            self.editor.status_message.emit(f"Automatische Sicherung fehlgeschlagen: {exc}")
            return None
        self.dirty = False
        self.last_path = target
        _prune(stem, AUTO_TAG, KEEP_AUTOSAVES)
        self.editor.status_message.emit(f"Automatisch gesichert ({time.strftime('%H:%M')})")
        return target


__all__ = ["Autosaver", "backup_before_save", "backups_dir", "latest_autosave"]
