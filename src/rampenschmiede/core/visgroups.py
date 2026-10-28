"""Sichtgruppen (Visgroups wie in Hammer): benannte Sammlungen von Objekten, die man mit
einem Klick aus- und einblendet. Ein Objekt kann in mehreren Gruppen sein; es ist versteckt,
sobald eine seiner Gruppen versteckt ist.

Die Gruppen stehen in `doc.extra["sichtgruppen"]` (mit Undo), die Zugehörigkeit in
`EditorInfo.visgroup_ids` und damit im VMF als `visgroupid`. Aus einem importierten VMF
werden die Gruppen beim ersten Lesen aus dem rohen `visgroups`-Block übernommen."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Iterable

from ..i18n import tr
from .commands import Command, MacroCommand, ReplaceObjects
from .model import ChangeSet, MapDocument, MapObject

KEY = "sichtgruppen"
#: Farben neuer Gruppen der Reihe nach (wie Hammer zufällig, aber gut unterscheidbar)
COLORS = ((230, 120, 60), (90, 170, 230), (120, 210, 110), (220, 200, 80), (200, 110, 210), (100, 210, 200))


@dataclass(frozen=True)
class Visgroup:
    id: int
    name: str
    color: tuple[int, int, int] = (200, 200, 200)
    shown: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "color": list(self.color), "shown": self.shown}

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "Visgroup":
        c = d.get("color") or (200, 200, 200)
        return Visgroup(int(d["id"]), str(d.get("name", "")), (int(c[0]), int(c[1]), int(c[2])),
                        bool(d.get("shown", True)))


def _parse_raw(nodes: list, out: list[Visgroup]) -> None:
    for name, value in nodes:
        if name != "visgroup" or not isinstance(value, list):
            continue
        kv = {k: v for k, v in value if isinstance(v, str)}
        try:
            gid = int(kv.get("visgroupid", ""))
        except ValueError:
            continue
        try:
            color = tuple(int(float(c)) for c in kv.get("color", "").split())
        except ValueError:
            color = ()
        out.append(Visgroup(gid, kv.get("name", f"Gruppe {gid}"),
                            color if len(color) == 3 else (200, 200, 200)))  # type: ignore[arg-type]
        _parse_raw(value, out)  # verschachtelte Gruppen flach übernehmen


def visgroups(doc: MapDocument) -> list[Visgroup]:
    raw = doc.extra.get(KEY)
    if isinstance(raw, list):
        return [Visgroup.from_dict(d) for d in raw]
    out: list[Visgroup] = []
    for node in doc.extra.get("vmf_layout", ()):
        if isinstance(node, list) and node and node[0] == "visgroups" and isinstance(node[1], list):
            _parse_raw(node[1], out)
    return out


def raw_node(groups: Iterable[Visgroup]) -> list:
    """`visgroups`-Block fürs VMF."""
    return ["visgroups", [["visgroup", [["name", g.name], ["visgroupid", str(g.id)],
                                        ["color", " ".join(str(c) for c in g.color)]]] for g in groups]]


class SetVisgroups(Command):
    def __init__(self, groups: list[Visgroup], description: str) -> None:
        self.new = [g.to_dict() for g in groups]
        self.old: object = None
        self.description = description

    def do(self, doc: MapDocument) -> ChangeSet:
        self.old = doc.extra.get(KEY)
        doc.extra[KEY] = [dict(d) for d in self.new]
        return ChangeSet(world_changed=True)

    def undo(self, doc: MapDocument) -> ChangeSet:
        if self.old is None:
            doc.extra.pop(KEY, None)
        else:
            doc.extra[KEY] = self.old
        return ChangeSet(world_changed=True)


def _with_ids(doc: MapDocument, ids: Iterable[int]) -> list[MapObject]:
    """Objekte samt den Brushes ihrer Brush-Entities bzw. Bausteine."""
    ids = set(ids)
    objs = [o for i in ids if (o := doc.get(i)) is not None]
    objs += [s for s in doc.attached(ids) if s.id not in ids]
    return objs


def members(doc: MapDocument, gid: int) -> list[int]:
    return [o.id for o in doc.objects() if gid in o.editor.visgroup_ids]


def _hidden_ids(groups: list[Visgroup]) -> set[int]:
    return {g.id for g in groups if not g.shown}


def create(doc: MapDocument, name: str, ids: Iterable[int]) -> tuple[Command, int]:
    groups = visgroups(doc)
    gid = max((g.id for g in groups), default=0) + 1
    color = COLORS[(gid - 1) % len(COLORS)]
    groups = [*groups, Visgroup(gid, name.strip() or tr('Gruppe {0}').format(gid), color)]
    changed = [o.replace(editor=dataclasses.replace(o.editor, visgroup_ids=(*o.editor.visgroup_ids, gid)))
               for o in _with_ids(doc, ids)]
    cmds: list[Command] = [SetVisgroups(groups, "Sichtgruppe anlegen")]
    if changed:
        cmds.append(ReplaceObjects(changed))
    return MacroCommand(cmds, "Sichtgruppe anlegen"), gid


def add(doc: MapDocument, gid: int, ids: Iterable[int]) -> Command | None:
    group = next((g for g in visgroups(doc) if g.id == gid), None)
    changed = []
    for o in _with_ids(doc, ids):
        if gid not in o.editor.visgroup_ids:
            e = dataclasses.replace(o.editor, visgroup_ids=(*o.editor.visgroup_ids, gid))
            if group is not None and not group.shown:
                e = dataclasses.replace(e, hidden=True)
            changed.append(o.replace(editor=e))
    return ReplaceObjects(changed, tr("Zur Sichtgruppe hinzufügen")) if changed else None


def remove_from(doc: MapDocument, gid: int, ids: Iterable[int]) -> Command | None:
    hidden = _hidden_ids(visgroups(doc)) - {gid}
    changed = []
    for o in _with_ids(doc, ids):
        if gid in o.editor.visgroup_ids:
            rest = tuple(v for v in o.editor.visgroup_ids if v != gid)
            changed.append(o.replace(editor=dataclasses.replace(
                o.editor, visgroup_ids=rest, hidden=bool(hidden & set(rest)))))
    return ReplaceObjects(changed, tr("Aus Sichtgruppe nehmen")) if changed else None


def set_shown(doc: MapDocument, gid: int, shown: bool) -> Command | None:
    groups = visgroups(doc)
    if not any(g.id == gid for g in groups):
        return None
    groups = [dataclasses.replace(g, shown=shown) if g.id == gid else g for g in groups]
    hidden = _hidden_ids(groups)
    changed = []
    for o in doc.objects():
        if gid in o.editor.visgroup_ids:
            want = bool(hidden & set(o.editor.visgroup_ids))
            if o.editor.hidden != want:
                changed.append(o.replace(editor=dataclasses.replace(o.editor, hidden=want)))
    text = "Sichtgruppe einblenden" if shown else "Sichtgruppe ausblenden"
    cmds: list[Command] = [SetVisgroups(groups, text)]
    if changed:
        cmds.append(ReplaceObjects(changed))
    return MacroCommand(cmds, text)


def rename(doc: MapDocument, gid: int, name: str) -> Command | None:
    groups = visgroups(doc)
    if not name.strip() or not any(g.id == gid for g in groups):
        return None
    return SetVisgroups([dataclasses.replace(g, name=name.strip()) if g.id == gid else g for g in groups],
                        "Sichtgruppe umbenennen")


def delete(doc: MapDocument, gid: int) -> Command | None:
    """Gruppe auflösen; ihre Objekte bleiben (und werden sichtbar, wenn nur sie sie versteckt hat)."""
    groups = visgroups(doc)
    if not any(g.id == gid for g in groups):
        return None
    rest = [g for g in groups if g.id != gid]
    cmds: list[Command] = [SetVisgroups(rest, tr("Sichtgruppe löschen"))]
    change = remove_from(doc, gid, members(doc, gid))
    if change is not None:
        cmds.append(change)
    return MacroCommand(cmds, tr("Sichtgruppe löschen"))


__all__ = ["KEY", "Visgroup", "add", "create", "delete", "members", "raw_node", "remove_from", "rename",
           "set_shown", "visgroups"]
