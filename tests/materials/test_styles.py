"""Welt-Stile: Himmel, Sonne, Nebel und Wand-Material aus dem Spiel."""
from rampenschmiede.core.commands import AddObjects, CommandStack, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.materials import MaterialLibrary
from rampenschmiede.core.materials.styles import (
    DEFAULT_SKY,
    STYLE_BY_KEY,
    STYLES,
    WorldStyle,
    pick_sky,
    pick_wall,
    style_command,
)
from rampenschmiede.core.materials.theme import Theme, get_theme
from rampenschmiede.core.model import Entity, MapDocument

from .fakegame import make_game, vmt_text

THEME = Theme("R/SURF", "R/SEITE", "W/WAND")


def _doc():
    doc = MapDocument()
    stack = CommandStack(doc)
    floor = solids_from_faces(doc, primitives.block((0, 0, -64), (512, 512, 0)))[0]
    stack.push(AddObjects([floor]))
    return doc, stack, floor


def _entities(doc, cls):
    return [o for o in doc.objects() if isinstance(o, Entity) and o.classname == cls]


def test_styles_are_complete():
    assert len({s.key for s in STYLES}) == len(STYLES) >= 5
    for s in STYLES:
        assert s.skies and len(s.sun.split()) == 4 and s.pitch < 0


def test_pick_sky_and_wall(tmp_path):
    game = make_game(tmp_path)
    sky = game / "materials" / "skybox"
    sky.mkdir(parents=True)
    (sky / "sky_testup.vmt").write_text(vmt_text("skybox/sky_testup", "UnlitGeneric"))
    lib = MaterialLibrary.for_game(game)
    style = WorldStyle("x", "X", "", ("gibtsnicht", "sky_test"), "1 1 1 1", "1 1 1 1", -45, 0, None,
                       (1, 1, 1), (2, 2, 2), (3, 3, 3), ("gibts/nicht",), (("blau",),))
    assert pick_sky(style, lib) == "sky_test"
    assert pick_wall(style, lib) == "lose/blau"
    other = WorldStyle("y", "Y", "", ("nein",), "1 1 1 1", "1 1 1 1", -45, 0, None,
                       (1, 1, 1), (2, 2, 2), (3, 3, 3), ("test/rot",))
    assert pick_sky(other, lib) == DEFAULT_SKY
    assert pick_wall(other, lib) == "test/rot"
    assert pick_wall(STYLE_BY_KEY["neon"], lib) == ""
    assert pick_sky(STYLE_BY_KEY["tag"], None) == "sky_day01_01"


def test_style_command_sets_world_and_undoes():
    doc, stack, floor = _doc()
    style = STYLE_BY_KEY["abend"]
    stack.push(style_command(doc, style, "sky_test", THEME))
    assert dict(doc.world_keyvalues)["skyname"] == "sky_test"
    (sun,) = _entities(doc, "light_environment")
    assert sun.get("_light") == style.sun and sun.get("angles") == f"{style.pitch} {style.yaw} 0"
    (fog,) = _entities(doc, "env_fog_controller")
    assert fog.get("fogenable") == "1" and fog.get("fogend") == str(style.fog.end)
    assert get_theme(doc).ramp == "R/SURF"
    assert {f.material for f in doc.get(floor.id).faces} == {"W/WAND"}
    stack.undo()
    assert dict(doc.world_keyvalues)["skyname"] == "sky_day01_01"
    assert not _entities(doc, "light_environment") and not _entities(doc, "env_fog_controller")
    assert not get_theme(doc).is_set()


def test_style_reuses_sun_and_disables_fog():
    doc, stack, _ = _doc()
    stack.push(style_command(doc, STYLE_BY_KEY["nacht"], "a", THEME))
    stack.push(style_command(doc, STYLE_BY_KEY["tag"], "b", THEME))
    assert len(_entities(doc, "light_environment")) == 1
    (fog,) = _entities(doc, "env_fog_controller")
    assert fog.get("fogenable") == "0"
    assert _entities(doc, "light_environment")[0].get("_light") == STYLE_BY_KEY["tag"].sun
