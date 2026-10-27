"""Assistent „Neue Surf-Map“: spielbar, dicht, innerhalb der Map-Grenzen."""
import pytest

from rampenschmiede.core.blocks import block_info
from rampenschmiede.core.model import MapDocument
from rampenschmiede.core.templates import RAMP_KINDS, SurfMapSettings, new_surf_map
from rampenschmiede.core.validation.seal import check_seal


def build(**kw):
    doc = MapDocument()
    doc._insert(new_surf_map(doc, SurfMapSettings(**kw)))
    return doc


@pytest.mark.parametrize("kind", RAMP_KINDS)
def test_map_is_sealed_and_inside_limits(kind):
    doc = build(game="momentum", ramp_kind=kind)
    assert check_seal(doc).sealed
    bb = doc.bbox()
    assert all(abs(c) <= 16384 for c in (*bb.mins, *bb.maxs))
    assert all(s.is_valid() for s in doc.solids())


def test_stages_ramps_and_teleports_match():
    doc = build(game="css", stages=4, ramps_per_stage=3, ramp_length=1024)
    ents = list(doc.entities())
    ramps = [e for e in ents if (block_info(e) or {}).get("template") == "gerade"]
    assert len(ramps) == 12
    triggers = [e for e in ents if e.classname == "trigger_teleport"]
    dests = {e.get("targetname") for e in ents if e.classname == "info_teleport_destination"}
    assert len(triggers) == 4 and {t.get("target") for t in triggers} == dests
    assert {e.classname for e in ents} >= {"info_player_counterterrorist", "info_player_terrorist", "light_environment"}
    # Spawns stehen auf der ersten Plattform, über dem tiefsten Punkt der Rampen
    spawn = next(e for e in ents if e.classname == "info_player_counterterrorist")
    assert spawn.origin[2] > max(r.origin[2] if r.origin else -1e9 for r in ramps)


def test_ramps_descend_along_the_course():
    doc = build(stages=1, ramps_per_stage=3)
    xs_z = sorted((block_info(e)["placement"][0], block_info(e)["placement"][2])
                  for e in doc.entities() if (block_info(e) or {}).get("template") == "gerade")
    zs = [z for _x, z in xs_z]
    assert zs == sorted(zs, reverse=True) and zs[0] > zs[-1]


def test_too_long_map_is_refused():
    with pytest.raises(ValueError, match="Source erlaubt"):
        build(stages=10, ramps_per_stage=4, ramp_length=4096)
