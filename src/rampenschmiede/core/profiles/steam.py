"""Steam finden und installierte Spiele in allen Bibliotheken suchen."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from srctools.keyvalues import Keyvalues


def steam_roots() -> list[Path]:
    """Mögliche Steam-Ordner, der aus der Registry zuerst."""
    found: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg

            for hive, key, name in (
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
            ):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        found.append(Path(winreg.QueryValueEx(k, name)[0]))
                except OSError:
                    pass
        except ImportError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(env)
            if base:
                found.append(Path(base) / "Steam")
    else:
        home = Path.home()
        found += [home / ".steam" / "steam", home / ".local" / "share" / "Steam",
                  home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"]
    result: list[Path] = []
    for p in found:
        try:
            resolved = p.resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in result:
            result.append(resolved)
    return result


def steam_executable(root: Path) -> Path | None:
    for name in ("steam.exe", "steam.sh", "steam"):
        p = root / name
        if p.is_file():
            return p
    return None


def library_folders(root: Path) -> list[Path]:
    """Alle Steam-Bibliotheken laut libraryfolders.vdf, die Hauptbibliothek zuerst."""
    libs = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        try:
            kv = Keyvalues.parse(vdf.read_text(encoding="utf-8", errors="replace"), str(vdf))
        except Exception:  # kaputte Datei: nur die Hauptbibliothek nutzen
            kv = None
        if kv is not None:
            for block in kv.find_all("libraryfolders"):
                for entry in block:
                    if entry.has_children():
                        path = entry["path", ""]
                    else:  # altes Format: "1" "D:\\Games\\Steam"
                        path = entry.value if entry.name.isdigit() else ""
                    if path:
                        p = Path(path)
                        if p not in libs:
                            libs.append(p)
    return [p for p in libs if (p / "steamapps").is_dir()]


def find_game_folders(folder_names: list[str], roots: list[Path] | None = None) -> list[Path]:
    """Installationsordner (steamapps/common/<Name>) eines Spiels in allen Bibliotheken."""
    hits: list[Path] = []
    for root in roots if roots is not None else steam_roots():
        for lib in library_folders(root):
            for name in folder_names:
                p = lib / "steamapps" / "common" / name
                if p.is_dir() and p not in hits:
                    hits.append(p)
    return hits
