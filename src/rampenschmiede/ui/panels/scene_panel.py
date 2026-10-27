"""Szenen-Baum: alle Objekte nach Ordnern (Rampen, Welt, Trigger, Spawns …), mit Auge zum
Ein- und Ausblenden ganzer Ordner oder einzelner Objekte. Klick wählt aus, Doppelklick
zentriert die Ansichten darauf."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.lights import LIGHT_CLASSES, parse_color
from ...core.model import Entity
from ...core.scene import FOLDERS, SceneIndex, label, members
from .. import icons
from ..editor import EditorContext

ID_ROLE = Qt.UserRole
FOLDER_ROLE = Qt.UserRole + 1
EYE_COLUMN = 1
#: So viele Einträge zeigt ein Ordner höchstens (große BSPs haben Zehntausende Brushes)
MAX_CHILDREN = 2000


class ScenePanel(QWidget):
    def __init__(self, editor: EditorContext, center: Callable[[], None] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        self._center = center
        self._index = SceneIndex()
        self._folders: dict[str, list[int]] = {}
        self._folder_of: dict[int, str] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(EYE_COLUMN, QHeaderView.Fixed)
        self.tree.header().resizeSection(EYE_COLUMN, 28)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.itemExpanded.connect(self._fill)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        self.tree.itemSelectionChanged.connect(self._select)
        lay.addWidget(self.tree)
        self.hint = QLabel(self.tr("Auge: Ordner ein-/ausblenden · Doppelklick: hinspringen"))
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #9aa0a6;")
        lay.addWidget(self.hint)
        self._items: dict[str, QTreeWidgetItem] = {}
        for f in FOLDERS:
            item = QTreeWidgetItem([self.tr(f.label), ""])
            item.setIcon(0, icons.icon(f.icon))
            item.setData(0, FOLDER_ROLE, f.key)
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            item.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            self.tree.addTopLevelItem(item)
            self._items[f.key] = item
        self._syncing = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)
        editor.document_changed.connect(self._timer.start)
        editor.document_replaced.connect(self.refresh)
        editor.selection_changed.connect(self._sync_selection)
        self.refresh()

    # ---- Aufbau ---------------------------------------------------------------
    def refresh(self) -> None:
        doc = self.editor.doc
        self._folders = self._index.folders(doc)
        self._folder_of = {oid: key for key, ids in self._folders.items() for oid in ids}
        for f in FOLDERS:
            item = self._items[f.key]
            ids = self._folders[f.key]
            item.setText(0, f"{self.tr(f.label)} ({len(ids)})")
            item.setHidden(not ids)
            self._set_eye(item, bool(ids) and all(self._hidden(i) for i in ids))
            if item.isExpanded():
                self._fill(item, force=True)
            else:
                item.takeChildren()
        self._sync_selection()

    def _fill(self, item: QTreeWidgetItem, force: bool = False) -> None:
        key = item.data(0, FOLDER_ROLE)
        if key is None or (item.childCount() and not force):
            return
        item.takeChildren()
        doc = self.editor.doc
        ids = self._folders.get(key, [])
        for oid in ids[:MAX_CHILDREN]:
            obj = doc.get(oid)
            if obj is None:
                continue
            child = QTreeWidgetItem([label(obj), ""])
            child.setData(0, ID_ROLE, oid)
            if isinstance(obj, Entity) and obj.classname.lower() in LIGHT_CLASSES:
                child.setIcon(0, _swatch(obj))
            self._set_eye(child, obj.editor.hidden)
            item.addChild(child)
        if len(ids) > MAX_CHILDREN:
            more = QTreeWidgetItem([self.tr("… und {0} weitere").format(len(ids) - MAX_CHILDREN), ""])
            more.setFlags(Qt.ItemIsEnabled)
            item.addChild(more)
        self._sync_selection()

    def _set_eye(self, item: QTreeWidgetItem, hidden: bool) -> None:
        item.setIcon(EYE_COLUMN, icons.icon("eye_off" if hidden else "eye"))
        item.setToolTip(EYE_COLUMN, self.tr("Einblenden") if hidden else self.tr("Ausblenden"))
        for col in (0, EYE_COLUMN):
            item.setForeground(col, Qt.gray if hidden else self.palette().text())

    def _hidden(self, oid: int) -> bool:
        obj = self.editor.doc.get(oid)
        return obj is not None and obj.editor.hidden

    # ---- Bedienung ---------------------------------------------------------------
    def folder_ids(self, key: str) -> list[int]:
        return list(self._folders.get(key, []))

    def toggle_folder(self, key: str) -> None:
        ids = self._folders.get(key, [])
        if not ids:
            return
        hide = not all(self._hidden(i) for i in ids)
        self.editor.set_hidden(members(self.editor.doc, ids), hide)

    def toggle_object(self, oid: int) -> None:
        obj = self.editor.doc.get(oid)
        if obj is not None:
            self.editor.set_hidden(members(self.editor.doc, [oid]), not obj.editor.hidden)

    def _clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if column != EYE_COLUMN:
            return
        key = item.data(0, FOLDER_ROLE)
        if key is not None:
            self.toggle_folder(key)
        elif (oid := item.data(0, ID_ROLE)) is not None:
            self.toggle_object(oid)

    def _double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        if column == EYE_COLUMN or item.data(0, ID_ROLE) is None:
            return
        if self._center is not None:
            self._center()

    def _select(self) -> None:
        if self._syncing:
            return
        ids = [i.data(0, ID_ROLE) for i in self.tree.selectedItems() if i.data(0, ID_ROLE) is not None]
        ids = [i for i in ids if not self._hidden(i)]
        if ids:
            self.editor.set_selection(ids)

    def _sync_selection(self) -> None:
        """Auswahl in der Liste zeigen: Ordner der gewählten Objekte aufklappen, Einträge
        markieren und zum ersten hinscrollen."""
        if self._syncing:
            return
        sel = self.editor.selection
        self._syncing = True
        try:
            for key in {self._folder_of[i] for i in sel if i in self._folder_of}:
                folder = self._items[key]
                if not folder.isExpanded():
                    folder.setExpanded(True)
                    self._fill(folder)
            first = None
            for item in self._items.values():
                for k in range(item.childCount()):
                    child = item.child(k)
                    oid = child.data(0, ID_ROLE)
                    on = oid is not None and oid in sel
                    child.setSelected(on)
                    if on and first is None:
                        first = child
            if first is not None:
                self.tree.scrollToItem(first)
        finally:
            self._syncing = False


def _swatch(ent: Entity) -> QIcon:
    """Kleines Farbfeld in der Lichtfarbe."""
    rgb, _ = parse_color(ent.get("_light"))
    pix = QPixmap(12, 12)
    pix.fill(QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)))
    return QIcon(pix)
