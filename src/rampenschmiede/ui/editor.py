"""Editor-Kontext: verbindet Dokument, Undo-Stapel, Auswahl und Werkzeuge mit der Oberfläche."""
from __future__ import annotations

import itertools
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Iterable

import numpy as np
from PySide6.QtCore import QObject, Signal

from ..core import cordon as cordon_mod
from ..core.attach import follow_supports
from ..core.blocks import clone_objects, transform_command
from ..core.commands import AddObjects, Command, CommandStack, RemoveObjects, ReplaceObjects
from ..core.decals import DECAL, OVERLAY, sticker_bbox
from ..core.entities.fgd import EntityCatalog, builtin_catalog, load_catalog
from ..core.entities.io import io_segments
from ..core.geometry import transform
from ..core.geometry.transform import TransformError
from ..core.instances import INSTANCE, InstanceCache, instance_bbox, placed_objects
from ..core.instances import resolve as resolve_instance
from ..core.lights import LightSet, collect_lights, gizmo_segments
from ..core.materials import MaterialLibrary
from ..core.materials.sizes import set_size_lookup
from ..core.mathutil import BBox, Point
from ..core.model import (
    DEFAULT_MATERIAL,
    ChangeSet,
    Entity,
    MapDocument,
    MapObject,
    owner_id,
    set_entity_bounds,
)
from ..core.models.library import ModelLibrary
from ..core.models.props import prop_bbox
from ..core.organize import expand_groups
from ..core.pillars import follow_pillars
from ..core.sounds import SoundLibrary
from ..core.templates.starter import grow_hull
from ..core.tracks import PATH_COLOR, path_segments
from ..render.scene_mesh import SceneMesh
from ..render.sky import SkyCache, SkyImages
from ..render.textures import TextureAtlas

if TYPE_CHECKING:
    from .tools.base import Tool

GRID_SIZES = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512)


def _size_lookup(library: MaterialLibrary | None):
    """Texturgrößen für Rampen mit eingepasster Textur aus der Material-Bibliothek."""
    if library is None:
        return None

    def lookup(material: str) -> tuple[int, int] | None:
        tex = library.texture(material)
        return (tex.source_width, tex.source_height) if tex else None
    return lookup
LEAK_COLOR = (1.0, 0.1, 0.1)
CORDON_COLOR = (1.0, 0.3, 0.3)
CORDON_OFF_COLOR = (0.5, 0.5, 0.55)


def _use_model_bounds(editor: "EditorContext") -> None:
    """Auswahl, Picking und Gizmos sehen Props so groß wie ihr Modell, Aufkleber so groß
    wie ihr Bild."""
    ref = weakref.ref(editor)

    def bounds(ent):
        if ent.classname.lower() in (DECAL, OVERLAY):
            bb = sticker_bbox(ent)
            if bb is not None:
                return bb
        ed = ref()
        if ed is not None and ent.classname.lower() == INSTANCE:
            return instance_bbox(ent, ed.instance_content(ent))
        return prop_bbox(ent, ed.models) if ed is not None else None
    set_entity_bounds(bounds)


#: Linienfarbe der Portale (hellblau, wie in Hammer)
PORTAL_COLOR = (0.45, 0.75, 1.0)
#: Linienfarbe der Pfade (path_track/path_corner)
PATH_LINE = tuple(c / 255 for c in PATH_COLOR)


