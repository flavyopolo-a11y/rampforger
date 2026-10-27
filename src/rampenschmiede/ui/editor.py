"""Editor-Kontext: verbindet Dokument, Undo-Stapel, Auswahl und Werkzeuge mit der Oberfläche."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterable

import numpy as np
from PySide6.QtCore import QObject, Signal

from ..core.commands import AddObjects, Command, CommandStack, RemoveObjects, ReplaceObjects
from ..core.geometry import transform
from ..core.geometry.transform import TransformError
from ..core.mathutil import BBox, Point
from ..core.model import ChangeSet, Entity, MapDocument, MapObject, Solid
from ..render.scene_mesh import SceneMesh

if TYPE_CHECKING:
    from .tools.base import Tool

GRID_SIZES = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512)
LEAK_COLOR = (1.0, 0.1, 0.1)


class EditorContext(QObject):
    document_replaced = Signal()
    document_changed = Signal()
    selection_changed = Signal()
    grid_changed = Signal(int)
    tool_changed = Signal(str)
    history_changed = Signal()
    status_message = Signal(str)
    redraw_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.doc = MapDocument()
        self.stack = CommandStack(self.doc)
        self.scene = SceneMesh(self.doc)
        self.selection: frozenset[int] = frozenset()
        self.file_path: Path | None = None
        #: Woher eine importierte Map stammt (VMF), solange sie nicht als Projekt gespeichert ist
        self.import_path: Path | None = None
        self.tools: dict[str, "Tool"] = {}
        self.tool: "Tool | None" = None
        self.texture_lock = True
        #: Leck-Spur aus der letzten .lin-Datei, als Linienpaare für die Ansichten
        self.leak_lines: np.ndarray | None = None
        self.leak_points: list[Point] = []
        self._hook_document()

    # ---- Dokument --------------------------------------------------------------
    def _hook_document(self) -> None:
        self.doc.subscribe(self._on_doc_change)
        self.stack.subscribe(self.history_changed.emit)

    def set_document(self, doc: MapDocument, path: Path | None, import_path: Path | None = None) -> None:
        self.doc.unsubscribe(self._on_doc_change)
        self.scene.detach()
        self.doc = doc
        self.stack = CommandStack(doc)
        self.scene = SceneMesh(doc)
        self.file_path = path
        self.import_path = import_path
        self.selection = frozenset()
        self.leak_points, self.leak_lines = [], None
        self._hook_document()
        self.document_replaced.emit()
        self.selection_changed.emit()
        self.history_changed.emit()
        self.grid_changed.emit(self.doc.editor.grid_size)
        self.redraw_requested.emit()

    def _on_doc_change(self, cs: ChangeSet) -> None:
        if cs.removed & self.selection:
            self.set_selection(self.selection - cs.removed)
        self.document_changed.emit()
        self.redraw_requested.emit()

    def run(self, cmd: Command) -> bool:
        """Führt ein Command aus. Fehler werden als Statusmeldung gezeigt statt abzustürzen."""
        try:
            self.stack.push(cmd)
        except TransformError as exc:
            self.status_message.emit(str(exc))
            return False
        return True

    def undo(self) -> None:
        self.stack.undo()

    def redo(self) -> None:
        self.stack.redo()

    # ---- Grid ------------------------------------------------------------------
    @property
    def grid(self) -> int:
        return self.doc.editor.grid_size

    def set_grid(self, size: int) -> None:
        size = min(GRID_SIZES, key=lambda g: abs(g - size))
        if size != self.doc.editor.grid_size:
            self.doc.editor.grid_size = size
            self.grid_changed.emit(size)
            self.redraw_requested.emit()

    def grid_finer(self) -> None:
        i = GRID_SIZES.index(self.grid)
        self.set_grid(GRID_SIZES[max(0, i - 1)])

    def grid_coarser(self) -> None:
        i = GRID_SIZES.index(self.grid)
        self.set_grid(GRID_SIZES[min(len(GRID_SIZES) - 1, i + 1)])

    def snap(self, value: float) -> int:
        g = self.grid
        return int(round(value / g) * g)

    # ---- Auswahl ----------------------------------------------------------------
    def set_selection(self, ids: Iterable[int]) -> None:
        sel = frozenset(i for i in ids if i in self.doc)
        if sel != self.selection:
            self.selection = sel
            self.scene.set_selection(sel)
            self.selection_changed.emit()
            self.redraw_requested.emit()

    def selected_objects(self) -> list[MapObject]:
        return [o for i in sorted(self.selection) if (o := self.doc.get(i)) is not None]

    def selection_bbox(self) -> BBox | None:
        return self.doc.bbox(self.selection) if self.selection else None

    def selectable(self, obj: MapObject) -> bool:
        return not (obj.editor.hidden or obj.editor.locked)

    def select_all(self) -> None:
        self.set_selection(o.id for o in self.doc.objects() if self.selectable(o) and not _is_entity_child(o))

    # ---- Bearbeiten der Auswahl ---------------------------------------------------
    def transform_selection(self, fn, description: str, merge_key: object | None = None) -> bool:
        objs = self.selected_objects()
        targets: list[MapObject] = []
        for o in objs:
            targets.append(o)
            if isinstance(o, Entity):
                targets += self.doc.children(o.id)
        if not targets:
            return False
        try:
            new = [fn(o) for o in targets]
        except TransformError as exc:
            self.status_message.emit(str(exc))
            return False
        return self.run(ReplaceObjects(new, description, merge_key=merge_key))

    def move_selection(self, delta: Point, merge_key: object | None = None) -> bool:
        return self.transform_selection(
            lambda o: transform.translate(o, delta, self.texture_lock), "Verschieben", merge_key)

    def rotate_selection(self, pivot: Point, axis: int, degrees: float, merge_key: object | None = None) -> bool:
        return self.transform_selection(
            lambda o: transform.rotate(o, pivot, axis, degrees, self.texture_lock), "Drehen", merge_key)

    def scale_selection(self, pivot: Point, factors: Point, merge_key: object | None = None) -> bool:
        return self.transform_selection(
            lambda o: transform.scale_obj(o, pivot, factors, self.texture_lock), "Skalieren", merge_key)

    def mirror_selection(self, axis: int) -> bool:
        bbox = self.selection_bbox()
        if bbox is None:
            return False
        pivot = tuple(round(c) for c in bbox.center)
        return self.transform_selection(lambda o: transform.mirror(o, pivot, axis), "Spiegeln")  # type: ignore[arg-type]

    def delete_selection(self) -> None:
        if self.selection:
            self.run(RemoveObjects(sorted(self.selection), "Löschen"))

    def duplicate(self, objs: list[MapObject], offset: Point) -> list[MapObject]:
        """Kopiert Objekte mit neuen IDs (Brush-Entities samt Brushes) und verschiebt sie."""
        new_objs: list[MapObject] = []
        roots: list[int] = []
        for o in objs:
            if isinstance(o, Entity):
                ne = o.replace(id=self.doc.new_id(), vmf_id=None)
                ne = transform.translate(ne, offset)
                new_objs.append(ne)
                roots.append(ne.id)
                for child in self.doc.children(o.id):
                    nc = child.replace(id=self.doc.new_id(), parent_id=ne.id, vmf_id=None)
                    new_objs.append(transform.translate(nc, offset, self.texture_lock))
            elif isinstance(o, Solid):
                ns = o.replace(id=self.doc.new_id(), vmf_id=None)
                ns = transform.translate(ns, offset, self.texture_lock)
                new_objs.append(ns)
                roots.append(ns.id)
        if new_objs:
            self.run(AddObjects(new_objs, "Duplizieren"))
            self.set_selection(roots)
        return new_objs

    def set_hidden(self, ids: Iterable[int], hidden: bool) -> None:
        from dataclasses import replace

        objs = [o for i in ids if (o := self.doc.get(i)) is not None and o.editor.hidden != hidden]
        if objs:
            self.run(ReplaceObjects([o.replace(editor=replace(o.editor, hidden=hidden)) for o in objs],
                                    "Ausblenden" if hidden else "Einblenden"))
            if hidden:
                self.set_selection(self.selection - {o.id for o in objs})

    # ---- Leck-Spur -------------------------------------------------------------------
    def set_leak_path(self, points: list[Point]) -> None:
        self.leak_points = list(points)
        if len(points) < 2:
            self.leak_lines = None
        else:
            pts = np.asarray(points, dtype=np.float32)
            pairs = np.repeat(pts, 2, axis=0)[1:-1]
            color = np.tile(np.asarray(LEAK_COLOR, dtype=np.float32), (len(pairs), 1))
            self.leak_lines = np.hstack([pairs, color])
        self.redraw_requested.emit()

    # ---- Werkzeuge ------------------------------------------------------------------
    def register_tool(self, tool: "Tool") -> None:
        self.tools[tool.name] = tool

    def set_tool(self, name: str) -> None:
        tool = self.tools[name]
        if tool is self.tool:
            return
        if self.tool is not None:
            self.tool.deactivate()
        self.tool = tool
        tool.activate()
        self.tool_changed.emit(name)
        self.redraw_requested.emit()


def _is_entity_child(obj: MapObject) -> bool:
    return isinstance(obj, Solid) and obj.parent_id is not None
