"""Hauptfenster: Menüs, Werkzeugleiste, Ansichten, Panels, Datei-Operationen."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolBar,
)

from .. import __version__
from ..core.commands import AddObjects
from ..core.io import rsmap
from ..core.model import Entity, MapDocument, MapObject
from .dialogs.transform_dialog import TransformDialog
from .editor import EditorContext
from .panels.selection_panel import SelectionPanel
from .panels.tool_options import ToolOptionsPanel
from .tools.entity_tool import EntityTool
from .tools.select_tool import SelectTool
from .tools.shape_tool import ShapeTool
from .viewports.layout import ViewportGrid

APP_NAME = "Rampenschmiede"
FILE_FILTER = "Rampenschmiede-Projekt (*.rsmap)"
MAX_RECENT = 8
DOCK_MIN_WIDTH = 320

CONTROLS_HELP = """
<h3>Kamera</h3>
<table>
<tr><td><b>3D</b>: rechte Maustaste halten</td><td>Umsehen, dazu W A S D fliegen, Q/E runter/hoch</td></tr>
<tr><td><b>3D</b>: Z</td><td>Umsehen ein/aus (wie Hammer)</td></tr>
<tr><td><b>3D</b>: Mausrad</td><td>vor/zurück, mit Shift schneller</td></tr>
<tr><td>Mittlere Maustaste oder Leertaste + Ziehen</td><td>Ansicht verschieben</td></tr>
<tr><td><b>2D</b>: Mausrad</td><td>zoomen zum Mauszeiger</td></tr>
</table>
<h3>Bearbeiten</h3>
<table>
<tr><td>[ und ]</td><td>Raster feiner / gröber</td></tr>
<tr><td>Pfeiltasten (2D)</td><td>Auswahl um eine Rasterweite verschieben</td></tr>
<tr><td>Shift + Ziehen</td><td>Auswahl kopieren</td></tr>
<tr><td>Zweiter Klick auf Auswahl</td><td>Dreh- statt Skaliergriffe</td></tr>
<tr><td>Strg+M</td><td>Transformieren mit exakten Zahlen</td></tr>
<tr><td>Strg+L / Strg+I</td><td>Spiegeln horizontal / vertikal (bezogen auf die aktive 2D-Ansicht)</td></tr>
<tr><td>H / Strg+H / U</td><td>Auswahl ausblenden / Rest ausblenden / alles einblenden</td></tr>
<tr><td>Enter / Esc</td><td>Form erstellen / Rahmen oder Auswahl verwerfen</td></tr>
</table>
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.editor = EditorContext()
        for tool in (SelectTool(self.editor), ShapeTool(self.editor), EntityTool(self.editor)):
            self.editor.register_tool(tool)
        self._clipboard: list[MapObject] = []
        self.settings = QSettings("Rampenschmiede", "Rampenschmiede")

        self.grid_view = ViewportGrid(self.editor)
        self.setCentralWidget(self.grid_view)
        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_statusbar()

        ed = self.editor
        ed.history_changed.connect(self._update_title)
        ed.history_changed.connect(self._update_undo_actions)
        ed.document_replaced.connect(self._update_title)
        ed.status_message.connect(lambda m: self.statusBar().showMessage(m, 5000))
        ed.grid_changed.connect(lambda g: self.grid_label.setText(self.tr("Raster {0}").format(g)))
        ed.selection_changed.connect(self._update_selection_label)
        ed.tool_changed.connect(self._on_tool_changed)

        ed.set_tool("select")
        self._restore_window()
        self._update_title()
        self._update_undo_actions()

    # ---- Aufbau ------------------------------------------------------------------
    def _build_docks(self) -> None:
        self.tool_dock = QDockWidget(self.tr("Werkzeug"), self)
        self.tool_dock.setObjectName("dock_tool")
        self.tool_options = ToolOptionsPanel(self.editor)
        self.tool_dock.setWidget(self.tool_options)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tool_dock)
        self.sel_dock = QDockWidget(self.tr("Auswahl"), self)
        self.sel_dock.setObjectName("dock_selection")
        self.sel_dock.setWidget(SelectionPanel(self.editor))
        self.addDockWidget(Qt.RightDockWidgetArea, self.sel_dock)
        # Ohne Mindestbreite drücken die Ansichten die Panels auf wenige Pixel zusammen.
        for dock in (self.tool_dock, self.sel_dock):
            dock.widget().setMinimumWidth(DOCK_MIN_WIDTH)

    def _action(self, text: str, slot, shortcut: str | QKeySequence | None = None, tip: str = "",
                checkable: bool = False) -> QAction:
        a = QAction(self.tr(text), self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.WindowShortcut)
        if tip:
            a.setStatusTip(self.tr(tip))
            a.setToolTip(f"{self.tr(text)} ({a.shortcut().toString()})\n{self.tr(tip)}" if shortcut else self.tr(tip))
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        return a

    def _build_actions(self) -> None:
        ed = self.editor
        self.act_new = self._action("&Neu", self.file_new, QKeySequence.New, "Neue, leere Map")
        self.act_open = self._action("Ö&ffnen …", self.file_open, QKeySequence.Open, "Projekt öffnen")
        self.act_save = self._action("&Speichern", self.file_save, QKeySequence.Save, "Projekt speichern")
        self.act_save_as = self._action("Speichern &unter …", self.file_save_as, "Ctrl+Shift+S")
        self.act_quit = self._action("&Beenden", self.close, QKeySequence.Quit)

        self.act_undo = self._action("&Rückgängig", ed.undo, QKeySequence.Undo)
        self.act_redo = self._action("&Wiederholen", ed.redo, "Ctrl+Y")
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.act_cut = self._action("Aus&schneiden", self.edit_cut, QKeySequence.Cut)
        self.act_copy = self._action("&Kopieren", self.edit_copy, QKeySequence.Copy)
        self.act_paste = self._action("&Einfügen", self.edit_paste, QKeySequence.Paste)
        self.act_delete = self._action("&Löschen", ed.delete_selection, QKeySequence.Delete)
        self.act_select_all = self._action("&Alles auswählen", ed.select_all, QKeySequence.SelectAll)
        self.act_transform = self._action("&Transformieren …", self.edit_transform, "Ctrl+M",
                                          "Verschieben, Drehen, Skalieren mit exakten Zahlen")
        self.act_flip_h = self._action("Spiegeln &horizontal", lambda: self._flip(0), "Ctrl+L")
        self.act_flip_v = self._action("Spiegeln &vertikal", lambda: self._flip(1), "Ctrl+I")

        self.act_grid_finer = self._action("Raster feiner", ed.grid_finer, "[")
        self.act_grid_coarser = self._action("Raster gröber", ed.grid_coarser, "]")
        self.act_center = self._action("Ansichten auf Auswahl zentrieren", self.center_on_selection, "Ctrl+E")
        self.act_hide = self._action("Auswahl ausblenden", lambda: ed.set_hidden(ed.selection, True), "H")
        self.act_hide_others = self._action(
            "Nicht ausgewählte ausblenden",
            lambda: ed.set_hidden([o.id for o in ed.doc.objects() if o.id not in ed.selection], True), "Ctrl+H")
        self.act_unhide = self._action("Alles einblenden",
                                       lambda: ed.set_hidden([o.id for o in ed.doc.objects()], False), "U")
        self.act_reset_layout = self._action("Layout zurücksetzen", self.reset_layout)
        self.act_expert = self._action("Experten-Modus", self.set_expert, "Ctrl+Shift+X",
                                       "Zeigt alle Einstellungen. Im Einfach-Modus bleiben Bausteine und "
                                       "Assistenten im Vordergrund.", checkable=True)

        self.tool_group = QActionGroup(self)
        self.tool_actions: dict[str, QAction] = {}
        for name, tool in ed.tools.items():
            a = self._action(tool.label, lambda _=False, n=name: ed.set_tool(n), tool.shortcut, tool.hint, True)
            self.tool_group.addAction(a)
            self.tool_actions[name] = a

        self.act_controls = self._action("&Steuerung", self.show_controls, "F1")
        self.act_about = self._action("Ü&ber Rampenschmiede", self.show_about)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu(self.tr("&Datei"))
        for a in (self.act_new, self.act_open):
            m.addAction(a)
        self.recent_menu = m.addMenu(self.tr("&Zuletzt geöffnet"))
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        for a in (self.act_save, self.act_save_as):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.act_quit)

        m = mb.addMenu(self.tr("&Bearbeiten"))
        for a in (self.act_undo, self.act_redo, None, self.act_cut, self.act_copy, self.act_paste, self.act_delete,
                  None, self.act_select_all, None, self.act_transform, self.act_flip_h, self.act_flip_v):
            m.addSeparator() if a is None else m.addAction(a)

        m = mb.addMenu(self.tr("&Ansicht"))
        for a in (self.act_grid_finer, self.act_grid_coarser, None, self.act_center, None, self.act_hide,
                  self.act_hide_others, self.act_unhide, None, self.act_expert, self.act_reset_layout):
            m.addSeparator() if a is None else m.addAction(a)
        m.addSeparator()
        m.addAction(self.tool_dock.toggleViewAction())
        m.addAction(self.sel_dock.toggleViewAction())

        m = mb.addMenu(self.tr("&Werkzeuge"))
        for a in self.tool_actions.values():
            m.addAction(a)

        m = mb.addMenu(self.tr("&Hilfe"))
        m.addAction(self.act_controls)
        m.addAction(self.act_about)

    def _build_toolbars(self) -> None:
        tb = QToolBar(self.tr("Datei"))
        tb.setObjectName("tb_file")
        for a in (self.act_new, self.act_open, self.act_save, None, self.act_undo, self.act_redo, None,
                  self.act_grid_finer, self.act_grid_coarser, None, self.act_expert):
            tb.addSeparator() if a is None else tb.addAction(a)
        self.addToolBar(Qt.TopToolBarArea, tb)
        tools = QToolBar(self.tr("Werkzeuge"))
        tools.setObjectName("tb_tools")
        tools.setToolButtonStyle(Qt.ToolButtonTextOnly)
        for a in self.tool_actions.values():
            tools.addAction(a)
        self.addToolBar(Qt.LeftToolBarArea, tools)

    def _build_statusbar(self) -> None:
        sb = self.statusBar()
        self.sel_label = QLabel()
        self.grid_label = QLabel(self.tr("Raster {0}").format(self.editor.grid))
        sb.addPermanentWidget(self.sel_label)
        sb.addPermanentWidget(self.grid_label)

    # ---- Zustand ------------------------------------------------------------------
    def _update_title(self) -> None:
        name = self.editor.file_path.name if self.editor.file_path else self.tr("Unbenannt")
        dirty = "" if self.editor.stack.is_clean() else "*"
        self.setWindowTitle(f"{name}{dirty} – {APP_NAME}")

    def _update_undo_actions(self) -> None:
        st = self.editor.stack
        self.act_undo.setEnabled(st.can_undo())
        self.act_redo.setEnabled(st.can_redo())
        self.act_undo.setText(self.tr("&Rückgängig: {0}").format(st.undo_text()) if st.can_undo() else self.tr("&Rückgängig"))
        self.act_redo.setText(self.tr("&Wiederholen: {0}").format(st.redo_text()) if st.can_redo() else self.tr("&Wiederholen"))

    def _update_selection_label(self) -> None:
        bb = self.editor.selection_bbox()
        n = len(self.editor.selection)
        if bb is None:
            self.sel_label.setText("")
        else:
            s = bb.size
            self.sel_label.setText(self.tr("{0} ausgewählt · {1:g} × {2:g} × {3:g}").format(n, s[0], s[1], s[2]))

    def _on_tool_changed(self, name: str) -> None:
        if name in self.tool_actions:
            self.tool_actions[name].setChecked(True)

    def active_viewport(self):
        for vp in self.grid_view.viewports():
            if vp.hasFocus():
                return vp
        return None

    # ---- Datei ---------------------------------------------------------------------
    def _confirm_discard(self) -> bool:
        if self.editor.stack.is_clean():
            return True
        r = QMessageBox.question(
            self, APP_NAME, self.tr("Die Map hat ungespeicherte Änderungen. Speichern?"),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Save:
            return self.file_save()
        return r == QMessageBox.Discard

    def file_new(self) -> None:
        if self._confirm_discard():
            self.editor.set_document(MapDocument(), None)
            self._update_title()

    def file_open(self) -> None:
        if not self._confirm_discard():
            return
        start = self.settings.value("last_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Projekt öffnen"), start, self.tr(FILE_FILTER))
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path) -> bool:
        try:
            doc = rsmap.load(path)
        except (OSError, rsmap.ProjectFormatError, KeyError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, APP_NAME, self.tr("Datei konnte nicht geöffnet werden:\n{0}").format(exc))
            return False
        self.editor.set_document(doc, path)
        self._remember(path)
        self._update_title()
        self.statusBar().showMessage(self.tr("{0} geladen ({1} Objekte)").format(path.name, len(doc)), 5000)
        return True

    def file_save(self) -> bool:
        if self.editor.file_path is None:
            return self.file_save_as()
        return self._save_to(self.editor.file_path)

    def file_save_as(self) -> bool:
        start = str(self.editor.file_path or Path(self.settings.value("last_dir", str(Path.home()))) / "neue_map.rsmap")
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Projekt speichern"), start, self.tr(FILE_FILTER))
        if not path:
            return False
        p = Path(path)
        if p.suffix.lower() != rsmap.FILE_SUFFIX:
            p = p.with_suffix(rsmap.FILE_SUFFIX)
        return self._save_to(p)

    def _save_to(self, path: Path) -> bool:
        for vp in self.grid_view.viewports():
            vp.store_camera()
        try:
            rsmap.save(self.editor.doc, path)
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, self.tr("Speichern fehlgeschlagen:\n{0}").format(exc))
            return False
        self.editor.file_path = path
        self.editor.stack.set_clean()
        self._remember(path)
        self._update_title()
        self.statusBar().showMessage(self.tr("Gespeichert: {0}").format(path), 5000)
        return True

    def _remember(self, path: Path) -> None:
        self.settings.setValue("last_dir", str(path.parent))
        recent = [p for p in self._recent() if p != str(path)]
        recent.insert(0, str(path))
        self.settings.setValue("recent", json.dumps(recent[:MAX_RECENT]))

    def _recent(self) -> list[str]:
        try:
            return list(json.loads(self.settings.value("recent", "[]")))
        except (TypeError, ValueError):
            return []

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        recent = self._recent()
        if not recent:
            a = self.recent_menu.addAction(self.tr("(keine)"))
            a.setEnabled(False)
        for p in recent:
            self.recent_menu.addAction(p, lambda p=p: self._confirm_discard() and self.open_path(Path(p)))

    # ---- Bearbeiten -------------------------------------------------------------------
    def edit_copy(self) -> None:
        objs = self.editor.selected_objects()
        out: list[MapObject] = list(objs)
        for o in objs:
            if isinstance(o, Entity):
                out += self.editor.doc.children(o.id)
        self._clipboard = out

    def edit_cut(self) -> None:
        self.edit_copy()
        self.editor.delete_selection()

    def edit_paste(self) -> None:
        if not self._clipboard:
            return
        doc = self.editor.doc
        id_map: dict[int, int] = {}
        new: list[MapObject] = []
        roots: list[int] = []
        for o in self._clipboard:
            id_map[o.id] = doc.new_id()
        for o in self._clipboard:
            if isinstance(o, Entity):
                new.append(o.replace(id=id_map[o.id], vmf_id=None))
                roots.append(id_map[o.id])
            else:
                parent = id_map.get(o.parent_id) if o.parent_id is not None else None
                new.append(o.replace(id=id_map[o.id], parent_id=parent, vmf_id=None))
                if parent is None:
                    roots.append(id_map[o.id])
        self.editor.run(AddObjects(new, self.tr("Einfügen")))
        self.editor.set_selection(roots)

    def edit_transform(self) -> None:
        if not self.editor.selection:
            self.statusBar().showMessage(self.tr("Erst etwas auswählen"), 3000)
            return
        dlg = TransformDialog(self.editor, self)
        if dlg.exec():
            dlg.apply()

    def _flip(self, which: int) -> None:
        vp = self.active_viewport()
        if vp is None or vp.is_3d:
            # ohne aktive 2D-Ansicht: horizontal = X, vertikal = Z
            axis = 0 if which == 0 else 2
        else:
            axis = vp.axes()[which]
        self.editor.mirror_selection(axis)

    # ---- Ansicht -----------------------------------------------------------------------
    def center_on_selection(self) -> None:
        bb = self.editor.selection_bbox() or self.editor.doc.bbox()
        if bb is None:
            return
        size = max(bb.size)
        for vp in self.grid_view.viewports():
            vp.center_on(bb.center, max(size, 64))

    def reset_layout(self) -> None:
        self.grid_view.reset()
        for dock in (self.tool_dock, self.sel_dock):
            dock.setFloating(False)
            dock.show()
            self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def set_expert(self, on: bool) -> None:
        self.editor.doc.editor.expert_mode = on
        self.statusBar().showMessage(
            self.tr("Experten-Modus aktiv") if on else self.tr("Einfach-Modus aktiv"), 3000)

    def show_controls(self) -> None:
        QMessageBox.information(self, self.tr("Steuerung"), self.tr(CONTROLS_HELP))

    def show_about(self) -> None:
        QMessageBox.about(self, APP_NAME, self.tr(
            "<b>Rampenschmiede {0}</b><br>Map-Editor für Surf-, Bhop- und Trick-Maps<br>"
            "für Counter-Strike: Source und Momentum Mod."
        ).format(__version__))

    # ---- Fenster -------------------------------------------------------------------------
    def _restore_window(self) -> None:
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1600, 960)
        state = self.settings.value("window_state")
        if state is not None:
            self.restoreState(state)
        self.resizeDocks([self.tool_dock, self.sel_dock], [DOCK_MIN_WIDTH, DOCK_MIN_WIDTH], Qt.Horizontal)
        try:
            self.grid_view.restore_state(json.loads(self.settings.value("viewports", "{}")))
        except (TypeError, ValueError):
            pass

    def closeEvent(self, e: QCloseEvent) -> None:
        if not self._confirm_discard():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())
        self.settings.setValue("viewports", json.dumps(self.grid_view.save_state()))
        e.accept()
