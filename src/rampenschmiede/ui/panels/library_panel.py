"""Bibliothek: Rampen-Vorlagen einfügen und Bausteine über ihre Regler ändern.

Oben die Vorlagen nach Gruppen, dazu die einfachen Formen (Block, Keil, …). Doppelklick oder „Einfügen“ setzt die Vorlage in die Mitte
der Ansicht von oben, Ziehen in eine Ansicht setzt sie an die Mausposition. Darunter die
Regler: für die gewählte Vorlage (Werte für das nächste Einfügen) oder, wenn ein Baustein
ausgewählt ist, für diesen Baustein. Jede Änderung baut ihn sofort neu.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.blocks import (
    block_info,
    change_block,
    dissolve,
    insert_block,
    is_block_root,
    placement_of,
)
from ...core.commands import AddObjects
from ...core.io.rsmap import ProjectFormatError
from ...core.materials.theme import block_defaults
from ...core.model import Entity
from ...core.prefabs import list_prefabs, load_prefab, make_prefab, place_prefab, save_prefab
from ...core.surf.catalog import (
    CATALOG,
    Generated,
    Param,
    Placement,
    Template,
    angle_warnings,
    generate,
    surf_angles,
)
from ...core.surf.sweep import Materials
from ..editor import EditorContext
from ..icons import icon
from ..paths import prefabs_dir
from ..tools.shape_tool import SHAPE_HINTS, SHAPES
from ..widgets.material_field import MaterialField

#: Symbol je Gruppe in der Bibliothek
CATEGORY_ICONS = {"Rampen": "ramp", "Kurven": "curve", "Spezial": "halfpipe", "Bhop": "bhop", "Zonen": "flag",
                  "Gelände": "terrain"}
MIME_TEMPLATE = "application/x-rampenschmiede-vorlage"
PREFAB_PREFIX = "prefab:"
SHAPE_PREFIX = "shape:"
TREE_ICON = 22
OK_STYLE = "color: #3a3;"
WARN_STYLE = "color: #d80; font-weight: bold;"


class _TemplateTree(QTreeWidget):
    """Liste der Vorlagen, aus der man in die Ansichten ziehen kann."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setRootIsDecorated(True)
        self.setIconSize(QSize(TREE_ICON, TREE_ICON))

    def startDrag(self, actions) -> None:
        item = self.currentItem()
        key = item.data(0, Qt.UserRole) if item else None
        if not key:
            return
        mime = QMimeData()
        mime.setData(MIME_TEMPLATE, key.encode("utf-8"))
        mime.setText(item.text(0))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


def _editor_for(p: Param, editor: EditorContext | None = None) -> tuple[QWidget, Callable[[], Any], Callable[[Any], None], Any]:
    """Eingabefeld für einen Regler: (Widget, lesen, setzen, Änderungs-Signal)."""
    kind = p.kind
    if p.key.startswith("mat_"):
        m = MaterialField(editor)
        return m, m.value, m.set_value, m.changed
    if kind == "bool":
        w = QCheckBox()
        return w, w.isChecked, w.setChecked, w.toggled
    if kind == "choice":
        c = QComboBox()
        for value, label in p.choices:
            c.addItem(label, value)

        def set_choice(v: Any, c=c) -> None:
            i = c.findData(v)
            c.setCurrentIndex(max(0, i))
        return c, c.currentData, set_choice, c.currentIndexChanged
    if kind == "text":
        line = QLineEdit()
        return line, line.text, line.setText, line.editingFinished
    if kind == "int":
        s = QSpinBox()
        s.setRange(int(p.minimum), int(p.maximum))
        s.setSingleStep(int(p.step))
    else:
        s = QDoubleSpinBox()
        s.setRange(p.minimum, p.maximum)
        s.setSingleStep(p.step)
        s.setDecimals(1 if float(p.step) >= 0.1 else 2)
    if p.unit:
        s.setSuffix(f" {p.unit}")
    s.setKeyboardTracking(False)
    s.setAccelerated(True)
    return s, s.value, s.setValue, s.valueChanged


