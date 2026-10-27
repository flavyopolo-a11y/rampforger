"""Kompilier-Einstellungen und Voreinstellungen (Schnell, Normal, Final)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace


@dataclass
class CompileSettings:
    preset: str = "normal"
    run_vbsp: bool = True
    run_vvis: bool = True
    run_vrad: bool = True
    vbsp_args: str = ""
    vvis_args: str = ""
    vrad_args: str = ""
    #: Nach einem Leak abbrechen (ohne VIS ist die Map trotzdem spielbar, aber langsam)
    stop_on_leak: bool = True
    copy_to_game: bool = True
    launch_game: bool = True
    extra_launch_args: str = ""
    #: Spiel mit -buildcubemaps starten: baut die Spiegelungen der env_cubemap in die BSP
    build_cubemaps: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CompileSettings":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})


PRESETS: dict[str, tuple[str, str, CompileSettings]] = {
    "geometry": (
        "Nur Geometrie",
        "Sekunden. Ohne VIS und Licht: alles hell, gut zum Testen von Rampen und Sprüngen.",
        CompileSettings(preset="geometry", run_vvis=False, run_vrad=False),
    ),
    "fast": (
        "Schnell",
        "Grobe Sichtbarkeit und schnelles Licht. Für Zwischentests.",
        CompileSettings(preset="fast", vvis_args="-fast", vrad_args="-fast -bounce 2"),
    ),
    "normal": (
        "Normal",
        "Volle Sichtbarkeit und normales Licht.",
        CompileSettings(preset="normal"),
    ),
    "final": (
        "Final",
        "Für die Veröffentlichung: LDR und HDR, weiche Schatten, Props werfen Schatten. Dauert lange.",
        CompileSettings(
            preset="final",
            vrad_args="-both -final -textureshadows -StaticPropLighting -StaticPropPolys",
        ),
    ),
}


def preset(key: str) -> CompileSettings:
    """Eine frische Kopie der Voreinstellung (Starten und Kopieren bleiben an)."""
    return replace(PRESETS[key][2])
