"""VMF-Import und -Export mit verlustfreiem Roundtrip.

Was Rampenschmiede versteht (Brushes, Seiten, Entities, I/O, Editor-Farben, Gruppen-
und Visgroup-Zuordnung, ausgeblendete Objekte), wird ins Datenmodell übernommen. Alles
andere (versioninfo, visgroups, viewsettings, cameras, cordons, dispinfo, Gruppen,
unbekannte Keys) bleibt als roher Baum am passenden Objekt hängen und wird an derselben
Stelle wieder geschrieben.

Roher Baum (JSON-fähig): ein Knoten ist [name, wert] mit wert = str oder Liste von Knoten.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from srctools.keyvalues import Keyvalues

from ..decals import is_auto_overlay, overlay_sides
from ..model import EditorInfo, Entity, Face, MapDocument, MapObject, Output, Solid, TexAxis

RawNode = list  # [name, str | list[RawNode]]

WORLD_MARK = "@world"
ENTITIES_MARK = "@entities"
IO_SEP_ESC = "\x1b"


class VmfError(ValueError):
    pass


# ---- Rohe Bäume ------------------------------------------------------------

def kv_to_raw(kv: Keyvalues) -> RawNode:
    if kv.has_children():
        return [kv.real_name, [kv_to_raw(c) for c in kv]]
    return [kv.real_name, kv.value]


def _write_raw(node: RawNode, out: list[str], depth: int) -> None:
    name, value = node
    ind = "\t" * depth
    if isinstance(value, list):
        out.append(f"{ind}{name}\n{ind}{{\n")
        for child in value:
            _write_raw(child, out, depth + 1)
        out.append(f"{ind}}}\n")
    else:
        out.append(f'{ind}"{name}" "{value}"\n')


# ---- Zahlen ---------------------------------------------------------------------

def fmt(v: float) -> str:
    if float(v).is_integer():
        return str(int(v))
    return format(v, ".10g")


_PLANE_RE = re.compile(r"\(\s*([^)]+?)\s*\)")
_AXIS_RE = re.compile(r"\[\s*([^\]]+?)\s*\]\s*([-+0-9.eE]+)")


def parse_plane(text: str) -> tuple[tuple[float, float, float], ...]:
    groups = _PLANE_RE.findall(text)
    if len(groups) != 3:
        raise VmfError(f"Ungültige Ebene: {text!r}")
    pts = []
    for g in groups:
        nums = [float(c) for c in g.split()]
        if len(nums) != 3:
            raise VmfError(f"Ungültiger Punkt in Ebene: {text!r}")
        pts.append((nums[0], nums[1], nums[2]))
    return tuple(pts)


def format_plane(points: Iterable[tuple[float, float, float]]) -> str:
    return " ".join("(" + " ".join(fmt(c) for c in p) + ")" for p in points)


def parse_axis(text: str) -> TexAxis:
    m = _AXIS_RE.match(text.strip())
    if not m:
        raise VmfError(f"Ungültige Texturachse: {text!r}")
    nums = [float(c) for c in m.group(1).split()]
    if len(nums) != 4:
        raise VmfError(f"Ungültige Texturachse: {text!r}")
    return TexAxis(nums[0], nums[1], nums[2], nums[3], float(m.group(2)))


def format_axis(a: TexAxis) -> str:
    return f"[{fmt(a.x)} {fmt(a.y)} {fmt(a.z)} {fmt(a.offset)}] {fmt(a.scale)}"


def _int_or_none(text: str) -> int | None:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


# ---- Import ---------------------------------------------------------------------

@dataclass
class ImportReport:
    solids: int = 0
    entities: int = 0
    warnings: list[str] = field(default_factory=list)


def _parse_editor(kv: Keyvalues, default: EditorInfo, hidden: bool) -> tuple[EditorInfo, list[RawNode]]:
    color = default.color
    group = None
    visgroups: list[int] = []
    raw: list[RawNode] = []
    for c in kv:
        key = c.name
        if c.has_children():
            raw.append(kv_to_raw(c))
        elif key == "color":
            try:
                r, g, b = (int(float(x)) for x in c.value.split()[:3])
                color = (r, g, b)
            except ValueError:
                raw.append(kv_to_raw(c))
        elif key == "groupid" and _int_or_none(c.value) is not None:
            group = int(c.value)
        elif key == "visgroupid" and _int_or_none(c.value) is not None:
            visgroups.append(int(c.value))
        else:
            raw.append(kv_to_raw(c))
    return EditorInfo(color=color, group_id=group, visgroup_ids=tuple(visgroups), hidden=hidden), raw


SIDE_KEYS = ("id", "plane", "material", "uaxis", "vaxis", "rotation", "lightmapscale", "smoothing_groups")


def _parse_side(kv: Keyvalues) -> Face:
    vals: dict[str, str] = {}
    raw: list[RawNode] = []
    for c in kv:
        if not c.has_children() and c.name in SIDE_KEYS and c.name not in vals:
            vals[c.name] = c.value
        else:
            raw.append(kv_to_raw(c))
    if "plane" not in vals:
        raise VmfError("Seite ohne Ebene")
    extra: dict[str, Any] = {"raw": raw} if raw else {}
    return Face(
        points=parse_plane(vals["plane"]),  # type: ignore[arg-type]
        material=vals.get("material", "TOOLS/TOOLSNODRAW"),
        uaxis=parse_axis(vals["uaxis"]) if "uaxis" in vals else TexAxis(1, 0, 0),
        vaxis=parse_axis(vals["vaxis"]) if "vaxis" in vals else TexAxis(0, -1, 0),
        rotation=float(vals.get("rotation", 0) or 0),
        lightmapscale=int(float(vals.get("lightmapscale", 16) or 16)),
        smoothing_groups=int(float(vals.get("smoothing_groups", 0) or 0)),
        vmf_id=_int_or_none(vals.get("id", "")),
        extra=extra,
    )


def _parse_solid(doc: MapDocument, kv: Keyvalues, parent: int | None, hidden: bool) -> Solid:
    faces: list[Face] = []
    vmf_id = None
    editor = EditorInfo(hidden=hidden)
    raw: list[RawNode] = []
    editor_raw: list[RawNode] = []
    for c in kv:
        if c.name == "side" and c.has_children():
            faces.append(_parse_side(c))
        elif c.name == "editor" and c.has_children():
            editor, editor_raw = _parse_editor(c, editor, hidden)
        elif c.name == "id" and not c.has_children():
            vmf_id = _int_or_none(c.value)
        else:
            raw.append(kv_to_raw(c))
    extra: dict[str, Any] = {}
    if raw:
        extra["raw"] = raw
    if editor_raw:
        extra["editor_raw"] = editor_raw
    return Solid(id=doc.new_id(), faces=tuple(faces), parent_id=parent, editor=editor, vmf_id=vmf_id, extra=extra)


def _parse_connections(kv: Keyvalues) -> tuple[list[Output], str]:
    """Liest Outputs. Zurück kommt auch je Output das Trennzeichen ("e" = ESC, "c" = Komma)."""
    outputs = []
    seps = ""
    for c in kv:
        value = c.value
        if IO_SEP_ESC in value:
            seps += "e"
            parts = value.split(IO_SEP_ESC)
        else:
            seps += "c"
            parts = value.split(",")
            if len(parts) > 5:  # Komma im Parameter
                parts = [parts[0], parts[1], ",".join(parts[2:-2]), parts[-2], parts[-1]]
        while len(parts) < 5:
            parts.append("")
        target, inp, param, delay, times = parts[:5]
        try:
            d = float(delay or 0)
        except ValueError:
            d = 0.0
        t = _int_or_none(times)
        outputs.append(Output(c.real_name, target, inp, param, d, -1 if t is None else t))
    return outputs, seps


def _parse_entity(doc: MapDocument, kv: Keyvalues, hidden: bool, objs: list[MapObject]) -> None:
    eid = doc.new_id()
    classname = ""
    keyvalues: list[tuple[str, str]] = []
    outputs: list[Output] = []
    vmf_id = None
    editor = EditorInfo(color=(220, 30, 220), hidden=hidden)
    extra: dict[str, Any] = {}
    raw: list[RawNode] = []
    solids: list[Solid] = []
    for c in kv:
        if c.has_children():
            if c.name == "solid":
                solids.append(_parse_solid(doc, c, eid, hidden))
            elif c.name == "connections":
                outs, seps = _parse_connections(c)
                outputs += outs
                if "e" in seps or any("," in o.parameter for o in outs):
                    extra["io_seps"] = extra.get("io_seps", "") + seps
            elif c.name == "editor":
                editor, editor_raw = _parse_editor(c, editor, hidden)
                if editor_raw:
                    extra["editor_raw"] = editor_raw
            elif c.name == "hidden":
                for h in c:
                    if h.name == "solid":
                        solids.append(_parse_solid(doc, h, eid, True))
                    else:
                        raw.append(kv_to_raw(h))
            else:
                raw.append(kv_to_raw(c))
        elif c.name == "id":
            vmf_id = _int_or_none(c.value)
        elif c.name == "classname" and not classname:
            classname = c.value
        else:
            keyvalues.append((c.real_name, c.value))
    if raw:
        extra["raw"] = raw
    ent = Entity(id=eid, classname=classname, keyvalues=tuple(keyvalues), outputs=tuple(outputs),
                 editor=editor, vmf_id=vmf_id, extra=extra)
    objs.append(ent)
    objs.extend(solids)


def parse_vmf(text: str, filename: str = "") -> tuple[MapDocument, ImportReport]:
    try:
        root = Keyvalues.parse(text, filename, allow_escapes=False)
    except Exception as exc:  # srctools wirft eigene Fehlerklassen
        raise VmfError(f"VMF konnte nicht gelesen werden: {exc}") from exc
    doc = MapDocument()
    report = ImportReport()
    objs: list[MapObject] = []
    layout: list[Any] = []
    world_seen = False
    entities_marked = False
    world_blocks: list[RawNode] = []
    for block in root:
        name = block.name
        if name == "world" and block.has_children() and not world_seen:
            world_seen = True
            layout.append(WORLD_MARK)
            kvs: list[tuple[str, str]] = []
            for c in block:
                if c.has_children():
                    if c.name == "solid":
                        objs.append(_parse_solid(doc, c, None, False))
                    elif c.name == "hidden":
                        for h in c:
                            if h.name == "solid":
                                objs.append(_parse_solid(doc, h, None, True))
                            else:
                                world_blocks.append(["hidden", [kv_to_raw(h)]])
                    else:
                        world_blocks.append(kv_to_raw(c))
                elif c.name == "id":
                    doc.extra["world_id"] = _int_or_none(c.value)
                else:
                    kvs.append((c.real_name, c.value))
            doc.world_keyvalues = tuple(kvs)
        elif name == "entity" and block.has_children():
            if not entities_marked:
                layout.append(ENTITIES_MARK)
                entities_marked = True
            _parse_entity(doc, block, False, objs)
        elif name == "hidden" and block.has_children() and any(c.name == "entity" for c in block):
            if not entities_marked:
                layout.append(ENTITIES_MARK)
                entities_marked = True
            for c in block:
                if c.name == "entity":
                    _parse_entity(doc, c, True, objs)
                else:
                    layout.append(["hidden", [kv_to_raw(c)]])
        else:
            layout.append(kv_to_raw(block))
    if not world_seen:
        raise VmfError("Die Datei enthält keinen world-Block")
    if not entities_marked:
        layout.insert(layout.index(WORLD_MARK) + 1, ENTITIES_MARK)
    doc.extra["vmf_layout"] = layout
    if world_blocks:
        doc.extra["world_blocks"] = world_blocks
    doc._insert(objs)
    for o in objs:
        if isinstance(o, Solid):
            report.solids += 1
            if not o.is_valid():
                report.warnings.append(f"Brush {o.vmf_id}: ungültige Geometrie (wird trotzdem übernommen)")
        else:
            report.entities += 1
    return doc, report


def load_vmf(path: str | os.PathLike[str]) -> tuple[MapDocument, ImportReport]:
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    return parse_vmf(text, str(path))


# ---- Export ---------------------------------------------------------------------

@dataclass
class ExportResult:
    text: str
    #: VMF-ID -> Objekt-ID, damit Compiler-Meldungen ("Brush 123") zum Objekt führen
    solid_ids: dict[int, int] = field(default_factory=dict)
    entity_ids: dict[int, int] = field(default_factory=dict)
    #: Objekt-IDs der Entities in Schreibreihenfolge; vbsp zählt so ("Entity 3" = Index 2 hier)
    entity_order: list[int] = field(default_factory=list)
    side_count: int = 0


class _Ids:
    def __init__(self, reserved: Iterable[int] = ()) -> None:
        self.used: set[int] = set(reserved)
        self.next = 1

    def take(self, wanted: int | None) -> int:
        if wanted is not None and wanted > 0 and wanted not in self.used:
            self.used.add(wanted)
            return wanted
        while self.next in self.used:
            self.next += 1
        self.used.add(self.next)
        return self.next


DEFAULT_PRE = [
    ["versioninfo", [["editorversion", "400"], ["editorbuild", "8864"], ["mapversion", "1"],
                     ["formatversion", "100"], ["prefab", "0"]]],
    ["visgroups", []],
    ["viewsettings", [["bSnapToGrid", "1"], ["bShowGrid", "1"], ["bShowLogicalGrid", "0"],
                      ["nGridSpacing", "64"], ["bShow3DGrid", "0"]]],
]
DEFAULT_POST = [
    ["cameras", [["activecamera", "-1"]]],
    ["cordons", [["active", "0"]]],
]


def _editor_nodes(e: EditorInfo, extra: dict[str, Any], groups: dict[int, int] | None = None) -> list[RawNode]:
    nodes: list[RawNode] = [["color", f"{e.color[0]} {e.color[1]} {e.color[2]}"]]
    for v in e.visgroup_ids:
        nodes.append(["visgroupid", str(v)])
    if e.group_id is not None:
        nodes.append(["groupid", str((groups or {}).get(e.group_id, e.group_id))])
    raw = extra.get("editor_raw")
    if raw:
        nodes += raw
    else:
        nodes += [["visgroupshown", "1"], ["visgroupautoshown", "1"]]
    return nodes


def _group_block_id(node: Any) -> int | None:
    if isinstance(node, list) and len(node) == 2 and node[0] == "group" and isinstance(node[1], list):
        for child in node[1]:
            if child[0] == "id" and isinstance(child[1], str):
                return _int_or_none(child[1])
    return None


class _Writer:
    def __init__(self, doc: MapDocument, for_compile: bool = False) -> None:
        self.doc = doc
        # Für die Compiler ist Ausblenden nur eine Ansichtssache: alles wird gebaut.
        self.for_compile = for_compile
        self.out: list[str] = []
        self.object_ids = _Ids()
        self.side_ids = _Ids()
        self.result = ExportResult("")
        # Hammer zählt Welt, Brushes und Entities mit einem gemeinsamen Zähler. Erst
        # behalten alle Objekte ihre importierte ID (Kopien mit gleicher ID nicht),
        # dann bekommen neue Objekte freie Nummern.
        self.world_id = self.object_ids.take(doc.extra.get("world_id") or 1)
        # Gruppen aus der importierten Datei behalten ihre Nummer und ihren group-Block
        known_groups = {gid for node in doc.extra.get("world_blocks", ()) if (gid := _group_block_id(node)) is not None}
        self.object_ids.used |= known_groups
        ordered = sorted(doc.objects(), key=lambda o: o.id)
        self._assigned: dict[int, int] = {}
        for o in ordered:
            if o.vmf_id is not None and o.vmf_id > 0 and o.vmf_id not in self.object_ids.used:
                self._assigned[o.id] = self.object_ids.take(o.vmf_id)
        for o in ordered:
            if o.id not in self._assigned:
                self._assigned[o.id] = self.object_ids.take(None)
        # Neue Gruppen brauchen einen group-Block im world-Block; Hammer zählt sie mit den Objekten
        self.groups: dict[int, int] = {g: g for g in known_groups}
        for gid in sorted({g for o in ordered if (g := o.editor.group_id) is not None} - known_groups):
            self.groups[gid] = self.object_ids.take(None)
        self.new_groups = sorted(v for g, v in self.groups.items() if g not in known_groups)
        for s in doc.solids():
            for f in s.faces:
                if f.vmf_id is not None:
                    self.side_ids.used.add(f.vmf_id)
        self._side_seen: set[int] = set()
        # Seiten-IDs vorab vergeben: Overlays (Entities) nennen Seiten, die erst später oder
        # in Brush-Entities geschrieben werden
        self._face_side: dict[tuple[int, int], int] = {}
        for s in sorted(doc.solids(), key=lambda s: s.id):
            for i, f in enumerate(s.faces):
                self._face_side[(s.id, i)] = self.side_id(f.vmf_id)

    def w(self, line: str, depth: int) -> None:
        self.out.append("\t" * depth + line + "\n")

    def kv(self, key: str, value: str, depth: int) -> None:
        self.out.append(f'{chr(9) * depth}"{key}" "{value}"\n')

    def raw(self, nodes: Iterable[RawNode], depth: int) -> None:
        for n in nodes:
            _write_raw(n, self.out, depth)

    def side_id(self, wanted: int | None) -> int:
        if wanted is not None and wanted > 0 and wanted not in self._side_seen:
            self._side_seen.add(wanted)
            return wanted
        nid = self.side_ids.take(None)
        self._side_seen.add(nid)
        return nid

    def solid(self, s: Solid, depth: int) -> None:
        vid = self._assigned[s.id]
        self.result.solid_ids[vid] = s.id
        self.w("solid", depth)
        self.w("{", depth)
        self.kv("id", str(vid), depth + 1)
        for i, f in enumerate(s.faces):
            self.w("side", depth + 1)
            self.w("{", depth + 1)
            d = depth + 2
            self.kv("id", str(self._face_side[(s.id, i)]), d)
            self.kv("plane", format_plane(f.points), d)
            self.kv("material", f.material, d)
            self.kv("uaxis", format_axis(f.uaxis), d)
            self.kv("vaxis", format_axis(f.vaxis), d)
            self.kv("rotation", fmt(f.rotation), d)
            self.kv("lightmapscale", str(f.lightmapscale), d)
            self.kv("smoothing_groups", str(f.smoothing_groups), d)
            self.raw(f.extra.get("raw", ()), d)
            self.w("}", depth + 1)
            self.result.side_count += 1
        self.raw(s.extra.get("raw", ()), depth + 1)
        self.w("editor", depth + 1)
        self.w("{", depth + 1)
        self.raw(_editor_nodes(s.editor, s.extra, self.groups), depth + 2)
        self.w("}", depth + 1)
        self.w("}", depth)

    def world(self) -> None:
        self.w("world", 0)
        self.w("{", 0)
        self.kv("id", str(self.world_id), 1)
        kvs = list(self.doc.world_keyvalues)
        if not any(k.lower() == "classname" for k, _ in kvs):
            kvs.insert(0, ("classname", "worldspawn"))
        for k, v in kvs:
            self.kv(k, v, 1)
        world_solids = sorted((s for s in self.doc.solids() if s.parent_id is None), key=lambda s: s.id)
        for s in world_solids:
            if not self._hidden(s):
                self.solid(s, 1)
        hidden = [s for s in world_solids if self._hidden(s)]
        if hidden:
            for s in hidden:
                self.w("hidden", 1)
                self.w("{", 1)
                self.solid(s, 2)
                self.w("}", 1)
        self.raw(self.doc.extra.get("world_blocks", ()), 1)
        for gid in self.new_groups:
            _write_raw(["group", [["id", str(gid)], ["editor", [["color", "0 100 0"], ["visgroupshown", "1"],
                                                                 ["visgroupautoshown", "1"]]]]], self.out, 1)
        self.w("}", 0)

    def _hidden(self, o: MapObject) -> bool:
        return o.editor.hidden and not self.for_compile

    def _overlay_keyvalues(self, e: Entity) -> tuple[tuple[str, str], ...]:
        """Overlay aus dem Werkzeug: Basis am Ursprung, Seiten aus der aktuellen Geometrie."""
        sides = " ".join(str(self._face_side[key]) for key in overlay_sides(self.doc, e) if key in self._face_side)
        origin = e.get("origin")
        out = []
        for k, v in e.keyvalues:
            if k == "sides":
                v = sides
            elif k == "BasisOrigin" and origin:
                v = origin
            out.append((k, v))
        return tuple(out)

    def entity(self, e: Entity, depth: int) -> None:
        vid = self._assigned[e.id]
        self.result.entity_ids[vid] = e.id
        self.result.entity_order.append(e.id)
        self.w("entity", depth)
        self.w("{", depth)
        d = depth + 1
        self.kv("id", str(vid), d)
        self.kv("classname", e.classname, d)
        keyvalues = e.keyvalues
        if is_auto_overlay(e):
            keyvalues = self._overlay_keyvalues(e)
        for k, v in keyvalues:
            self.kv(k, v, d)
        if e.outputs:
            # Trennzeichen wie in der importierten Datei. Bei geänderten Outputs gilt:
            # ESC, wenn die Datei ESC nutzte oder ein Parameter ein Komma enthält.
            seps = e.extra.get("io_seps", "")
            known = len(seps) == len(e.outputs)
            self.w("connections", d)
            self.w("{", d)
            for i, o in enumerate(e.outputs):
                if known:
                    esc = seps[i] == "e"
                else:
                    esc = "e" in seps or "," in o.parameter
                sep = IO_SEP_ESC if esc else ","
                value = sep.join([o.target, o.input, o.parameter, fmt(o.delay), str(o.times)])
                self.kv(o.output, value, d + 1)
            self.w("}", d)
        children = sorted(self.doc.children(e.id), key=lambda s: s.id)
        for s in children:
            if not self._hidden(s) or self._hidden(e):
                self.solid(s, d)
        for s in children:
            if self._hidden(s) and not self._hidden(e):
                self.w("hidden", d)
                self.w("{", d)
                self.solid(s, d + 1)
                self.w("}", d)
        self.raw(e.extra.get("raw", ()), d)
        self.w("editor", d)
        self.w("{", d)
        self.raw(_editor_nodes(e.editor, e.extra, self.groups), d + 1)
        self.w("}", d)
        self.w("}", depth)

    def entities(self) -> None:
        for e in sorted(self.doc.entities(), key=lambda e: e.id):
            if self._hidden(e):
                self.w("hidden", 0)
                self.w("{", 0)
                self.entity(e, 1)
                self.w("}", 0)
            else:
                self.entity(e, 0)

    def run(self) -> ExportResult:
        layout = self.doc.extra.get("vmf_layout")
        if not layout:
            layout = [*DEFAULT_PRE, WORLD_MARK, ENTITIES_MARK, *DEFAULT_POST]
        for item in layout:
            if item == WORLD_MARK:
                self.world()
            elif item == ENTITIES_MARK:
                self.entities()
            else:
                _write_raw(item, self.out, 0)
        self.result.text = "".join(self.out)
        return self.result


def export_vmf(doc: MapDocument, for_compile: bool = False) -> ExportResult:
    """VMF-Text. `for_compile` schreibt ausgeblendete Objekte normal, damit sie mitgebaut werden."""
    return _Writer(doc, for_compile).run()


def save_vmf(doc: MapDocument, path: str | os.PathLike[str], for_compile: bool = False) -> ExportResult:
    result = export_vmf(doc, for_compile)
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(result.text, encoding="utf-8", newline="\r\n")
    os.replace(tmp, path)
    return result
