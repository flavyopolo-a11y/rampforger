"""Entity-Beschreibungen aus FGD-Daten: welche Keyvalues, Flags, Ein- und Ausgänge eine
Entity-Klasse hat, mit Anzeigenamen, Typ, Standardwert und Hilfetext.

Grundlage ist die FGD-Datenbank von srctools (deckt die Source-Spiele ab, darunter CS:S).
Eigene FGD-Dateien (z. B. von Momentum) lassen sich zusätzlich laden; sie ergänzen und
überschreiben die eingebauten Klassen.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

#: Keys, die Rampenschmiede selbst setzt oder die in CS:S keine Rolle spielen
HIDDEN_KEYS = {"origin", "linedivider_vscript", "linedivider_base", "vscripts", "thinkfunction",
               "vscript_init_code", "vscript_init_code2", "classname", "hammerid"}

#: Die Engine-Basisklasse aller Entities bringt Dutzende Keys anderer Spiele mit (gmod, vscript …).
#: Von ihr werden nur diese gezeigt; was eine Klasse selbst (oder eine echte Basis) erklärt, immer.
ENGINE_BASE = "_cbaseentity_"
BASE_KEYS = {"targetname", "parentname", "spawnflags"}
BASE_INPUTS = {"kill", "killhierarchy", "addoutput", "fireuser1", "fireuser2", "fireuser3", "fireuser4",
               "setparent", "clearparent", "use", "enabledraw", "disabledraw", "alpha", "color"}
BASE_OUTPUTS = {"onuser1", "onuser2", "onuser3", "onuser4", "onkilled"}

#: FGD-Typ -> Editor-Art
KIND_BY_TYPE = {
    "integer": "integer",
    "float": "float",
    "boolean": "boolean",
    "choices": "choices",
    "flags": "flags",
    "color255": "color",
    "color1": "color1",
    "target_source": "name",
    "target_destination": "target",
    "target_name_or_class": "target",
    "filterclass": "target",
    "npcclass": "string",
    "studio": "model",
    "sprite": "material",
    "material": "material",
    "decal": "material",
    "sound": "sound",
    "angle": "angle",
    "vector": "vector",
}


@dataclass(frozen=True)
class KeyDef:
    name: str
    label: str
    kind: str
    default: str = ""
    desc: str = ""
    #: Auswahl-Werte (Wert, Anzeigename)
    choices: tuple[tuple[str, str], ...] = ()
    #: Spawnflags (Bit, Anzeigename, standardmäßig an)
    flags: tuple[tuple[int, str, bool], ...] = ()


@dataclass(frozen=True)
class IODef:
    name: str
    type: str = "void"
    desc: str = ""


@dataclass
class EntityClass:
    name: str
    kind: str  # "point" oder "solid"
    desc: str = ""
    keys: list[KeyDef] = field(default_factory=list)
    inputs: list[IODef] = field(default_factory=list)
    outputs: list[IODef] = field(default_factory=list)

    def key(self, name: str) -> KeyDef | None:
        low = name.lower()
        return next((k for k in self.keys if k.name.lower() == low), None)

    def defaults(self) -> tuple[tuple[str, str], ...]:
        """Keyvalues mit Standardwert für eine neue Entity (ohne leere)."""
        out = []
        for k in self.keys:
            if k.kind == "flags":
                bits = sum(bit for bit, _, on in k.flags if on)
                if bits:
                    out.append((k.name, str(bits)))
            elif k.default not in ("", None):
                out.append((k.name, k.default))
        return tuple(out)


def _kind(type_name: str) -> str:
    return KIND_BY_TYPE.get(type_name, "string")


def _desc(text: str) -> str:
    return " ".join((text or "").replace("\\n", " ").split())


def _convert(ent) -> EntityClass:
    from srctools.fgd import EntityTypes

    kind = "solid" if ent.type is EntityTypes.BRUSH else "point"
    keys: list[KeyDef] = []
    own_kv: set[str] = set()
    own_in: set[str] = set()
    own_out: set[str] = set()
    for base in (ent, *ent.iter_bases()):
        if base.classname.lower() != ENGINE_BASE:
            own_kv |= {n.lower() for n in base.keyvalues}
            own_in |= {n.lower() for n in base.inputs}
            own_out |= {n.lower() for n in base.outputs}
    # Die Ansichten kv/inp/out enthalten auch die Basisklassen (Name, Ausgänge wie OnUser1 …)
    for name in ent.kv:
        low = name.lower()
        if low in HIDDEN_KEYS or low.startswith(("gmod_", "vscript")) or (low not in own_kv and low not in BASE_KEYS):
            continue
        kv = ent.kv[name]
        type_name = kv.type.value
        kind_k = _kind(type_name)
        choices: tuple = ()
        flags: tuple = ()
        if kind_k == "flags":
            # Die Datenbank mischt Spiele: gleiche Bits mit anderem Namen, der erste gilt
            seen: dict[int, tuple[int, str, bool]] = {}
            for opt in kv.options or ():
                seen.setdefault(opt.bitflag, (opt.bitflag, opt.name, bool(opt.default)))
            flags = tuple(sorted(seen.values()))
        elif kind_k == "choices":
            choices = tuple((str(opt.value), opt.name) for opt in kv.options or ())
        label = kv.disp_name or kv.name
        keys.append(KeyDef(kv.name, label, kind_k, str(kv.default or ""), _desc(kv.desc), choices, flags))
    # Name zuerst, wie in Hammer
    keys.sort(key=lambda k: 0 if k.name.lower() == "targetname" else 1)
    ios = []
    for view, own, keep in ((ent.inp, own_in, BASE_INPUTS), (ent.out, own_out, BASE_OUTPUTS)):
        out: list[IODef] = []
        for name in view:
            if name.lower() not in own and name.lower() not in keep:
                continue
            io = view[name]
            out.append(IODef(io.name, io.type.value, _desc(io.desc)))
        # Eigene Ein- und Ausgänge der Klasse zuerst, die allgemeinen (OnUser1, Kill …) danach
        out.sort(key=lambda d: (d.name.lower() not in own, d.name.lower()))
        ios.append(out)
    return EntityClass(ent.classname, kind, _desc(ent.desc), keys, ios[0], ios[1])


class EntityCatalog:
    def __init__(self) -> None:
        self._raw: dict[str, object] = {}
        self._classes: dict[str, EntityClass] = {}
        self._names: dict[str | None, list[str]] = {}

    def add_fgd(self, fgd) -> None:
        from srctools.fgd import EntityTypes

        for name, ent in fgd.entities.items():
            if ent.type in (EntityTypes.BASE, EntityTypes.EXTEND):
                continue
            self._raw[name.lower()] = ent
            self._classes.pop(name.lower(), None)
        self._names.clear()

    def get(self, classname: str) -> EntityClass | None:
        low = classname.lower()
        hit = self._classes.get(low)
        if hit is None:
            raw = self._raw.get(low)
            if raw is None:
                return None
            hit = self._classes[low] = _convert(raw)
        return hit

    def classnames(self, kind: str | None = None) -> list[str]:
        from srctools.fgd import EntityTypes

        hit = self._names.get(kind)
        if hit is None:
            hit = sorted((ent.classname for ent in self._raw.values()
                          if kind is None or (kind == "solid") == (ent.type is EntityTypes.BRUSH)), key=str.lower)
            self._names[kind] = hit
        return list(hit)

    def __contains__(self, classname: str) -> bool:
        return classname.lower() in self._raw


@lru_cache(maxsize=1)
def builtin_catalog() -> EntityCatalog:
    from srctools.fgd import FGD

    cat = EntityCatalog()
    cat.add_fgd(FGD.engine_dbase())
    return cat


def load_catalog(extra_fgds: list[str | os.PathLike[str]] = ()) -> EntityCatalog:
    """Eingebaute Datenbank plus eigene FGD-Dateien (spätere gewinnen)."""
    from srctools.fgd import FGD
    from srctools.filesys import RawFileSystem

    cat = EntityCatalog()
    cat._raw.update(builtin_catalog()._raw)
    cat._names.clear()
    for path in extra_fgds:
        p = Path(path)
        fgd = FGD()
        fgd.parse_file(RawFileSystem(str(p.parent)), RawFileSystem(str(p.parent))[p.name], eval_bases=True)
        cat.add_fgd(fgd)
    return cat


def flag_bits(value: str) -> int:
    try:
        return int(float(value or "0"))
    except ValueError:
        return 0