class EditorContext(QObject):
    document_replaced = Signal()
    document_changed = Signal()
    selection_changed = Signal()
    grid_changed = Signal(int)
    tool_changed = Signal(str)
    history_changed = Signal()
    status_message = Signal(str)
    redraw_requested = Signal()
    #: Bereich (Cordon) gesetzt, verändert, an- oder ausgeschaltet
    cordon_changed = Signal()
    #: Eine Vorlage aus der Bibliothek wurde in eine Ansicht gezogen: (Schlüssel, Weltpunkt)
    template_dropped = Signal(str, object)
    #: Map-Dateien (rsmap, vmf, bsp) wurden ins Fenster gezogen
    files_dropped = Signal(list)
    #: Neue Material-Bibliothek (anderes Spielprofil, neue eigene Texturen)
    materials_changed = Signal()
    #: Aktuelles Material für neue Brushes und „Material anwenden“
    current_material_changed = Signal(str)
    #: Gilt eine Rampen-Textur für alle Rampen oder nur eine ("alle"/"einer")?
    material_scope_changed = Signal(str)
    #: Ein Modell aus dem Modell-Browser wurde in eine Ansicht gezogen: (Modellname, Weltpunkt)
    model_dropped = Signal(str, object)
    #: Namen-Pipette (o. Ä.) wartet auf einen Klick in eine Ansicht: True beim Start, False am Ende
    picking_changed = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.doc = MapDocument()
        self.stack = CommandStack(self.doc)
        self.materials: MaterialLibrary | None = None
        #: Modelle des Spiels (gleiche Dateien wie die Materialien), None ohne Spielprofil
        self.models: ModelLibrary | None = None
        self.atlas = TextureAtlas()
        self.current_material = DEFAULT_MATERIAL
        #: Gilt eine Rampen-Textur für alle Rampen ("alle") oder nur eine ("einer")?
        self.material_scope = "alle"
        self.scene = SceneMesh(self.doc, self.atlas)
        self.scene.instances = self.instance_objects
        self.selection: frozenset[int] = frozenset()
        self.file_path: Path | None = None
        #: Woher eine importierte Map stammt (VMF), solange sie nicht als Projekt gespeichert ist
        self.import_path: Path | None = None
        self.tools: dict[str, "Tool"] = {}
        self.tool: "Tool | None" = None
        self.texture_lock = True
        #: „Gruppen ignorieren“ (Strg+W): Klick wählt dann nur das Objekt, nicht die ganze Gruppe
        self.ignore_groups = False
        #: Leck-Spur aus der letzten .lin-Datei, als Linienpaare für die Ansichten
        self.leak_lines: np.ndarray | None = None
        #: Portale aus der letzten .prt-Datei (Umrisse als Linienpaare)
        self.portal_lines: np.ndarray | None = None
        self.portal_count = 0
        self.leak_points: list[Point] = []
        self._entity_fgds: list[str] = []
        self._entity_catalog: EntityCatalog | None = None
        #: Wartet ein Panel auf das nächste angeklickte Objekt (Namen-Pipette)?
        self._picker: Callable[[MapObject], None] | None = None
        self._io_cache: tuple[int, np.ndarray | None] | None = None
        self._sounds: SoundLibrary | None = None
        self.instance_cache = InstanceCache()
        self._lights: LightSet | None = None
        self.sky_cache = SkyCache()
        #: Kamera der zuletzt gezeichneten 3D-Ansicht (setzt die Ansicht selbst)
        self.camera3d = None
        self._hook_document()
        _use_model_bounds(self)

    # ---- Dokument --------------------------------------------------------------
    def _hook_document(self) -> None:
        self.doc.subscribe(self._on_doc_change)
        self.stack.subscribe(self.history_changed.emit)

    def set_document(self, doc: MapDocument, path: Path | None, import_path: Path | None = None) -> None:
        self.doc.unsubscribe(self._on_doc_change)
        self.scene.detach()
        self.doc = doc
        self.stack = CommandStack(doc)
        self.scene = SceneMesh(doc, self.atlas, self.models)
        self.scene.instances = self.instance_objects
        self.file_path = path
        self.import_path = import_path
        self.selection = frozenset()
        self.leak_points, self.leak_lines = [], None
        self.portal_lines, self.portal_count = None, 0
        self._lights = None
        self._hook_document()
        self.document_replaced.emit()
        self.selection_changed.emit()
        self.history_changed.emit()
        self.grid_changed.emit(self.doc.editor.grid_size)
        self.redraw_requested.emit()

    def set_entity_fgds(self, paths: list[str]) -> None:
        """FGD-Dateien des Spielprofils; die Entity-Liste wird beim nächsten Zugriff neu gelesen."""
        if list(paths) != self._entity_fgds:
            self._entity_fgds = list(paths)
            self._entity_catalog = None

    @property
    def entity_catalog(self) -> EntityCatalog:
        if self._entity_catalog is None:
            existing = [p for p in self._entity_fgds if Path(p).is_file()]
            try:
                self._entity_catalog = load_catalog(existing)
            except Exception as exc:  # kaputte FGD: eingebaute Liste reicht zum Arbeiten
                self._entity_catalog = builtin_catalog()
                self.status_message.emit(f"FGD-Dateien nicht lesbar, nutze eingebaute Entity-Liste ({exc})")
        return self._entity_catalog

    def lights(self) -> LightSet:
        """Lichter der Map für die Licht-Vorschau (nach jeder Änderung neu gelesen)."""
        if self._lights is None:
            self._lights = collect_lights(self.doc)
        return self._lights

    def sky_images(self) -> SkyImages | None:
        """Bilder des eingestellten Himmels (skyname), None wenn das Spiel ihn nicht hat."""
        return self.sky_cache.get(self.materials, self.doc.world_get("skyname"))

    def set_material_library(self, library: MaterialLibrary | None) -> None:
        self.materials = library
        self.models = ModelLibrary(library) if library is not None else None
        _use_model_bounds(self)
        self.sky_cache.forget()
        self.atlas.set_library(library)
        self.scene.set_models(self.models)
        set_size_lookup(_size_lookup(library))
        self.materials_changed.emit()
        self.redraw_requested.emit()

    def refresh_materials(self) -> None:
        """Neu einlesen, z. B. nachdem eigene Texturen dazugekommen sind."""
        if self.materials is not None:
            self.materials.forget()
        self.set_material_library(self.materials)

    def set_material_scope(self, scope: str) -> None:
        if scope != self.material_scope:
            self.material_scope = scope
            self.material_scope_changed.emit(scope)

    def set_current_material(self, name: str) -> None:
        name = name.strip().upper()
        if name and name != self.current_material:
            self.current_material = name
            self.current_material_changed.emit(name)

    def _on_doc_change(self, cs: ChangeSet) -> None:
        self._lights = None
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
        # Zonen folgen ihrem Block, die Hülle des Startraums wächst mit, im selben Undo-Schritt
        # Erst die Stützen der Rampen, dann die Zonen auf ihren Blöcken
        for follow in (follow_pillars(self.doc), follow_supports(self.doc)):
            if follow is not None:
                self.stack.attach(follow)
        grow = grow_hull(self.doc)
        if grow is not None:
            self.stack.attach(grow)
            self.status_message.emit("Hülle vergrößert, damit alles hineinpasst")
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
        if not self.ignore_groups:
            ids = set(ids)
            ids |= {i for i in expand_groups(self.doc, ids) - ids if self.selectable(self.doc.get(i))}
        sel = frozenset(i for i in ids if i in self.doc)
        if sel != self.selection:
            self.selection = sel
            self.scene.set_selection(sel)
            self.selection_changed.emit()
            self.redraw_requested.emit()

    def io_lines(self) -> np.ndarray | None:
        """Verbindungslinien der gewählten Entities (Ausgänge grün, Eingänge orange) und
        immer die Pfade aus path_track/path_corner (hellgrün, gestrichelt wirkt zu unruhig)."""
        version = self.scene.version
        if self._io_cache is not None and self._io_cache[0] == version:
            return self._io_cache[1]
        segs = io_segments(self.doc, self.selection) if self.selection else []
        segs += [(a, b, PATH_LINE) for a, b in path_segments(self.doc)]
        lines = np.asarray([[*p, *c] for a, b, c in segs for p in (a, b)], dtype=np.float32) if segs else None
        self._io_cache = (version, lines)
        return lines

    def light_lines(self) -> np.ndarray | None:
        """Reichweite, Kegel und Sonnenrichtung der gewählten Lichter."""
        segs = gizmo_segments(self.doc, self.selection) if self.selection else []
        if not segs:
            return None
        return np.asarray([[*p, *c] for a, b, c in segs for p in (a, b)], dtype=np.float32)

    # ---- Bereich (Cordon) -----------------------------------------------------------
    def cordon(self) -> tuple[BBox | None, bool]:
        return cordon_mod.get_cordon(self.doc)

    def set_cordon(self, box: BBox | None, active: bool = True) -> None:
        """Bereich setzen (None löscht ihn). Kein Rückgängig-Schritt, aber die Map gilt als geändert."""
        old = self.doc.extra.get(cordon_mod.KEY)
        cordon_mod.set_cordon(self.doc, box, active)
        if self.doc.extra.get(cordon_mod.KEY) == old:
            return
        self.stack.set_dirty()
        self.cordon_changed.emit()
        self.history_changed.emit()
        self.redraw_requested.emit()

    def cordon_from_selection(self, pad: int = 64) -> bool:
        """Bereich um die Auswahl legen (mit `pad` Luft) und einschalten."""
        bb = self.selection_bbox()
        if bb is None:
            self.status_message.emit("Erst etwas auswählen oder mit dem Werkzeug „Bereich“ ziehen")
            return False
        self.set_cordon(BBox(tuple(v - pad for v in bb.mins), tuple(v + pad for v in bb.maxs)), True)  # type: ignore[arg-type]
        self.status_message.emit("Bereich um die Auswahl gelegt: beim Kompilieren wird nur er gebaut")
        return True

    def cordon_lines(self) -> np.ndarray | None:
        """Rahmen des Bereichs: rot, wenn nur er gebaut wird, sonst grau."""
        from .tools.base import box_lines

        box, on = self.cordon()
        if box is None:
            return None
        return box_lines(box, CORDON_COLOR if on else CORDON_OFF_COLOR)

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
        targets: list[MapObject] = objs + self.doc.attached(o.id for o in objs)
        if not targets:
            return False
        try:
            cmd = transform_command(self.doc, targets, fn, description, merge_key)
        except TransformError as exc:
            self.status_message.emit(str(exc))
            return False
        return self.run(cmd)

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
        """Kopiert Objekte mit neuen IDs (Brush-Entities und Bausteine samt Brushes) und verschiebt sie."""
        objs = list(objs)
        clones, roots = clone_objects(self.doc, objs + self.doc.attached(o.id for o in objs))
        new_objs = [transform.translate(o, offset, self.texture_lock) for o in clones]
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

    # ---- Instanzen --------------------------------------------------------------------
    def map_dir(self) -> Path | None:
        """Ordner der Map: Instanz-Dateien stehen relativ dazu."""
        path = self.file_path or self.import_path
        return path.parent if path is not None else None

    def instance_file(self, ent: Entity) -> Path | None:
        return resolve_instance(ent.get("file"), self.map_dir())

    def instance_content(self, ent: Entity) -> MapDocument | None:
        path = self.instance_file(ent)
        return self.instance_cache.get(path) if path is not None else None

    def instance_objects(self, ent: Entity) -> list[MapObject] | None:
        """Inhalt einer func_instance an ihrer Stelle (für Anzeige und Auswahl)."""
        content = self.instance_content(ent)
        if content is None:
            return None
        return placed_objects(ent, content, itertools.count(1).__next__, fixup=False)

    def reload_instances(self) -> bool:
        """Instanz-Dateien neu lesen, wenn sich eine geändert hat (z. B. in einem zweiten Fenster
        bearbeitet). True, wenn neu gezeichnet wird."""
        changed = self.instance_cache.stale()
        if changed:
            self.instance_cache.forget()
            self.scene.textures_changed()
            self.redraw_requested.emit()
        return changed

    # ---- Sounds -----------------------------------------------------------------------
    def sounds(self) -> SoundLibrary:
        """Sounds des Spiels; nach einem Wechsel der Material-Bibliothek neu gelesen."""
        if self._sounds is None or self._sounds.materials is not self.materials:
            self._sounds = SoundLibrary(self.materials)
        return self._sounds

    # ---- Portale (vbsp .prt) ----------------------------------------------------------
    def set_portals(self, polys: list[list[Point]]) -> None:
        """Portale als Umrisse in allen Ansichten zeigen; leere Liste blendet sie aus. Wo viele
        Portale dicht liegen, zerschneidet die Geometrie die Map stark (VIS wird langsam)."""
        self.portal_count = len(polys)
        if not polys:
            self.portal_lines = None
        else:
            rows = []
            for poly in polys:
                for i, a in enumerate(poly):
                    b = poly[(i + 1) % len(poly)]
                    rows += [[*a, *PORTAL_COLOR], [*b, *PORTAL_COLOR]]
            self.portal_lines = np.asarray(rows, dtype=np.float32)
        self.redraw_requested.emit()

    # ---- Objekt in einer Ansicht anklicken (Pipette) --------------------------------
    @property
    def picking(self) -> bool:
        return self._picker is not None

    def start_pick(self, callback: Callable[[MapObject], None], message: str) -> None:
        """Der nächste Linksklick in eine Ansicht wählt kein Objekt aus, sondern gibt es an
        `callback`. Esc oder ein zweiter Start bricht ab."""
        self._picker = callback
        self.status_message.emit(message)
        self.picking_changed.emit(True)

    def cancel_pick(self) -> None:
        if self._picker is not None:
            self._picker = None
            self.picking_changed.emit(False)

    def finish_pick(self, obj: MapObject) -> None:
        callback, self._picker = self._picker, None
        self.picking_changed.emit(False)
        if callback is not None:
            callback(obj)

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
    return owner_id(obj) is not None
