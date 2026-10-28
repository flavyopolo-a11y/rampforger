"""Natur in der Bibliothek: Wasser, Lava, Kill-Zone und einzelne Bäume."""
from rampenschmiede.core.model import Entity, Solid
from rampenschmiede.core.surf.nature_templates import DEFAULT_WATER
from rampenschmiede.ui.panels.library_panel import NATURE_PREFIX


def _keys(lib):
    out = []
    for i in range(lib.tree.topLevelItemCount()):
        g = lib.tree.topLevelItem(i)
        out += [g.child(k).data(0, 0x0100) for k in range(g.childCount())]
    return out


def test_nature_group_lists_water_lava_kill_and_props(window):
    keys = _keys(window.library)
    for k in ("wasser", "lava", "killzone", NATURE_PREFIX + "baum", NATURE_PREFIX + "fels"):
        assert k in keys


def test_insert_water_and_lava(window):
    ed = window.editor
    lib = window.library
    oid = lib.insert("wasser", (0.0, 0.0, 0.0))
    water = ed.doc.get(oid)
    assert isinstance(water, Solid) and any(f.material == DEFAULT_WATER for f in water.faces)
    assert ed.selection == {oid}
    oid = lib.insert("lava", (2048.0, 0.0, 0.0))
    lava = ed.doc.get(oid)
    mats = {f.material for f in lava.faces}
    assert len(mats) == 1 and mats.pop().startswith("RAMPENSCHMIEDE/LAVA")
    # Lava kommt mit ihrem Trigger als Gruppe: ein Klick wählt beides
    assert any(isinstance(ed.doc.get(i), Entity) and ed.doc.get(i).classname == "trigger_hurt" for i in ed.selection)


def test_tree_needs_models_and_places_a_random_tree(window, monkeypatch):
    ed = window.editor
    lib = window.library
    assert lib.insert(NATURE_PREFIX + "baum", (0.0, 0.0, 0.0)) is None  # ohne Spiel keine Modelle

    class _Models:
        def names(self):
            return ["models/props_foliage/tree_pine04.mdl", "models/props_c17/bench01a.mdl"]

        def load(self, _name):
            return None

    monkeypatch.setattr(ed, "models", _Models())
    oid = lib.insert(NATURE_PREFIX + "baum", (128.0, 64.0, 0.0))
    ent = ed.doc.get(oid)
    assert ent.get("model") == "models/props_foliage/tree_pine04.mdl" and ent.classname.startswith("prop_")