class LibraryPanel(QWidget):
    #: Ein Baustein wurde eingefügt (ID der Wurzel)
    inserted = Signal(int)

    def __init__(self, editor: EditorContext, view_center: Callable[[], tuple[float, float, float]],
                 parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.view_center = view_center
        #: Werte, mit denen jede Vorlage als Nächstes eingefügt wird
        self.next_values: dict[str, dict] = {}
        self._fields: dict[str, tuple[QWidget, Callable, Callable, QLabel]] = {}
        self._updating = False
        self._block_id: int | None = None
        #: Was das Formular gerade zeigt, damit es nur bei echten Änderungen neu aufgebaut wird
        self._shown: tuple | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.tree = _TemplateTree()
        groups: dict[str, QTreeWidgetItem] = {}
        for t in CATALOG.values():
            g = groups.get(t.category)
            if g is None:
                g = groups[t.category] = QTreeWidgetItem(self.tree, [self.tr(t.category)])
                g.setIcon(0, icon(CATEGORY_ICONS.get(t.category, "shape")))
                g.setFlags(g.flags() & ~Qt.ItemIsDragEnabled)
                g.setExpanded(True)
            item = QTreeWidgetItem(g, [self.tr(t.name)])
            item.setIcon(0, icon(CATEGORY_ICONS.get(t.category, "shape")))
            item.setData(0, Qt.UserRole, t.key)
            item.setToolTip(0, self.tr(t.description))
        self.shape_group = QTreeWidgetItem(self.tree, [self.tr("Formen")])
        self.shape_group.setIcon(0, icon("shape"))
        self.shape_group.setFlags(self.shape_group.flags() & ~Qt.ItemIsDragEnabled)
        self.shape_group.setExpanded(True)
        for key, name in SHAPES.items():
            item = QTreeWidgetItem(self.shape_group, [self.tr(name)])
            item.setIcon(0, icon(f"shape_{key}"))
            item.setData(0, Qt.UserRole, SHAPE_PREFIX + key)
            item.setToolTip(0, self.tr(SHAPE_HINTS[key]))
        self.prefab_group = QTreeWidgetItem(self.tree, [self.tr("Eigene Prefabs")])
        self.prefab_group.setIcon(0, icon("prefab"))
        self.prefab_group.setFlags(self.prefab_group.flags() & ~Qt.ItemIsDragEnabled)
        self.prefab_group.setExpanded(True)
        self.refresh_prefabs()
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.tree.currentItemChanged.connect(self._template_changed)
        self.tree.itemClicked.connect(self._template_clicked)
        self.tree.itemDoubleClicked.connect(lambda item, _col: self.insert_current() if item.data(0, Qt.UserRole) else None)
        lay.addWidget(self.tree, 3)

        row = QHBoxLayout()
        self.insert_btn = QPushButton(self.tr("Einfügen"))
        self.insert_btn.setToolTip(self.tr("In die Mitte der Ansicht von oben setzen. Oder die Vorlage in eine Ansicht ziehen."))
        self.insert_btn.clicked.connect(self.insert_current)
        row.addWidget(self.insert_btn)
        self.save_btn = QPushButton(self.tr("Als Prefab speichern …"))
        self.save_btn.setToolTip(self.tr("Die Auswahl als eigenes Prefab in der Bibliothek ablegen"))
        self.save_btn.clicked.connect(lambda: self.save_selection_as_prefab())
        row.addWidget(self.save_btn)
        lay.addLayout(row)

        self.box = QGroupBox()
        box_lay = QVBoxLayout(self.box)
        self.description = QLabel()
        self.description.setWordWrap(True)
        box_lay.addWidget(self.description)
        self.form = QFormLayout()
        box_lay.addLayout(self.form)
        self.angle_label = QLabel()
        self.angle_label.setWordWrap(True)
        box_lay.addWidget(self.angle_label)
        self.dissolve_btn = QPushButton(self.tr("Baustein lösen"))
        self.dissolve_btn.setToolTip(self.tr(
            "Macht normale Brushes daraus. Danach lässt sich die Form frei bearbeiten, aber nicht mehr über Regler."))
        self.dissolve_btn.clicked.connect(self._dissolve)
        box_lay.addWidget(self.dissolve_btn)
        lay.addWidget(self.box, 2)

        editor.selection_changed.connect(self._sync_from_selection)
        editor.document_changed.connect(self._sync_from_selection)
        editor.template_dropped.connect(self.insert)
        editor.tool_changed.connect(self._tool_changed)
        shape_tool = editor.tools.get("shape")
        if shape_tool is not None:
            shape_tool.signals.shape_changed.connect(lambda _k: self._tool_changed("shape"))
        first = self.tree.topLevelItem(0).child(0)
        self.tree.setCurrentItem(first)
        self._sync_from_selection()

    # ---- Zustand ---------------------------------------------------------------------
    def current_key(self) -> str | None:
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item else None

    def current_template(self) -> Template | None:
        key = self.current_key()
        return CATALOG.get(key) if key else None

    def selected_block(self) -> Entity | None:
        if len(self.editor.selection) != 1:
            return None
        obj = self.editor.doc.get(next(iter(self.editor.selection)))
        return obj if isinstance(obj, Entity) and is_block_root(obj) else None

    def _template_key(self) -> str | None:
        return self.current_key()

    def _template_clicked(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        """Vorlage angeklickt: gleich zum Malen bereit (Vorschau am Mauszeiger). Eine Form
        angeklickt: Formen-Werkzeug mit dieser Form, dann in einer Ansicht aufziehen."""
        key = item.data(0, Qt.UserRole)
        if not key:
            return
        if key.startswith(SHAPE_PREFIX):
            if "shape" in self.editor.tools:
                self.editor.set_tool("shape")
                self.editor.tools["shape"].set_shape(key[len(SHAPE_PREFIX):])  # type: ignore[attr-defined]
            return
        if key.startswith(PREFAB_PREFIX):
            return
        if "paint" in self.editor.tools:
            self.editor.set_selection(set())
            self.editor.set_tool("paint")

    def _tool_changed(self, name: str) -> None:
        """Formen-Werkzeug aktiv: die passende Form in der Liste markieren und zeigen."""
        if name != "shape" or self.editor.tool is not self.editor.tools.get("shape"):
            return
        shape = self.editor.tools["shape"].options.shape  # type: ignore[attr-defined]
        for i in range(self.shape_group.childCount()):
            child = self.shape_group.child(i)
            if child.data(0, Qt.UserRole) == SHAPE_PREFIX + shape:
                if self.tree.currentItem() is not child:
                    self.tree.setCurrentItem(child)
                self.tree.scrollToItem(child)
                return

    def _template_changed(self, *_args) -> None:
        if self.selected_block() is None:
            self._show_form()

    def _sync_from_selection(self) -> None:
        if self._updating:
            return
        root = self.selected_block()
        new_id = root.id if root else None
        if new_id != self._block_id:
            self._block_id = new_id
            self.editor.stack.end_merge()  # Regler eines anderen Bausteins sind ein neuer Schritt
        shown = ("block", root.id, block_info(root)) if root else ("template", self._template_key())
        if shown != self._shown:
            self._show_form()

    # ---- Formular ----------------------------------------------------------------------
    def _show_form(self) -> None:
        root = self.selected_block()
        self._shown = ("block", root.id, block_info(root)) if root else ("template", self._template_key())
        if root is not None:
            info = block_info(root)
            assert info is not None
            template = CATALOG.get(info["template"])
            values = dict(info["values"])
            at = placement_of(info)
            self.box.setTitle(self.tr("Baustein: {0}").format(self.tr(template.name) if template else "?"))
        else:
            template = self.current_template()
            values = template.values(self.insert_values(template)) if template else {}
            at = None
            self.box.setTitle(self.tr("Vorlage: {0}").format(self.tr(template.name)) if template else "")
        self.dissolve_btn.setVisible(root is not None)
        key = self.current_key()
        self.insert_btn.setEnabled(template is not None or bool(key and key.startswith((PREFAB_PREFIX, SHAPE_PREFIX))))
        if root is None and key and key.startswith(SHAPE_PREFIX):
            self._clear_form()
            shape = key[len(SHAPE_PREFIX):]
            self.box.setTitle(self.tr("Form: {0}").format(self.tr(SHAPES[shape])))
            self.description.setText(self.tr(SHAPE_HINTS[shape]) + "\n\n" + self.tr(
                "In einer Ansicht ein Rechteck aufziehen, Enter baut die Form. Einfügen oder Ziehen setzt sie in "
                "der zuletzt benutzten Größe ab. Seiten, Stufen usw. rechts unter Werkzeug."))
            self.angle_label.setText("")
            return
        if root is None and key and key.startswith(PREFAB_PREFIX):
            self._clear_form()
            item = self.tree.currentItem()
            self.box.setTitle(self.tr("Prefab: {0}").format(item.text(0)))
            self.description.setText(self.tr("Eigenes Prefab. Einfügen setzt es mit seiner Mitte unten an die Stelle. "
                                             "Rechtsklick zum Löschen."))
            self.angle_label.setText("")
            return
        if template is None:
            self._clear_form()
            self.description.setText("")
            self.angle_label.setText("")
            return
        self.description.setText(self.tr(template.description))
        self._build_form(template, values, at)
        if root is not None:
            self._show_angles(self._block_angles(root, template))
        else:
            self._show_angles(generate(template, values))

    def _block_angles(self, root: Entity, template: Template) -> Generated:
        """Winkel aus den vorhandenen Brushes, ohne neu zu rechnen."""
        faces = [s.faces for s in self.editor.doc.children(root.id)]
        angles = surf_angles(faces, Materials().surf)
        return Generated(faces, angles, angle_warnings(angles) if template.check_angles else [])

    def _clear_form(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._fields.clear()

    def _build_form(self, template: Template, values: dict, at: Placement | None) -> None:
        self._updating = True
        try:
            self._clear_form()
            params: list[Param] = list(template.params)
            if at is not None:
                params = [
                    Param("_yaw", "Richtung", float(at.yaw), -360, 360, 15, "°", hint="0° = +X, 90° = +Y"),
                    Param("_x", "Anker X", int(at.x), -32768, 32768, 16, "u"),
                    Param("_y", "Anker Y", int(at.y), -32768, 32768, 16, "u"),
                    Param("_z", "Anker Z", int(at.z), -32768, 32768, 16, "u"),
                ] + params
            for p in params:
                widget, read, write, changed = _editor_for(p, self.editor)
                write(values.get(p.key, p.default) if not p.key.startswith("_") else p.default)
                if p.hint:
                    widget.setToolTip(self.tr(p.hint))
                label = QLabel(self.tr(p.label))
                self.form.addRow(label, widget)
                self._fields[p.key] = (widget, read, write, label)
                changed.connect(lambda *_a, k=p.key: self._field_changed(k))
            self._update_visibility(values)
        finally:
            self._updating = False

    def _update_visibility(self, values: dict) -> None:
        template = self._form_template()
        if template is None:
            return
        for p in template.params:
            field = self._fields.get(p.key)
            if field:
                show = p.applies(values)
                field[0].setVisible(show)
                field[3].setVisible(show)

    def _form_template(self) -> Template | None:
        root = self.selected_block()
        if root is not None:
            return CATALOG.get(block_info(root)["template"])  # type: ignore[index]
        return self.current_template()

    def _form_values(self) -> tuple[dict, Placement | None]:
        values = {k: f[1]() for k, f in self._fields.items() if not k.startswith("_")}
        at = None
        if "_yaw" in self._fields:
            at = Placement(self._fields["_x"][1](), self._fields["_y"][1](), self._fields["_z"][1](),
                           self._fields["_yaw"][1]() % 360)
        return values, at

    def _show_angles(self, gen: Generated) -> None:
        if gen.angle_range is None:
            self.angle_label.setText("")
            return
        lo, hi = gen.angle_range
        text = self.tr("Surf-Winkel {0:.1f}°").format(lo) if abs(hi - lo) < 0.05 else \
            self.tr("Surf-Winkel {0:.1f}° bis {1:.1f}°").format(lo, hi)
        if gen.warnings:
            self.angle_label.setStyleSheet(WARN_STYLE)
            self.angle_label.setText("⚠ " + "\n".join([text] + [self.tr(w) for w in gen.warnings]))
        else:
            self.angle_label.setStyleSheet(OK_STYLE)
            self.angle_label.setText("✓ " + text)

    def _field_changed(self, key: str) -> None:
        if self._updating:
            return
        values, at = self._form_values()
        self._update_visibility(values)
        root = self.selected_block()
        if root is None:
            template = self.current_template()
            if template is None:
                return
            # Nur die geänderten Regler merken, der Rest kommt weiter aus dem Map-Thema
            self.next_values.setdefault(template.key, {})[key] = values[key]
            self._show_angles(generate(template, values))
            return
        cmd, gen = change_block(self.editor.doc, root.id, values, at, merge_key=("baustein", root.id, key))
        self._updating = True
        try:
            self.editor.run(cmd)
        finally:
            self._updating = False
        root = self.editor.doc.get(root.id)
        self._shown = ("block", root.id, block_info(root))
        self._show_angles(gen)

    def insert_values(self, template: Template) -> dict:
        """Werte fürs nächste Einfügen: Map-Thema, darüber die selbst gestellten Regler."""
        return {**block_defaults(self.editor.doc, template), **self.next_values.get(template.key, {})}

    def refresh(self) -> None:
        """Formular neu aufbauen, z. B. nachdem sich das Map-Thema geändert hat."""
        self._shown = None
        self._sync_from_selection()

    # ---- Aktionen ----------------------------------------------------------------------
    def insert_current(self) -> None:
        key = self.current_key()
        if key:
            self.insert(key, self.view_center())

    def insert(self, key: str, point: tuple[float, float, float], yaw: float = 0.0) -> int | None:
        if key.startswith(PREFAB_PREFIX):
            return self._insert_prefab(Path(key[len(PREFAB_PREFIX):]), point)
        if key.startswith(SHAPE_PREFIX):
            return self._insert_shape(key[len(SHAPE_PREFIX):], point)
        template = CATALOG.get(key)
        if template is None:
            return None
        snap = self.editor.snap
        at = Placement(snap(point[0]), snap(point[1]), snap(point[2]), yaw)
        return self.place(key, self.insert_values(template), at)

    def place(self, key: str, values: dict, at: Placement) -> int | None:
        """Vorlage mit genau diesen Werten und dieser Platzierung einfügen (z. B. gemalt)."""
        template = CATALOG[key]
        objs, gen = insert_block(self.editor.doc, key, values, at)
        if not self.editor.run(AddObjects(objs, self.tr("{0} einfügen").format(self.tr(template.name)))):
            return None
        # Gelände sind lose Welt-Brushes: alle auswählen
        self.editor.set_selection({o.id for o in objs} if template.world else {objs[0].id})
        if template.world:
            self.editor.status_message.emit(self.tr("Gelände eingefügt. Mit dem Gelände-Werkzeug (Shift+G) weiter formen"))
        if gen.warnings:
            self.editor.status_message.emit(" · ".join(self.tr(w) for w in gen.warnings))
        self.inserted.emit(objs[0].id)
        return objs[0].id

    # ---- Eigene Prefabs ----------------------------------------------------------------
    def refresh_prefabs(self) -> None:
        self.prefab_group.takeChildren()
        for name, path in list_prefabs(prefabs_dir()):
            item = QTreeWidgetItem(self.prefab_group, [name])
            item.setIcon(0, icon("prefab"))
            item.setData(0, Qt.UserRole, PREFAB_PREFIX + str(path))
            item.setToolTip(0, str(path))
        if not self.prefab_group.childCount():
            hint = QTreeWidgetItem(self.prefab_group, [self.tr("(Auswahl → „Als Prefab speichern“)")])
            hint.setFlags(Qt.NoItemFlags)

    def save_selection_as_prefab(self, name: str | None = None) -> Path | None:
        ids = sorted(self.editor.selection)
        if not ids:
            self.editor.status_message.emit(self.tr("Erst etwas auswählen, dann als Prefab speichern"))
            return None
        if name is None:
            name, ok = QInputDialog.getText(self, self.tr("Als Prefab speichern"), self.tr("Name:"))
            if not ok or not name.strip():
                return None
        path = save_prefab(make_prefab(self.editor.doc, ids, name.strip()), prefabs_dir())
        self.refresh_prefabs()
        for i in range(self.prefab_group.childCount()):
            child = self.prefab_group.child(i)
            if child.data(0, Qt.UserRole) == PREFAB_PREFIX + str(path):
                self.tree.setCurrentItem(child)
        self.editor.status_message.emit(self.tr("Prefab „{0}“ gespeichert").format(name.strip()))
        return path

    def _insert_shape(self, shape: str, point: tuple[float, float, float]) -> int | None:
        tool = self.editor.tools.get("shape")
        if tool is None or shape not in SHAPES:
            return None
        tool.set_shape(shape)  # type: ignore[attr-defined]
        if not tool.create_at(point):  # type: ignore[attr-defined]
            return None
        return min(self.editor.selection) if self.editor.selection else None

    def _insert_prefab(self, path: Path, point: tuple[float, float, float]) -> int | None:
        try:
            data = load_prefab(path)
        except ProjectFormatError as exc:
            self.editor.status_message.emit(str(exc))
            return None
        snap = self.editor.snap
        objs, roots = place_prefab(self.editor.doc, data, (snap(point[0]), snap(point[1]), snap(point[2])))
        if not objs or not self.editor.run(AddObjects(objs, self.tr("Prefab einfügen"))):
            return None
        self.editor.set_selection(roots)
        return roots[0] if roots else None

    def _tree_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        key = item.data(0, Qt.UserRole) if item else None
        if not key or not key.startswith(PREFAB_PREFIX):
            return
        menu = QMenu(self)
        delete = menu.addAction(self.tr("Prefab löschen"))
        if menu.exec(self.tree.viewport().mapToGlobal(pos)) is delete:
            answer = QMessageBox.question(self, self.tr("Prefab löschen"),
                                          self.tr("„{0}“ endgültig löschen?").format(item.text(0)),
                                          QMessageBox.Yes | QMessageBox.No)
            if answer == QMessageBox.Yes:
                Path(key[len(PREFAB_PREFIX):]).unlink(missing_ok=True)
                self.refresh_prefabs()

    def _dissolve(self) -> None:
        root = self.selected_block()
        if root is None:
            return
        cmd = dissolve(self.editor.doc, [root.id])
        if cmd is not None:
            self.editor.run(cmd)
            self.editor.status_message.emit(self.tr("Baustein gelöst: Die Brushes sind jetzt frei bearbeitbar"))
