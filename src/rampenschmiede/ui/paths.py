"""Ablageorte für Einstellungen und Arbeitsdateien des Programms."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths

#: Überschreibt den Datenordner (für Tests und portable Installationen)
DATA_DIR_ENV = "RAMPENSCHMIEDE_DATA_DIR"


def data_dir() -> Path:
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        p = Path(override)
    else:
        base = QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)
        p = Path(base) if base else Path.home() / ".rampenschmiede"
    p.mkdir(parents=True, exist_ok=True)
    return p


def profiles_file() -> Path:
    return data_dir() / "spielprofile.json"


def prefabs_dir() -> Path:
    """Eigene Prefabs der Bibliothek."""
    d = data_dir() / "prefabs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def textures_dir() -> Path:
    """Eigene Texturen (importiert oder vom Rampen-Assistenten erzeugt), Aufbau wie ein
    Spielordner: materials/rampenschmiede/..."""
    d = data_dir() / "texturen"
    (d / "materials").mkdir(parents=True, exist_ok=True)
    return d


def compile_dir(project_path: Path | None, create: bool = True) -> Path:
    """Arbeitsordner fürs Kompilieren. Neben dem Projekt, damit nie eine fremde VMF
    überschrieben wird, in einem eigenen Unterordner."""
    if project_path is not None:
        d = project_path.parent / f"{project_path.stem}_kompilieren"
    else:
        d = data_dir() / "kompilieren"
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d
