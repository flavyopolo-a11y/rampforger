"""Sichtgruppen unter dem Szenen-Baum: Häkchen blendet eine Gruppe ein oder aus, Doppelklick
wählt ihre Objekte aus, Doppelklick auf den Namen zum Umbenennen."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core import visgroups as vg
from ...i18n import N_
from ..editor import EditorContext
from ..icons import icon

ID_ROLE = Qt.UserRole


def _swatch(color: tuple[int, int, int]) -> QIcon:
    pix = QPixmap(12, 12)
    pix.fill(QColor(*color))
    return QIcon(pix)


class VisgroupPanel(QWidget):
    def __init__(self, editor: EditorContext, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        title = QLabel(self.tr("Sichtgruppen"))
        title.setStyleSheet("font-weight: bold;")
        head.addWidget(title, 1)
        self.new_btn = self._button("visgroup", N_("Neue Sichtgruppe aus der Auswahl"), self.create_from_selection)
        self.add_btn = self._button("new", N_("Auswahl zur markierten Gruppe hinzufügen"), self.add_selection)
        self.remove_btn = self._button("hole", N_("Auswahl aus der markierten Gruppe nehmen"), self.remove_selection)
        self.delete_btn = self._button("eye_off", N_("Markierte Gruppe auflösen (die Objekte bleiben)"),
                                       self.delete_current)
        for b in (self.new_btn, self.add_btn, self.remove_btn, self.delete_btn):
            head.addWidget(b)
        lay.addLayout(head)
        self.list = QListWidget()
        self.list.setMinimumHeight(48)
        self.list.setToolTip(self.tr("Häkchen: ein-/ausblenden · Doppelklick: Objekte auswählen"))
        self.list.itemChanged.connect(self._item_changed)
        self.list.itemDoubleClicked.connect(lambda item: self.select_members(item.data(ID_ROLE)))
        self.list.currentItemChanged.connect(lambda *_a: self._update_buttons())
        lay.addWidget(self.list, 1)
        self._filling = False
        editor.document_changed.connect(self.refresh)
        editor.document_replaced.connect(self.refresh)
        editor.selection_changed.connect(self._update_buttons)
        self.refresh()

    def _button(self, icon_name: str, tip: str, slot) -> QToolButton:
        b = QToolButton()
        b.setIcon(icon(icon_name))
        b.setAutoRaise(True)
        b.setToolTip(self.tr(tip))
        b.clicked.connect(lambda: slot())
        return b

    # ---- Anzeige -----------------------------------------------------------------------
    def refresh(self) -> None:
        doc = self.editor.doc
        groups = vg.visgroups(doc)
        current = self.current_id()
        counts: dict[int, int] = {}
        for o in doc.objects():
            for v in o.editor.visgroup_ids:
                counts[v] = counts.get(v, 0) + 1
        self._filling = True
        try:
            self.list.clear()
            for g in groups:
                item = QListWidgetItem(_swatch(g.color), f"{g.name}  ({counts.get(g.id, 0)})")
                item.setData(ID_ROLE, g.id)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if g.shown else Qt.Unchecked)
                self.list.addItem(item)
                if g.id == current:
                    self.list.setCurrentItem(item)
        finally:
            self._filling = False
        self._update_buttons()

    def current_id(self) -> int | None:
        item = self.list.currentItem()
        return item.data(ID_ROLE) if item is not None else None

    def _update_buttons(self) -> None:
        has_sel = bool(self.editor.selection)
        has_group = self.current_id() is not None
        self.new_btn.setEnabled(has_sel)
        self.add_btn.setEnabled(has_sel and has_group)
        self.remove_btn.setEnabled(has_sel and has_group)
        self.delete_btn.setEnabled(has_group)

    # ---- Aktionen ----------------------------------------------------------------------
    def _item_changed(self, item: QListWidgetItem) -> None:
        if self._filling:
            return
        self.set_shown(item.data(ID_ROLE), item.checkState() == Qt.Checked)

    def set_shown(self, gid: int, shown: bool) -> None:
        cmd = vg.set_shown(self.editor.doc, gid, shown)
        if cmd is not None:
            self.editor.run(cmd)
            if not shown:
                # Versteckte Objekte nicht ausgewählt lassen
                doc = self.editor.doc
                self.editor.set_selection([i for i in self.editor.selection
                                           if (o := doc.get(i)) is not None and not o.editor.hidden])

    def create_from_selection(self, name: str | None = None) -> int | None:
        ed = self.editor
        if not ed.selection:
            return None
        if name is None:
            name, ok = QInputDialog.getText(self, self.tr("Neue Sichtgruppe"), self.tr("Name der Gruppe"))
            if not ok:
                return None
        cmd, gid = vg.create(ed.doc, name, ed.selection)
        ed.run(cmd)
        self.refresh()
        for i in range(self.list.count()):
            if self.list.item(i).data(ID_ROLE) == gid:
                self.list.setCurrentRow(i)
        return gid

    def add_selection(self) -> None:
        gid = self.current_id()
        if gid is not None and (cmd := vg.add(self.editor.doc, gid, self.editor.selection)) is not None:
            self.editor.run(cmd)

    def remove_selection(self) -> None:
        gid = self.current_id()
        if gid is not None and (cmd := vg.remove_from(self.editor.doc, gid, self.editor.selection)) is not None:
            self.editor.run(cmd)

    def delete_current(self) -> None:
        gid = self.current_id()
        if gid is not None and (cmd := vg.delete(self.editor.doc, gid)) is not None:
            self.editor.run(cmd)

    def select_members(self, gid: int) -> None:
        doc = self.editor.doc
        ids = [i for i in vg.members(doc, gid) if (o := doc.get(i)) is not None and not o.editor.hidden
               and getattr(o, "parent_id", None) is None]
        self.editor.set_selection(ids)


__all__ = ["VisgroupPanel"]
