"""Welt-Stile: Himmel, Sonne, Nebel und Farben einer Map mit einem Klick.

Ein Stil nennt mögliche Himmel und Wand-Materialien aus CS:S und HL2. Welche davon es gibt,
entscheidet die Material-Bibliothek des Spiels zur Laufzeit; fehlt alles, nimmt die
Rampenschmiede einen Standard-Himmel und erzeugt die Wand-Textur aus der Stilfarbe. Rampen
bekommen immer Farb-Texturen wie beim Rampen-Assistenten, damit sie im Spiel gut lesbar sind.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..commands import AddObjects, Command, MacroCommand, ReplaceObjects, SetWorldKeyvalues
from ..model import Entity, MapDocument
from .library import MaterialLibrary, normalize
from .theme import SetTheme, Theme, apply_theme

RGB = tuple[int, int, int]
DEFAULT_SKY = "sky_day01_01"
#: Ordner, die als Wand-Material nie in Frage kommen
_NOT_WALLS = ("tools/", "skybox/", "decals/", "overlays/", "effects/", "models/", "sprites/", "particle/",
              "dev/", "editor/", "console/", "vgui/", "debug/", "water/", "liquids/", "lights/", "glass/")


@dataclass(frozen=True)
class Fog:
    color: str
    start: int
    end: int


@dataclass(frozen=True)
class WorldStyle:
    key: str
    name: str
    description: str
    skies: tuple[str, ...]
    sun: str            # _light: "R G B Helligkeit"
    ambient: str        # _ambient
    pitch: int          # Sonnenhöhe, negativ = von oben
    yaw: int            # Sonnenrichtung
    fog: Fog | None
    ramp: RGB
    lines: RGB
    wall: RGB
    walls: tuple[str, ...] = ()                    # Wand-Materialien, erstes vorhandenes gewinnt
    wall_words: tuple[tuple[str, ...], ...] = ()   # sonst: erstes Material mit allen Wörtern


STYLES: tuple[WorldStyle, ...] = (
    WorldStyle("tag", "Sonniger Tag", "Klarer Himmel, warmes Sonnenlicht, helle Rampen mit blauen Linien.",
               ("sky_day01_01", "sky_day01_05"), "255 244 220 350", "150 175 210 60", -55, 30, None,
               (214, 218, 224), (47, 111, 214), (120, 124, 130),
               ("concrete/concretewall001a", "concrete/concretefloor001a"), (("concrete", "wall"), ("concrete",))),
    WorldStyle("abend", "Sonnenuntergang", "Tiefe Sonne, oranges Licht, leichter warmer Dunst.",
               ("sky_day02_09", "sky_day01_08", "sky_day02_06"), "255 170 110 260", "120 100 140 50", -20, 200,
               Fog("255 170 120", 2048, 16384), (60, 40, 70), (255, 140, 60), (95, 72, 80),
               ("brick/brickwall001a", "brick/brickwall003a"), (("brick", "wall"), ("brick",))),
    WorldStyle("nacht", "Nacht", "Dunkler Himmel, kühles Mondlicht, leuchtende Linien.",
               ("sky_day01_09", "sky_borealis01", "sky_day02_10"), "140 160 255 120", "40 50 90 40", -70, 120,
               Fog("20 25 50", 1024, 12000), (24, 26, 40), (80, 200, 255), (40, 44, 60),
               ("metal/metalwall001a", "metal/metalwall048a"), (("metal", "wall"), ("metal",))),
    WorldStyle("wueste", "Wüste", "Grelle Sonne, sandige Farben, weiter Dunst.",
               ("sky_dust", "sky_cs15_daylight02_hdr", "sky_day01_04"), "255 230 190 400", "200 180 150 70",
               -60, 60, Fog("230 210 170", 4096, 24000), (200, 170, 120), (140, 80, 40), (190, 160, 120),
               ("de_dust/stonewall02", "de_dust/sitebwall01"), (("dust", "wall"), ("sand",), ("plaster",))),
    WorldStyle("industrie", "Industrie", "Bedeckter Himmel, Metall und Beton, gelbe Warnlinien.",
               ("sky_day02_05", "sky_day01_06"), "220 225 235 200", "130 135 145 60", -65, 300,
               Fog("120 125 130", 2048, 16000), (110, 112, 118), (255, 200, 40), (80, 82, 88),
               ("metal/metalfloor001a", "metal/metalwall048a"), (("metal", "floor"), ("metal",))),
    WorldStyle("neon", "Neon", "Nachthimmel, violettes Licht, Rampen mit pinken Linien.",
               ("sky_day01_09", "sky_borealis01"), "120 60 255 100", "60 20 90 50", -80, 0,
               Fog("30 10 50", 1536, 12000), (27, 27, 43), (255, 43, 214), (42, 36, 64)),
)
STYLE_BY_KEY = {s.key: s for s in STYLES}


def pick_sky(style: WorldStyle, library: MaterialLibrary | None) -> str:
    """Ersten Himmel des Stils, den das Spiel hat (Skybox-Materialien heißen skybox/<name>up)."""
    if library is None:
        return style.skies[0] if style.skies else DEFAULT_SKY
    for sky in style.skies:
        if library.exists(f"skybox/{sky}up") or library.exists(f"skybox/{sky}rt"):
            return sky
    return DEFAULT_SKY


def pick_wall(style: WorldStyle, library: MaterialLibrary | None) -> str:
    """Wand-Material aus dem Spiel, leer wenn keins passt (dann Farb-Textur erzeugen)."""
    if library is None:
        return ""
    for name in style.walls:
        if library.exists(name):
            return normalize(name)
    if not style.wall_words:
        return ""
    names = [n for n in library.names() if not n.startswith(_NOT_WALLS)]
    for words in style.wall_words:
        for n in names:
            if all(w in n for w in words):
                return n
    return ""


def _set_kv(kvs: tuple[tuple[str, str], ...], key: str, value: str) -> tuple[tuple[str, str], ...]:
    out = [(k, value) if k == key else (k, v) for k, v in kvs]
    if not any(k == key for k, _ in kvs):
        out.append((key, value))
    return tuple(out)


def _anchor(doc: MapDocument) -> tuple[int, int, int]:
    bb = doc.bbox()
    if bb is None:
        return (0, 0, 64)
    return (round((bb.mins[0] + bb.maxs[0]) / 2), round((bb.mins[1] + bb.maxs[1]) / 2), round(bb.maxs[2] - 64))


def sky_command(doc: MapDocument, sky: str) -> Command:
    """Nur den Himmel der Map wechseln (ein Undo-Schritt)."""
    return SetWorldKeyvalues(_set_kv(doc.world_keyvalues, "skyname", sky), "Himmel ändern")


def style_command(doc: MapDocument, style: WorldStyle, sky: str, theme: Theme) -> Command:
    """Himmel, Sonne, Nebel und Thema in einem Undo-Schritt setzen. Vorhandene Sonne und
    Nebel-Steuerung werden angepasst, fehlende neu angelegt."""
    cmds: list[Command] = [SetWorldKeyvalues(_set_kv(doc.world_keyvalues, "skyname", sky), "Himmel")]
    x, y, z = _anchor(doc)
    entities = [o for o in doc.objects() if isinstance(o, Entity)]
    changed: list[Entity] = []
    added: list[Entity] = []

    sun_kvs = (("_light", style.sun), ("_ambient", style.ambient), ("pitch", str(style.pitch)),
               ("angles", f"{style.pitch} {style.yaw} 0"))
    suns = [e for e in entities if e.classname == "light_environment"]
    if suns:
        for sun in suns:
            for k, v in sun_kvs:
                sun = sun.with_keyvalue(k, v)
            changed.append(sun)
    else:
        added.append(Entity(id=doc.new_id(), classname="light_environment",
                            keyvalues=(("origin", f"{x} {y} {z}"), *sun_kvs)))

    fogs = [e for e in entities if e.classname == "env_fog_controller"]
    if style.fog is not None:
        fog_kvs = (("fogenable", "1"), ("fogblend", "0"), ("fogcolor", style.fog.color),
                   ("fogcolor2", style.fog.color), ("fogstart", str(style.fog.start)),
                   ("fogend", str(style.fog.end)), ("fogmaxdensity", "1"), ("fogdir", "1 0 0"))
        if fogs:
            for fog in fogs:
                for k, v in fog_kvs:
                    fog = fog.with_keyvalue(k, v)
                changed.append(fog)
        else:
            added.append(Entity(id=doc.new_id(), classname="env_fog_controller",
                                keyvalues=(("origin", f"{x} {y + 64} {z}"), ("spawnflags", "1"), *fog_kvs)))
    else:
        changed += [f.with_keyvalue("fogenable", "0") for f in fogs]

    if changed:
        cmds.append(ReplaceObjects(changed, "Licht und Nebel"))
    if added:
        cmds.append(AddObjects(added, "Licht und Nebel"))
    cmds.append(SetTheme(theme))
    themed = apply_theme(doc, theme)
    if themed is not None:
        cmds.append(themed)
    return MacroCommand(cmds, f"Welt-Stil „{style.name}“")


__all__ = ["DEFAULT_SKY", "STYLES", "STYLE_BY_KEY", "Fog", "WorldStyle", "pick_sky", "pick_wall", "sky_command",
           "style_command"]
