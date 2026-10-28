"""Commands und der unbegrenzte Undo/Redo-Stapel.

Jede Änderung am Dokument ist ein Command. `do` und `undo` liefern ein ChangeSet, das der
Stapel an die Beobachter des Dokuments weitergibt.
"""
from __future__ import annotations

import random
from typing import Callable, Iterable, Sequence

from ...i18n import tr
from ..model import ChangeSet, EditorInfo, MapDocument, MapObject, Solid


class Command:
    description: str = tr("Änderung")
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
    def __init__(self, objs: Sequence[MapObject], description: str = tr("Hinzufügen")) -> None:
        self.objs = list(objs)
        self.description = description

    def do(self, doc: MapDocument) -> ChangeSet:
        return doc._insert(self.objs)

    def undo(self, doc: MapDocument) -> ChangeSet:
        return doc._remove([o.id for o in self.objs])[1]


class RemoveObjects(Command):
    """Entfernt Objekte. Bei Brush-Entities und Bausteinen werden ihre Brushes mit entfernt."""

    def __init__(self, ids: Iterable[int], description: str = tr("Löschen")) -> None:
        self.ids = list(dict.fromkeys(ids))
        self.description = description
        self.removed: list[MapObject] = []

    def do(self, doc: MapDocument) -> ChangeSet:
        ids = list(self.ids)
        known = set(ids)
        ids += [s.id for s in doc.attached(self.ids) if s.id not in known]
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


class SwapObjects(Command):
    """Entfernt Objekte und fügt andere ein, als ein Undo-Schritt. Objekte, die mit derselben
    ID wieder eingefügt werden, gelten als geändert (z. B. ein neu erzeugter Baustein)."""

    def __init__(self, remove_ids: Iterable[int], add: Sequence[MapObject], description: str = tr("Ändern"),
                 merge_key: object | None = None) -> None:
        self.remove_ids = list(dict.fromkeys(remove_ids))
        self.added = list(add)
        self.removed: list[MapObject] = []
        self.description = description
        self.merge_key = merge_key

    @staticmethod
    def _changes(gone: Sequence[MapObject], new: Sequence[MapObject]) -> ChangeSet:
        g, n = {o.id for o in gone}, {o.id for o in new}
        return ChangeSet(added=n - g, removed=g - n, modified=g & n)

    def do(self, doc: MapDocument) -> ChangeSet:
        self.removed, _ = doc._remove(self.remove_ids)
        try:
            doc._insert(self.added)
        except Exception:
            doc._insert(self.removed)
            raise
        return self._changes(self.removed, self.added)

    def undo(self, doc: MapDocument) -> ChangeSet:
        doc._remove([o.id for o in self.added])
        doc._insert(self.removed)
        return self._changes(self.added, self.removed)

    def merge(self, newer: Command, doc: MapDocument) -> bool:
        if not isinstance(newer, SwapObjects) or newer.merge_key != self.merge_key:
            return False
        # Ursprüngliche Objekte behalten, Zwischenstände verwerfen, neuesten Stand übernehmen.
        mine = {o.id for o in self.added}
        gone = {o.id for o in newer.removed}
        self.removed += [o for o in newer.removed if o.id not in mine]
        self.added = [o for o in self.added if o.id not in gone] + newer.added
        self.remove_ids = [o.id for o in self.removed]
        return True


class SetWorldKeyvalues(Command):
    def __init__(self, kvs: tuple[tuple[str, str], ...], description: str = tr("Map-Eigenschaften")) -> None:
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


class Deferred(Command):
    """Schritte, die erst beim Ausführen gebaut werden, weil sie den Stand nach dem vorigen
    Schritt brauchen (z. B. Kopien einfügen, dann drehen). Ein Undo-Schritt; Redo nimmt die
    beim ersten Mal gebauten Commands."""

    def __init__(self, steps: Sequence[Callable[[MapDocument], Command]], description: str) -> None:
        self.steps = list(steps)
        self.description = description
        self.built: list[Command] | None = None

    def do(self, doc: MapDocument) -> ChangeSet:
        cs = ChangeSet()
        if self.built is None:
            built: list[Command] = []
            try:
                for step in self.steps:
                    c = step(doc)
                    cs.merge(c.do(doc))
                    built.append(c)
            except Exception:
                for c in reversed(built):
                    c.undo(doc)
                raise
            self.built = built
        else:
            for c in self.built:
                cs.merge(c.do(doc))
        return cs

    def undo(self, doc: MapDocument) -> ChangeSet:
        cs = ChangeSet()
        for c in reversed(self.built or []):
            cs.merge(c.undo(doc))
        return cs


class FollowUp(Command):
    """Ein Command samt Folgeänderungen, die automatisch danach passieren (z. B. die Hülle
    wächst mit). Ein Undo-Schritt; verschmilzt weiter wie das Haupt-Command."""

    def __init__(self, main: Command, extras: Sequence[Command] = ()) -> None:
        self.main = main
        self.extras = list(extras)
        self.description = main.description
        self.merge_key = main.merge_key

    def do(self, doc: MapDocument) -> ChangeSet:
        cs = self.main.do(doc)
        for c in self.extras:
            cs.merge(c.do(doc))
        return cs

    def undo(self, doc: MapDocument) -> ChangeSet:
        cs = ChangeSet()
        for c in reversed(self.extras):
            cs.merge(c.undo(doc))
        cs.merge(self.main.undo(doc))
        return cs

    def merge(self, newer: Command, doc: MapDocument) -> bool:
        return self.main.merge(newer, doc)


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

    def set_dirty(self) -> None:
        """Als ungespeichert markieren (z. B. nach dem Öffnen einer Sicherung)."""
        self._clean_index = None
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

    def attach(self, cmd: Command) -> ChangeSet:
        """Folgeänderung ausführen und an den letzten Undo-Schritt hängen."""
        if not self._undo:
            return self.push(cmd)
        cs = cmd.do(self.doc)
        top = self._undo[-1]
        if isinstance(top, FollowUp):
            top.extras.append(cmd)
        else:
            self._undo[-1] = FollowUp(top, [cmd])
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
