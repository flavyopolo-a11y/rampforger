"""Hauptfenster: Menüs, Werkzeugleiste, Ansichten, Panels, Datei-Operationen."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolBar,
    QToolButton,
)

from .. import __version__
from ..core.commands import AddObjects
from ..core.compile import CompileSettings, Level, LogLine
from ..core.io import rsmap, vmf
from ..core.model import Entity, MapDocument, MapObject
from ..core.profiles import ProfileStore, detect_profiles
from ..core.templates import enclose_map, starter_room
from ..core.validation.seal import describe as describe_seal
from .compile_controller import CompileController, load_pointfile
from .dialogs.compile_dialog import CompileDialog
from .dialogs.profiles_dialog import ProfilesDialog
from .dialogs.transform_dialog import TransformDialog
from .editor import EditorContext
from .panels.compile_log import CompileLogPanel
from .panels.selection_panel import SelectionPanel
from .panels.tool_options import ToolOptionsPanel
from .paths import profiles_file
from .seal_watcher import SealWatcher
from .tools.entity_tool import EntityTool
from .tools.select_tool import SelectTool
from .tools.shape_tool import ShapeTool
from .viewports.layout import ViewportGrid

APP_NAME = "Rampenschmiede"
FILE_FILTER = "Rampenschmiede-Projekt (*.rsmap)"
OPEN_FILTER = "Maps (*.rsmap *.vmf);;Rampenschmiede-Projekt (*.rsmap);;Hammer-Map (*.vmf)"
VMF_FILTER = "Hammer-Map (*.vmf)"
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
<h3>Testen</h3>
<table>
<tr><td>F9</td><td>Kompilieren und testen (Dialog)</td></tr>
<tr><td>Strg+F9</td><td>Sofort mit den letzten Einstellungen kompilieren</td></tr>
<tr><td>Klick auf eine rote Log-Zeile</td><td>springt zum betroffenen Objekt</td></tr>
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
        self.profiles = self._load_profiles()
        self.compile_settings = self._load_compile_settings()
        self.compiler = CompileController(self.editor, self)
        self.seal = SealWatcher(self.editor, self)

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
        self.compiler.started.connect(self._on_compile_started)
        self.compiler.finished.connect(self._on_compile_finished)

        ed.set_tool("select")
        self._restore_window()
        self.seal.checked.connect(self._on_seal_checked)
        self._new_document()
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
        self.log_dock = QDockWidget(self.tr("Kompilieren"), self)
        self.log_dock.setObjectName("dock_compile_log")
        self.compile_log = CompileLogPanel(self.compiler, self._center_views_on)
        self.log_dock.setWidget(self.compile_log)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()

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
        self.act_new = self._action("&Neu", self.file_new, QKeySequence.New,
                                    "Neue Map, auf Wunsch mit Startraum (Spawn in dichter Skybox)")
        self.act_new_empty = self._action("Neu (&leer)", lambda: self.file_new(empty=True), "Ctrl+Alt+N",
                                          "Neue Map ganz ohne Inhalt")
        self.act_starter = self._action("Neue Maps mit &Startraum", self._toggle_starter, None,
                                        "Neue Maps beginnen mit Spawn, Sonne und dichter Skybox-Hülle. "
                                        "So lässt sich sofort ohne Leck kompilieren.", checkable=True)
        self.act_starter.setChecked(self._starter_enabled())
        self.act_starter.toggled.connect(self._toggle_starter)  # auch wenn per Code umgeschaltet
        self.act_open = self._action("Ö&ffnen …", self.file_open, QKeySequence.Open, "Projekt öffnen")
        self.act_save = self._action("&Speichern", self.file_save, QKeySequence.Save, "Projekt speichern")
        self.act_save_as = self._action("Speichern &unter …", self.file_save_as, "Ctrl+Shift+S")
        self.act_import_vmf = self._action("VMF &importieren …", self.file_import_vmf, None,
                                           "Hammer-Map (.vmf) öffnen")
        self.act_export_vmf = self._action("Als VMF e&xportieren …", self.file_export_vmf, "Ctrl+Shift+E",
                                           "Map als .vmf für Hammer oder andere Werkzeuge speichern")
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

        self.act_compile = self._action("&Kompilieren und testen …", self.compile_dialog, "F9",
                                        "Map bauen, ins Spiel kopieren und starten")
        self.act_compile_again = self._action("&Sofort kompilieren", self.compile_again, "Ctrl+F9",
                                              "Mit den letzten Einstellungen kompilieren, ohne Dialog")
        self.act_compile_cancel = self._action("Kompilieren a&bbrechen", self.compiler.cancel)
        self.act_compile_cancel.setEnabled(False)
        self.act_profiles = self._action("S&pielprofile …", self.edit_profiles, None,
                                         "Spiele, Compiler und Startparameter einrichten")
        self.act_load_pointfile = self._action("Leck-Spur &laden …", self.open_pointfile, None,
                                               "Eine .lin-Datei von vbsp anzeigen")
        self.act_clear_leak = self._action("Leck-Spur &ausblenden", lambda: self.editor.set_leak_path([]))
        self.act_check_seal = self._action("&Dichtheit prüfen", self.show_seal_problem, None,
                                           "Prüft ohne Kompilieren, ob alle Entities umschlossen sind")
        self.act_enclose = self._action("Map mit Skybox &umhüllen", self.enclose_with_skybox, None,
                                        "Legt eine dichte Skybox-Hülle um alles, was in der Map ist")

        self.act_controls = self._action("&Steuerung", self.show_controls, "F1")
        self.act_about = self._action("Ü&ber Rampenschmiede", self.show_about)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu(self.tr("&Datei"))
        for a in (self.act_new, self.act_new_empty, self.act_starter, self.act_open):
            m.addAction(a)
        self.recent_menu = m.addMenu(self.tr("&Zuletzt geöffnet"))
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        for a in (self.act_save, self.act_save_as, None, self.act_import_vmf, self.act_export_vmf):
            m.addSeparator() if a is None else m.addAction(a)
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

        m = mb.addMenu(self.tr("&Testen"))
        for a in (self.act_compile, self.act_compile_again, self.act_compile_cancel, None,
                  self.act_check_seal, self.act_enclose, None,
                  self.act_load_pointfile, self.act_clear_leak, None, self.act_profiles):
            m.addSeparator() if a is None else m.addAction(a)
        m.addAction(self.log_dock.toggleViewAction())

        m = mb.addMenu(self.tr("&Hilfe"))
        m.addAction(self.act_controls)
        m.addAction(self.act_about)

    def _build_toolbars(self) -> None:
        tb = QToolBar(self.tr("Datei"))
        tb.setObjectName("tb_file")
        for a in (self.act_new, self.act_open, self.act_save, None, self.act_undo, self.act_redo, None,
                  self.act_grid_finer, self.act_grid_coarser, None, self.act_compile, None, self.act_expert):
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
        self.profile_label = QLabel()
        self.seal_button = QToolButton()
        self.seal_button.setAutoRaise(True)
        self.seal_button.clicked.connect(self.show_seal_problem)
        sb.addPermanentWidget(self.seal_button)
        sb.addPermanentWidget(self.sel_label)
        sb.addPermanentWidget(self.profile_label)
        sb.addPermanentWidget(self.grid_label)
        self._update_profile_label()

    # ---- Zustand ------------------------------------------------------------------
    def _update_title(self) -> None:
        ed = self.editor
        if ed.file_path:
            name = ed.file_path.name
        elif ed.import_path:
            name = self.tr("{0} (importiert)").format(ed.import_path.name)
        else:
            name = self.tr("Unbenannt")
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

    def file_new(self, empty: bool = False) -> None:
        if self._confirm_discard():
            self._new_document(empty)

    def _starter_enabled(self) -> bool:
        return str(self.settings.value("new_map_starter", "true")).lower() in ("true", "1")

    def _toggle_starter(self, on: bool) -> None:
        self.settings.setValue("new_map_starter", "true" if on else "false")

    def _new_document(self, empty: bool = False) -> None:
        doc = MapDocument()
        if not empty and self._starter_enabled():
            profile = self.profiles.active_profile()
            doc._insert(starter_room(doc, profile.key if profile else None))
            # 3D-Kamera steht im Raum hinter den Spawns, nicht draußen vor der Skybox
            doc.editor.camera_position = (-440.0, -440.0, 220.0)
            doc.editor.camera_angles = (45.0, -15.0)
        self.editor.set_document(doc, None)
        self._update_title()
        if len(doc):
            # erst nach dem Layout zentrieren, vorher sind die Ansichten noch winzig
            QTimer.singleShot(0, self._center_2d_on_map)

    def _center_2d_on_map(self) -> None:
        bb = self.editor.doc.bbox()
        if bb is None:
            return
        for vp in self.grid_view.viewports():
            if not vp.is_3d:
                vp.center_on(bb.center, max(max(bb.size), 64))

    # ---- Dichtheit ------------------------------------------------------------------
    def _on_seal_checked(self, result) -> None:
        text = describe_seal(self.editor.doc, result)
        if result.unknown:
            color, mark = "#9aa4b2", "·"
        elif result.sealed:
            color, mark = "#7fd67f", "✓"
        else:
            color, mark = "#f0c85a", "⚠"
        self.seal_button.setText(f"{mark} {text}")
        self.seal_button.setStyleSheet(f"color: {color};")
        self.seal_button.setToolTip(self.tr(
            "Vorhersage ohne Kompilieren. Klick zeigt den Weg ins Freie als rote Linie."
            if not result.sealed else "Alle Entities sind von Brushes umschlossen."))

    def show_seal_problem(self) -> None:
        result = self.seal.check_now()
        self._on_seal_checked(result)
        if result.sealed:
            self.statusBar().showMessage(self.tr(describe_seal(self.editor.doc, result)), 4000)
            return
        self.editor.set_leak_path(result.path)
        if result.entity_id is not None:
            self.editor.set_selection([result.entity_id])
        if result.path:
            self._center_views_on(result.path[0], 512)
        self.statusBar().showMessage(self.tr(
            "{0}. Rote Linie zeigt den Weg ins Freie. Tipp: Testen → Map mit Skybox umhüllen."
        ).format(describe_seal(self.editor.doc, result)), 8000)

    def enclose_with_skybox(self) -> None:
        hull = enclose_map(self.editor.doc)
        self.editor.run(AddObjects(hull, self.tr("Map umhüllen")))
        self.editor.set_leak_path([])
        self.editor.set_selection([s.id for s in hull])

    def file_open(self) -> None:
        if not self._confirm_discard():
            return
        start = self.settings.value("last_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Map öffnen"), start, self.tr(OPEN_FILTER))
        if path:
            self.open_path(Path(path))

    def file_import_vmf(self) -> None:
        if not self._confirm_discard():
            return
        start = self.settings.value("last_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, self.tr("VMF importieren"), start, self.tr(VMF_FILTER))
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path) -> bool:
        path = path.absolute()
        if path.suffix.lower() == ".vmf":
            return self._import_vmf(path)
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

    def _import_vmf(self, path: Path) -> bool:
        try:
            doc, report = vmf.load_vmf(path)
        except (OSError, vmf.VmfError, ValueError) as exc:
            QMessageBox.critical(self, APP_NAME, self.tr("VMF konnte nicht importiert werden:\n{0}").format(exc))
            return False
        self.editor.set_document(doc, None, import_path=path)
        self._remember(path)
        self._update_title()
        msg = self.tr("{0} importiert: {1} Brushes, {2} Entities").format(path.name, report.solids, report.entities)
        if report.warnings:
            msg += self.tr(" · {0} Warnungen").format(len(report.warnings))
        self.statusBar().showMessage(msg, 8000)
        self.center_on_selection()
        return True

    def file_export_vmf(self) -> bool:
        ed = self.editor
        source = ed.import_path or (ed.file_path.with_suffix(".vmf") if ed.file_path else None)
        start = str(source or Path(self.settings.value("last_dir", str(Path.home()))) / "neue_map.vmf")
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Als VMF exportieren"), start, self.tr(VMF_FILTER))
        if not path:
            return False
        p = Path(path)
        if p.suffix.lower() != ".vmf":
            p = p.with_suffix(".vmf")
        try:
            result = vmf.save_vmf(ed.doc, p)
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, self.tr("Export fehlgeschlagen:\n{0}").format(exc))
            return False
        self.settings.setValue("last_dir", str(p.parent))
        self.statusBar().showMessage(self.tr("Exportiert: {0} ({1} Brushes)").format(p, len(result.solid_ids)), 5000)
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

    # ---- Testen --------------------------------------------------------------------------
    def _load_profiles(self) -> ProfileStore:
        store = ProfileStore.load(profiles_file())
        if not store.profiles:
            try:
                if store.merge_detected(detect_profiles()):
                    store.save(profiles_file())
            except OSError:
                pass
        return store

    def _save_profiles(self) -> None:
        try:
            self.profiles.save(profiles_file())
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, self.tr("Spielprofile konnten nicht gespeichert werden:\n{0}").format(exc))
        self._update_profile_label()

    def _update_profile_label(self) -> None:
        p = self.profiles.active_profile()
        if p is None:
            self.profile_label.setText(self.tr("Kein Spielprofil"))
        else:
            mark = "" if not p.problems() else " ⚠"
            self.profile_label.setText(f"{p.name}{mark}")

    def _load_compile_settings(self) -> CompileSettings:
        try:
            return CompileSettings.from_dict(json.loads(self.settings.value("compile_settings", "{}")))
        except (TypeError, ValueError):
            return CompileSettings()

    def edit_profiles(self) -> bool:
        dlg = ProfilesDialog(self.profiles, self)
        if dlg.exec():
            self.profiles = dlg.result_store()
            self._save_profiles()
            return True
        return False

    def compile_dialog(self) -> None:
        if self.compiler.running:
            self.statusBar().showMessage(self.tr("Es wird schon kompiliert"), 3000)
            return
        dlg = CompileDialog(self.profiles, self.compile_settings, self.compiler.prepare,
                            self.editor.doc.editor.expert_mode, self)

        def open_profiles() -> None:
            if self.edit_profiles():
                dlg.set_store(self.profiles)

        dlg.profiles_requested.connect(open_profiles)
        if dlg.exec():
            self.profiles = dlg.store
            self._save_profiles()
            self.compile_settings = dlg.settings
            self.settings.setValue("compile_settings", json.dumps(self.compile_settings.to_dict()))
            self.start_compile()

    def compile_again(self) -> None:
        if self.profiles.active_profile() is None:
            self.compile_dialog()
        else:
            self.start_compile()

    def start_compile(self) -> bool:
        profile = self.profiles.active_profile()
        if profile is None or self.compiler.running:
            return False
        seal = self.seal.check_now()
        warnings = []
        if not seal.sealed:
            warnings.append(LogLine(
                self.tr("Vorab-Prüfung: {0}. vbsp wird vermutlich ein Leck melden. "
                        "Tipp: Testen → Map mit Skybox umhüllen.").format(describe_seal(self.editor.doc, seal)),
                Level.WARNING, position=seal.path[0] if seal.path else None))
        started = self.compiler.start(profile, self.compile_settings, warnings)
        if started and not seal.sealed:
            self.editor.set_leak_path(seal.path)
        return started

    def _on_compile_started(self, _plan) -> None:
        self.log_dock.show()
        self.log_dock.raise_()
        self.act_compile_cancel.setEnabled(True)
        self.act_compile.setEnabled(False)
        self.act_compile_again.setEnabled(False)

    def _on_compile_finished(self, result) -> None:
        self.act_compile_cancel.setEnabled(False)
        self.act_compile.setEnabled(True)
        self.act_compile_again.setEnabled(True)
        if result.ok:
            self.statusBar().showMessage(self.tr("Kompilieren fertig ({0:.1f} s)").format(result.seconds), 5000)

    def open_pointfile(self) -> None:
        start = str(self.compiler.plan.pointfile_path) if self.compiler.plan else self.settings.value("last_dir", "")
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Leck-Spur laden"), start, "Pointfile (*.lin)")
        if path:
            try:
                n = load_pointfile(self.editor, Path(path))
            except OSError as exc:
                QMessageBox.critical(self, APP_NAME, str(exc))
                return
            self.statusBar().showMessage(self.tr("Leck-Spur mit {0} Punkten geladen").format(n), 5000)
            self.compile_log.go_to_leak()

    # ---- Ansicht -----------------------------------------------------------------------
    def _center_views_on(self, point, size: float) -> None:
        for vp in self.grid_view.viewports():
            vp.center_on(point, size)

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
        if self.compiler.running:
            self.compiler.cancel()
            self.compiler.wait(5)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("window_state", self.saveState())
        self.settings.setValue("viewports", json.dumps(self.grid_view.save_state()))
        e.accept()
