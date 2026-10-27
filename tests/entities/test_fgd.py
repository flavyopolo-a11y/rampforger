"""Entity-Beschreibungen aus der FGD-Datenbank."""
from rampenschmiede.core.entities.fgd import builtin_catalog, flag_bits, load_catalog


def test_light_has_color_flags_and_name_first():
    light = builtin_catalog().get("light")
    assert light.kind == "point"
    assert light.keys[0].name == "targetname"
    color = light.key("_light")
    assert color.kind == "color" and color.default == "255 255 255 200"
    flags = light.key("spawnflags")
    assert flags.kind == "flags" and (1, "Initially dark", False) in flags.flags
    assert {"TurnOn", "TurnOff", "Toggle"} <= {i.name for i in light.inputs}


def test_engine_base_noise_is_filtered():
    relay = builtin_catalog().get("logic_relay")
    names = {k.name.lower() for k in relay.keys}
    assert "startdisabled" in names and "targetname" in names
    assert not any(n.startswith(("gmod_", "vscript")) for n in names)
    assert "nextthink" not in names
    outs = {o.name for o in relay.outputs}
    assert {"OnTrigger", "OnUser1"} <= outs


def test_brush_entity_defaults_and_lookup_ignore_case():
    cat = builtin_catalog()
    tele = cat.get("Trigger_Teleport")
    assert tele.kind == "solid"
    assert dict(tele.defaults())["spawnflags"] == "1"  # Spieler standardmäßig an
    assert "trigger_teleport" in cat and "kein_entity" not in cat
    assert "trigger_teleport" in cat.classnames("solid") and "light" not in cat.classnames("solid")


def test_own_fgd_overrides_and_extends(tmp_path):
    fgd = tmp_path / "eigen.fgd"
    fgd.write_text('@PointClass = trigger_momentum_info : "Nur ein Test"\n[\n'
                   '\tzahl(integer) : "Eine Zahl" : 5 : "Hilfe"\n'
                   '\tfarbe(choices) : "Farbe" : 0 =\n\t[\n\t\t0 : "Rot"\n\t\t1 : "Blau"\n\t]\n]\n',
                   encoding="utf-8")
    cat = load_catalog([fgd])
    info = cat.get("trigger_momentum_info")
    assert info.desc == "Nur ein Test"
    assert info.key("zahl").default == "5" and info.key("zahl").desc == "Hilfe"
    assert info.key("farbe").choices == (("0", "Rot"), ("1", "Blau"))
    assert cat.get("light") is not None  # eingebaute bleiben


def test_flag_bits():
    assert flag_bits("4097") == 4097 and flag_bits("") == 0 and flag_bits("x") == 0
