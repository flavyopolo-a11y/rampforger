"""Spielprofile: wo ein Spiel liegt, wo seine Compiler sind und wie es startet.

Neue Spiele kommen als weiterer Eintrag in KNOWN_GAMES dazu. Alle Pfade lassen sich
im Profil-Dialog von Hand setzen, die Erkennung füllt sie nur vor.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .steam import find_game_folders, steam_executable, steam_roots


@dataclass(frozen=True)
class GameSpec:
    """Was wir über ein Spiel wissen, um es zu finden."""

    key: str
    name: str
    app_id: int
    folder_names: tuple[str, ...]   # unter steamapps/common
    mod_dir: str                    # Ordner mit gameinfo.txt
    exe_names: tuple[str, ...]      # Spiel-Exe im Installationsordner, beste zuerst
    bin_dirs: tuple[str, ...] = ("bin/x64", "bin/win64", "bin")
    fgd_names: tuple[str, ...] = ()


KNOWN_GAMES: dict[str, GameSpec] = {
    "css": GameSpec(
        key="css",
        name="Counter-Strike: Source",
        app_id=240,
        folder_names=("Counter-Strike Source",),
        mod_dir="cstrike",
        exe_names=("cstrike_win64.exe", "cstrike.exe", "hl2.exe", "cstrike.sh", "hl2.sh"),
        fgd_names=("cstrike.fgd",),
    ),
    "momentum": GameSpec(
        key="momentum",
        name="Momentum Mod",
        app_id=1802710,
        folder_names=("Momentum Mod Playtest", "Momentum Mod"),
        mod_dir="momentum",
        exe_names=("momentum.exe", "momentum_win64.exe", "chaos.exe", "hl2_win64.exe", "hl2.exe", "momentum.sh"),
        fgd_names=("momentum.fgd",),
    ),
}

COMPILE_TOOLS = ("vbsp", "vvis", "vrad", "bspzip")


@dataclass
class GameProfile:
    key: str                  # Spiel-Typ aus KNOWN_GAMES oder "custom"
    name: str
    game_dir: str = ""        # Ordner mit gameinfo.txt, z. B. ...\Counter-Strike Source\cstrike
    bin_dir: str = ""         # Ordner mit vbsp.exe usw.
    game_exe: str = ""
    app_id: int = 0
    steam_exe: str = ""
    fgds: list[str] = field(default_factory=list)
    launch_args: str = "-novid -console -dev"
    #: Starten über Steam (-applaunch) statt direkt über die Exe
    launch_via_steam: bool = True

    @property
    def maps_dir(self) -> Path:
        return Path(self.game_dir) / "maps"

    def tool_path(self, tool: str) -> Path | None:
        if not self.bin_dir:
            return None
        # .bat/.cmd erlauben eigene Wrapper (und die Test-Attrappen unter Windows)
        for name in (f"{tool}.exe", tool, f"{tool}.bat", f"{tool}.cmd"):
            p = Path(self.bin_dir) / name
            if p.is_file():
                return p
        return None

    def problems(self) -> list[str]:
        """Was fehlt, damit Kompilieren und Testen klappt (leer = alles gut)."""
        out = []
        if not self.game_dir or not (Path(self.game_dir) / "gameinfo.txt").is_file():
            out.append("Spielordner mit gameinfo.txt fehlt")
        for tool in ("vbsp", "vvis", "vrad"):
            if self.tool_path(tool) is None:
                out.append(f"{tool} nicht gefunden")
        if self.launch_via_steam:
            if not self.steam_exe or not Path(self.steam_exe).is_file() or not self.app_id:
                out.append("Steam oder App-ID fehlt zum Starten")
        elif not self.game_exe or not Path(self.game_exe).is_file():
            out.append("Spiel-Exe fehlt zum Starten")
        return out

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "GameProfile":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


def _first_existing(base: Path, names: tuple[str, ...]) -> Path | None:
    for n in names:
        p = base / n
        if p.is_file():
            return p
    return None


def _find_bin(install: Path, spec: GameSpec) -> Path | None:
    for d in spec.bin_dirs:
        p = install / d
        if any((p / f"vbsp{ext}").is_file() for ext in (".exe", "")):
            return p
    return None


def _find_fgds(install: Path, bin_dir: Path | None, spec: GameSpec) -> list[str]:
    """Spiel-FGD zuerst. Basis-FGDs lädt der FGD-Parser über @include selbst nach."""
    places = [d for d in (bin_dir, install / "bin", install / spec.mod_dir) if d is not None]
    found: list[str] = []
    for d in places:
        for n in spec.fgd_names:
            p = d / n
            if p.is_file() and str(p) not in found:
                found.append(str(p))
    if not found:
        for d in places:
            for p in sorted(d.glob("*.fgd")) if d.is_dir() else ():
                if p.stem.lower() not in ("base", "halflife2", "hl2mp") and str(p) not in found:
                    found.append(str(p))
    return found


def profile_from_install(spec: GameSpec, install: Path, steam_root: Path | None = None) -> GameProfile | None:
    game_dir = install / spec.mod_dir
    if not (game_dir / "gameinfo.txt").is_file():
        return None
    bin_dir = _find_bin(install, spec)
    exe = _first_existing(install, spec.exe_names)
    steam = steam_executable(steam_root) if steam_root else None
    return GameProfile(
        key=spec.key,
        name=spec.name,
        game_dir=str(game_dir),
        bin_dir=str(bin_dir) if bin_dir else "",
        game_exe=str(exe) if exe else "",
        app_id=spec.app_id,
        steam_exe=str(steam) if steam else "",
        fgds=_find_fgds(install, bin_dir, spec),
        launch_via_steam=steam is not None,
    )


def detect_profiles(roots: list[Path] | None = None) -> list[GameProfile]:
    """Alle bekannten Spiele, die in einer Steam-Bibliothek installiert sind."""
    roots = steam_roots() if roots is None else roots
    found: list[GameProfile] = []
    for spec in KNOWN_GAMES.values():
        for root in roots:
            for install in find_game_folders(list(spec.folder_names), [root]):
                prof = profile_from_install(spec, install, root)
                if prof is not None and all(p.game_dir != prof.game_dir for p in found):
                    found.append(prof)
    return found


# ---- Speichern -------------------------------------------------------------------------

@dataclass
class ProfileStore:
    profiles: list[GameProfile] = field(default_factory=list)
    active: str = ""  # Name des aktiven Profils

    def active_profile(self) -> GameProfile | None:
        for p in self.profiles:
            if p.name == self.active:
                return p
        return self.profiles[0] if self.profiles else None

    def merge_detected(self, detected: list[GameProfile]) -> int:
        """Neu gefundene Spiele ergänzen, von Hand gesetzte Profile bleiben. Gibt die Anzahl neuer zurück."""
        known = {os.path.normcase(p.game_dir) for p in self.profiles}
        names = {p.name for p in self.profiles}
        added = 0
        for p in detected:
            if os.path.normcase(p.game_dir) in known:
                continue
            base, n = p.name, 2
            while p.name in names:
                p.name = f"{base} ({n})"
                n += 1
            self.profiles.append(p)
            names.add(p.name)
            added += 1
        if not self.active and self.profiles:
            self.active = self.profiles[0].name
        return added

    def to_dict(self) -> dict:
        return {"version": 1, "active": self.active, "profiles": [p.to_dict() for p in self.profiles]}

    @classmethod
    def from_dict(cls, data: dict) -> "ProfileStore":
        return cls([GameProfile.from_dict(p) for p in data.get("profiles", [])], data.get("active", ""))

    def save(self, path: str | os.PathLike[str]) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "ProfileStore":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls.from_dict(data) if isinstance(data, dict) else cls()
