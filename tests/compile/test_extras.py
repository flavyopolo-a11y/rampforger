"""Beim Kompilieren ergänzte Entities: shadow_control und Tonemap bei HDR."""
from rampenschmiede.core.compile.extras import build_extras, is_hdr_build, shadow_angles
from rampenschmiede.core.model import Entity, MapDocument


def _doc(*extra):
    doc = MapDocument()
    sun = Entity(id=doc.new_id(), classname="light_environment",
                 keyvalues=(("origin", "0 0 512"), ("angles", "-50 45 0"), ("pitch", "-50")))
    doc._insert([sun, *[Entity(id=doc.new_id(), classname=c, keyvalues=(("origin", "0 0 0"),)) for c in extra]])
    return doc


def test_hdr_detection():
    assert is_hdr_build("-both -final") and is_hdr_build("-HDR")
    assert not is_hdr_build("-final -textureshadows") and not is_hdr_build("")


def test_shadow_control_follows_the_sun():
    doc = _doc()
    sun = next(doc.entities())
    assert shadow_angles(sun) == "50 45 0"  # Schatten fallen nach unten, in Leuchtrichtung
    out, notes = build_extras(doc, "-final")
    classes = [e.classname for e in out.entities()]
    assert classes.count("shadow_control") == 1 and "env_tonemap_controller" not in classes
    assert len(notes) == 1
    # Die Map selbst bleibt unverändert
    assert [e.classname for e in doc.entities()] == ["light_environment"]


def test_tonemap_only_for_hdr_and_wired_by_logic_auto():
    out, notes = build_extras(_doc(), "-both -final")
    tone = next(e for e in out.entities() if e.classname == "env_tonemap_controller")
    auto = next(e for e in out.entities() if e.classname == "logic_auto")
    assert {o.target for o in auto.outputs} == {tone.get("targetname")}
    assert {o.input for o in auto.outputs} >= {"SetAutoExposureMin", "SetAutoExposureMax", "SetBloomScale"}
    assert len(notes) == 2
    # ohne vrad kein Tonemap
    out, _ = build_extras(_doc(), "-both", run_vrad=False)
    assert "env_tonemap_controller" not in {e.classname for e in out.entities()}


def test_own_entities_win():
    doc = _doc("shadow_control", "env_tonemap_controller")
    out, notes = build_extras(doc, "-both")
    assert out is doc and notes == []
