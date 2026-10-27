"""Aus Profil und Einstellungen wird eine Liste von Schritten.

Der Plan ist reine Beschreibung, ausgeführt wird er vom CompileRunner. So lässt sich
im Dialog vorher zeigen, welche Befehle genau laufen.
"""
from __future__ import annotations

import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..profiles import GameProfile
from .settings import CompileSettings


@dataclass
class ToolStep:
    label: str
    tool: str               # vbsp, vvis, vrad
    program: str
    args: list[str]
    cwd: str

    def command_line(self) -> str:
        return " ".join(_quote(a) for a in [self.program, *self.args])


@dataclass
class CopyStep:
    label: str
    source: str
    target: str


@dataclass
class WriteStep:
    """Textdatei schreiben (z. B. Momentum-Zonen), an jedes Ziel dieselbe."""
    label: str
    targets: list[str]
    text: str


@dataclass
class LaunchStep:
    label: str
    program: str
    args: list[str]

    def command_line(self) -> str:
        return " ".join(_quote(a) for a in [self.program, *self.args])


Step = ToolStep | CopyStep | WriteStep | LaunchStep


@dataclass
class CompilePlan:
    vmf_path: str
    map_name: str
    steps: list[Step] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def bsp_path(self) -> str:
        return str(Path(self.vmf_path).with_suffix(".bsp"))

    @property
    def pointfile_path(self) -> str:
        return str(Path(self.vmf_path).with_suffix(".lin"))


def _quote(arg: str) -> str:
    if sys.platform == "win32":
        return f'"{arg}"' if (not arg or any(c in arg for c in ' \t"')) else arg
    return shlex.quote(arg)


def split_args(text: str) -> list[str]:
    """Freitext-Parameter wie in einer Kommandozeile zerlegen (Anführungszeichen erlaubt)."""
    try:
        return shlex.split(text, posix=True)
    except ValueError:
        return text.split()


_NAME_RE = re.compile(r"[^A-Za-z0-9_\-]+")


def map_name_for(title: str) -> str:
    """Dateiname, den Source-Spiele sicher laden: keine Leerzeichen und Umlaute."""
    name = _NAME_RE.sub("_", title.strip()).strip("_")
    return name or "unbenannt"


def build_plan(profile: GameProfile, vmf_path: str | Path, settings: CompileSettings,
               momentum_zones: str | None = None) -> CompilePlan:
    """`momentum_zones`: Inhalt der Zonendatei. Nur bei Momentum-Profilen wird sie neben die
    BSP und (beim Kopieren ins Spiel) nach maps/zones/local geschrieben."""
    vmf = Path(vmf_path).absolute()  # die Compiler laufen im VMF-Ordner, relative Pfade gingen ins Leere
    base = str(vmf.with_suffix(""))
    plan = CompilePlan(str(vmf), vmf.stem)
    game = ["-game", profile.game_dir]
    cwd = str(vmf.parent)
    for tool, run, extra in (
        ("vbsp", settings.run_vbsp, settings.vbsp_args),
        ("vvis", settings.run_vvis and settings.run_vbsp, settings.vvis_args),
        ("vrad", settings.run_vrad and settings.run_vbsp, settings.vrad_args),
    ):
        if not run:
            continue
        program = profile.tool_path(tool)
        if program is None:
            plan.problems.append(f"{tool} nicht gefunden (Spielprofil prüfen)")
            continue
        plan.steps.append(ToolStep(tool.upper(), tool, str(program), [*game, *split_args(extra), base], cwd))
    if not (Path(profile.game_dir) / "gameinfo.txt").is_file():
        plan.problems.append("Spielordner mit gameinfo.txt fehlt (Spielprofil prüfen)")

    if settings.copy_to_game:
        target = profile.maps_dir / f"{plan.map_name}.bsp"
        plan.steps.append(CopyStep("Kopieren", plan.bsp_path, str(target)))
    if momentum_zones and profile.key == "momentum":
        targets = [str(vmf.with_suffix(".json"))]
        if settings.copy_to_game:
            targets.append(str(profile.maps_dir / "zones" / "local" / f"{plan.map_name}.json"))
        plan.steps.append(WriteStep("Momentum-Zonen", targets, momentum_zones))
    if settings.launch_game:
        launch_args = [*split_args(profile.launch_args), *split_args(settings.extra_launch_args),
                       "+map", plan.map_name]
        if profile.launch_via_steam and profile.steam_exe and profile.app_id:
            plan.steps.append(LaunchStep("Spiel starten", profile.steam_exe,
                                         ["-applaunch", str(profile.app_id), *launch_args]))
        elif profile.game_exe:
            plan.steps.append(LaunchStep("Spiel starten", profile.game_exe,
                                         ["-game", profile.game_dir, *launch_args]))
        else:
            plan.problems.append("Weder Steam noch Spiel-Exe bekannt, Starten nicht möglich")
    return plan
