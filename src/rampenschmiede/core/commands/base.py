"""Commands und der unbegrenzte Undo/Redo-Stapel.

Jede Änderung am Dokument ist ein Command. `do` und `undo` liefern ein ChangeSet, das der
Stapel an die Beobachter des Dokuments weitergibt.
"""
from __future__ import annotations

import random
from typing import Callable, Iterable, Sequence

from ..model import ChangeSet, EditorInfo, MapDocument, MapObject, Solid


class Command:
    description: str = "Änderung"
    #: Commands mit gleichem, nicht leerem merge_key verschmelzen zu einem Undo-Schritt
    #: (z. B. alle Mausbewegungen eines Ziehvorgangs).
    merge_key: object | None = None

    def do(self, doc: MapDocument) -> ChangeSet:
        raise NotImplementedError

    def undo(self, doc: MapDocument) -> ChangeSet:
        raise NotImplementedError

    def merge(self, newer: "Command", doc: MapDocument) -> bool:
        """Übernimmt ein bereits ausgeführtes jüngeres Command. True, wenn gelungen."""
        return False


class AddObjects(Command):
    def __init__(self, objs: Sequence[MapObject], description: str = "Hinzufügen") -> None:
        self.objs = list(objs)
        self.description = description

    def do(self, doc: MapDocument) -> ChangeSet:
        return doc._insert(self.objs)

    def undo(self, doc: MapDocument) -> ChangeSet:
        return doc._remove([o.id for o in self.objs])[1]


class RemoveObjects(Command):
    """Entfernt Objekte. Bei Brush-Entities werden ihre Brushes mit entfernt."""

    def __init__(self, ids: Iterable[int], description: str = "Löschen") -> None:
        self.ids = list(dict.fromkeys(ids))
        self.description = description
        self.removed: list[MapObject] = []

    def do(self, doc: MapDocument) -> ChangeSet:
        ids = list(self.ids)
        for oid in self.ids:
            ids += [s.id for s in doc.children(oid) if s.id not in ids]
        self.removed, cs = doc._remove(ids)
        return cs

    def undo(self, doc: MapDocument) -> ChangeSet:
        return doc._insert(self.removed)


class ReplaceObjects(Command):
    """Ersetzt Objekte durch neue Versionen mit derselben ID."""

    def __init__(self, new_objs: Sequence[MapObject], description: str = "Bearbeiten",
                 merge_key: object | None = None) -> None:
        self.new = list(new_objs)
        self.old: list[MapObject] = []
        self.description = description
        self.merge_key = merge_key

    def do(self, doc: MapDocument) -> ChangeSet:
        self.old, cs = doc._replace(self.new)
        return cs

    def undo(self, doc: MapDocument) -> ChangeSet:
        return doc._replace(self.old)[1]

    def merge(self, newer: Command, doc: MapDocument) -> bool:
        if not isinstance(newer, ReplaceObjects) or newer.merge_key != self.merge_key:
            return False
        # Ältesten Zustand je ID behalten, neuesten Zustand übernehmen.
        known = {o.id for o in self.old}
        self.old += [o for o in newer.old if o.id not in known]
        latest = {o.id: o for o in self.new}
        latest.update({o.id: o for o in newer.new})
        self.new = list(latest.values())
        return True


class SetWorldKeyvalues(Command):
    def __init__(self, kvs: tuple[tuple[str, str], ...], description: str = "Map-Eigenschaften") -> None:
        self.new = kvs
        self.old: tuple[tuple[str, str], ...] = ()
        self.description = description

    def do(self, doc: MapDocument) -> ChangeSet:
        self.old = doc.world_keyvalues
        return doc._set_world_keyvalues(self.new)

    def undo(self, doc: MapDocument) -> ChangeSet:
        return doc._set_world_keyvalues(self.old)


class MacroCommand(Command):
    """Mehrere Commands als ein Undo-Schritt."""

    def __init__(self, commands: Sequence[Command], description: str) -> None:
        self.commands = list(commands)
        self.description = description

    def do(self, doc: MapDocument) -> ChangeSet:
        cs = ChangeSet()
        done: list[Command] = []
        try:
            for c in self.commands:
                cs.merge(c.do(doc))
                done.append(c)
        except Exception:
            for c in reversed(done):
                c.undo(doc)
            raise
        return cs

    def undo(self, doc: MapDocument) -> ChangeSet:
        cs = ChangeSet()
        for c in reversed(self.commands):
            cs.merge(c.undo(doc))
        return cs


class CommandStack:
    """Unbegrenzter Undo/Redo-Stapel für ein Dokument."""

    def __init__(self, doc: MapDocument) -> None:
        self.doc = doc
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self._clean_index: int | None = 0
        self._allow_merge = True
        self._listeners: list[Callable[[], None]] = []

    # ---- Zustand ---------------------------------------------------------
    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo_text(self) -> str:
        return self._undo[-1].description if self._undo else ""

    def redo_text(self) -> str:
        return self._redo[-1].description if self._redo else ""

    def __len__(self) -> int:
        return len(self._undo)

    def is_clean(self) -> bool:
        return self._clean_index == len(self._undo)

    def set_clean(self) -> None:
        self._clean_index = len(self._undo)
        self._changed()

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _changed(self) -> None:
        for listener in list(self._listeners):
            listener()

    def end_merge(self) -> None:
        """Beendet einen Verschmelzungs-Zeitraum, z. B. nach dem Loslassen der Maus."""
        self._allow_merge = False

    # ---- Ausführen -------------------------------------------------------
    def push(self, cmd: Command) -> ChangeSet:
        cs = cmd.do(self.doc)
        top = self._undo[-1] if self._undo else None
        merged = (
            self._allow_merge
            and cmd.merge_key is not None
            and top is not None
            and top.merge_key == cmd.merge_key
            and self._clean_index != len(self._undo)
            and top.merge(cmd, self.doc)
        )
        if not merged:
            self._undo.append(cmd)
            if self._clean_index is not None and self._clean_index > len(self._undo) - 1:
                self._clean_index = None  # sauberer Zustand liegt im verworfenen Redo-Zweig
        self._allow_merge = True
        self._redo.clear()
        self.doc.notify(cs)
        self._changed()
        return cs

    def undo(self) -> ChangeSet | None:
        if not self._undo:
            return None
        cmd = self._undo.pop()
        cs = cmd.undo(self.doc)
        self._redo.append(cmd)
        self._allow_merge = False
        self.doc.notify(cs)
        self._changed()
        return cs

    def redo(self) -> ChangeSet | None:
        if not self._redo:
            return None
        cmd = self._redo.pop()
        cs = cmd.do(self.doc)
        self._undo.append(cmd)
        self._allow_merge = False
        self.doc.notify(cs)
        self._changed()
        return cs

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._clean_index = 0
        self._changed()


def solids_from_faces(doc: MapDocument, face_sets: Iterable[tuple], parent_id: int | None = None) -> list[Solid]:
    """Hilfsfunktion: macht aus Face-Tupeln (z. B. von primitives) neue Solids mit IDs."""
    rng = random.Random()
    result = []
    for faces in face_sets:
        # Hammer gibt jedem neuen Brush eine zufällige Farbe für die 2D-Ansichten.
        color = (rng.randint(80, 255), rng.randint(80, 255), rng.randint(80, 255))
        result.append(Solid(id=doc.new_id(), faces=tuple(faces), parent_id=parent_id, editor=EditorInfo(color=color)))
    return result
