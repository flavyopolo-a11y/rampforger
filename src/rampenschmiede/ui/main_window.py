"""Hauptfenster: Menüs, Werkzeugleiste, Ansichten, Panels, Datei-Operationen."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
)

from .. import __version__
from ..core.blocks import clone_objects
from ..core.commands import AddObjects, Command, MacroCommand
from ..core.compile import CompileSettings, Level, LogLine
from ..core.cutting import carve_with
from ..core.io import rsmap, vmf
from ..core.materials import MaterialLibrary
from ..core.materials.authoring import import_image, ramp_material, wall_material
from ..core.materials.styles import WorldStyle, pick_sky, pick_wall, style_command
from ..core.materials.theme import SetTheme, Theme, apply_collision, apply_theme, get_theme
from ..core.model import Entity, MapDocument, MapObject
from ..core.profiles import ProfileStore, detect_profiles
from ..core.templates import SurfMapSettings, enclose_map, new_surf_map, starter_room
from ..core.validation.seal import describe as describe_seal
from ..core.zones import collect_zones, momentum_zones, zone_problems
from .compile_controller import CompileController, load_pointfile
from .dialogs.compile_dialog import CompileDialog
from .dialogs.profiles_dialog import ProfilesDialog
from .dialogs.ramp_assistant import (
    PRESETS,
    AssistantChoice,
    RampAssistant,
    from_hex,
    side_color,
    to_hex,
)
from .dialogs.surf_wizard import SurfWizard
from .dialogs.texture_packs import TexturePacksDialog
from .dialogs.transform_dialog import TransformDialog
from .dialogs.world_styles import WorldStylesDialog
from .editor import EditorContext
from .icons import ACTIVE, icon, pixmap
from .panels.compile_log import CompileLogPanel
from .panels.library_panel import LibraryPanel
from .panels.material_browser import MaterialBrowser
from .panels.selection_panel import SelectionPanel
from .panels.tool_options import ToolOptionsPanel
from .paths import profiles_file, textures_dir
from .seal_watcher import SealWatcher
from .tools.clip_tool import ClipTool, HoleTool
from .tools.entity_tool import EntityTool
from .tools.face_tool import FaceTool
from .tools.paint_tool import PaintTool
from .tools.select_tool import SelectTool
from .tools.shape_tool import ShapeTool
from .viewports.layout import ViewportGrid

APP_NAME = "Rampenschmiede"
#: Reihenfolge der Werkzeuge links (wie oft man sie braucht)
TOOL_ORDER = ("select", "paint", "shape", "entity", "face", "clip", "hole")
#: Werkzeugleiste links: aktives Werkzeug orange hinterlegt, wie in Hammer eingedrückt
TOOLBAR_STYLE = """
QToolButton { min-width: 58px; padding: 4px 2px; border: 1px solid transparent; border-radius: 5px; }
QToolButton:hover { background: rgba(255, 255, 255, 0.08); }
QToolButton:checked { background: rgba(255, 140, 40, 0.25); border: 1px solid #ff8c28; color: #ffb070; }
"""
FILE_FILTER = "Rampenschmiede-Projekt (*.rsmap)"
OPEN_FILTER = "Maps (*.rsmap *.vmf);;Rampenschmiede-Projekt (*.rsmap);;Hammer-Map (*.vmf)"
VMF_FILTER = "Hammer-Map (*.vmf)"
MAX_RECENT = 8
#: Steigt, wenn neue Panels dazukommen: Alte gespeicherte Anordnungen werden dann verworfen
LAYOUT_VERSION = 2
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
<h3>Bibliothek</h3>
<table>
<tr><td>Doppelklick oder Ziehen in eine Ansicht</td><td>Vorlage oder Prefab einfügen</td></tr>
<tr><td>Klick auf einen Baustein</td><td>Regler im Panel „Bibliothek“ ändern, sofort neu gebaut</td></tr>
<tr><td>Strg+Shift+N</td><td>Assistent „Neue Surf-Map“</td></tr>
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
        for tool in (SelectTool(self.editor), ShapeTool(self.editor), EntityTool(self.editor), FaceTool(self.editor),
                     ClipTool(self.editor), HoleTool(self.editor)):
            self.editor.register_tool(tool)
        self._clipboard: list[MapObject] = []
        self.settings = QSettings("Rampenschmiede", "Rampenschmiede")
        self.profiles = self._load_profiles()
        self.compile_settings = self._load_compile_settings()
        self.compiler = CompileController(self.editor, self)
        self.seal = SealWatcher(self.editor, self)
        self._reload_materials()

        self.grid_view = ViewportGrid(self.editor)
        self.setCentralWidget(self.grid_view)
        self._build_docks()
        self._build_actions()
        self._set_icons()
        self.material_browser.add_actions([self.act_ramp_assistant, self.act_world_style, None, self.act_import_texture,
                                           self.act_texture_packs])
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
        ed.document_changed.connect(self._sync_ramp_clip)
        ed.document_replaced.connect(self._sync_ramp_clip)
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
        self.lib_dock = QDockWidget(self.tr("Bibliothek"), self)
        self.lib_dock.setObjectName("dock_library")
        self.library = LibraryPanel(self.editor, self._insert_point)
        self.lib_dock.setWidget(self.library)
        self.editor.register_tool(PaintTool(self.editor, self.library))
        self.addDockWidget(Qt.LeftDockWidgetArea, self.lib_dock)
        # Ohne Mindestbreite drücken die Ansichten die Panels auf wenige Pixel zusammen.
        for dock in (self.tool_dock, self.sel_dock, self.lib_dock):
            dock.widget().setMinimumWidth(DOCK_MIN_WIDTH)
        self.log_dock = QDockWidget(self.tr("Kompilieren"), self)
        self.log_dock.setObjectName("dock_compile_log")
        self.compile_log = CompileLogPanel(self.compiler, self._center_views_on)
        self.log_dock.setWidget(self.compile_log)
        self.mat_dock = QDockWidget(self.tr("Materialien"), self)
        self.mat_dock.setObjectName("dock_materials")
        self.material_browser = MaterialBrowser(self.editor)
        self.mat_dock.setWidget(self.material_browser)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.mat_dock)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
        self.tabifyDockWidget(self.mat_dock, self.log_dock)
        self.log_dock.hide()
        self.mat_dock.raise_()

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
        self.act_surf_wizard = self._action("Neue S&urf-Map (Assistent) …", self.surf_wizard, "Ctrl+Shift+N",
                                            "Spielbare Surf-Map aus Stages, Rampen und Teleportern erzeugen")
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
        self.act_carve = self._action("Mit Auswahl a&ushöhlen", self.carve_selection, "Ctrl+Shift+C",
                                      "Die ausgewählten Brushes schneiden sich aus allen anderen Brushes heraus "
                                      "(Carve wie in Hammer)")
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
        order = [n for n in TOOL_ORDER if n in ed.tools] + [n for n in ed.tools if n not in TOOL_ORDER]
        for name, tool in ((n, ed.tools[n]) for n in order):
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

        self.act_ramp_assistant = self._action("&Rampen-Assistent …", self.ramp_assistant, "Ctrl+Shift+R",
                                               "Farben für Rampen, Linien und Wände wählen, den Rest macht die "
                                               "Rampenschmiede")
        self.act_world_style = self._action("&Welt-Stil …", self.world_style, None,
                                            "Himmel, Sonne, Nebel, Wände und Rampenfarben mit einem Klick")
        self.act_ramp_clip = self._action("&Playerclip auf Rampen", self.set_ramp_clip, None,
                                          "Glatte Playerclip-Hülle auf allen Rampen (empfohlen). Aus: Die Rampe "
                                          "selbst ist die Kollision.", checkable=True)
        self.act_import_texture = self._action("Bild als Textur &importieren …", self.import_texture, None,
                                               "PNG, JPG, TGA oder BMP als eigenes Material übernehmen")
        self.act_texture_packs = self._action("Textur&pakete …", self.edit_texture_packs, None,
                                              "Eigene Ordner mit Materialien einbinden")

        self.act_controls = self._action("&Steuerung", self.show_controls, "F1")
        self.act_about = self._action("Ü&ber Rampenschmiede", self.show_about)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m = mb.addMenu(self.tr("&Datei"))
        for a in (self.act_new, self.act_new_empty, self.act_surf_wizard, self.act_starter, self.act_open):
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
                  None, self.act_select_all, None, self.act_carve, None, self.act_transform, self.act_flip_h, self.act_flip_v):
            m.addSeparator() if a is None else m.addAction(a)

        m = mb.addMenu(self.tr("&Ansicht"))
        for a in (self.act_grid_finer, self.act_grid_coarser, None, self.act_center, None, self.act_hide,
                  self.act_hide_others, self.act_unhide, None, self.act_expert, self.act_reset_layout):
            m.addSeparator() if a is None else m.addAction(a)
        m.addSeparator()
        m.addAction(self.tool_dock.toggleViewAction())
        m.addAction(self.sel_dock.toggleViewAction())
        m.addAction(self.lib_dock.toggleViewAction())
        m.addAction(self.mat_dock.toggleViewAction())

        m = mb.addMenu(self.tr("&Werkzeuge"))
        for a in self.tool_actions.values():
            m.addAction(a)

        m = mb.addMenu(self.tr("Te&xturen"))
        for a in (self.act_ramp_assistant, self.act_world_style, self.act_ramp_clip, None, self.act_import_texture,
                  self.act_texture_packs):
            m.addSeparator() if a is None else m.addAction(a)

        m = mb.addMenu(self.tr("&Testen"))
        for a in (self.act_compile, self.act_compile_again, self.act_compile_cancel, None,
                  self.act_check_seal, self.act_enclose, None,
                  self.act_load_pointfile, self.act_clear_leak, None, self.act_profiles):
            m.addSeparator() if a is None else m.addAction(a)
        m.addAction(self.log_dock.toggleViewAction())

        m = mb.addMenu(self.tr("&Hilfe"))
        m.addAction(self.act_controls)
        m.addAction(self.act_about)

    def _set_icons(self) -> None:
        for action, name in ((self.act_new, "new"), (self.act_open, "open"), (self.act_save, "save"),
                             (self.act_undo, "undo"), (self.act_redo, "redo"),
                             (self.act_grid_finer, "grid_finer"), (self.act_grid_coarser, "grid_coarser"),
                             (self.act_compile, "compile"), (self.act_expert, "expert"),
                             (self.act_ramp_assistant, "palette"), (self.act_carve, "carve"), (self.act_world_style, "sun")):
            action.setIcon(icon(name))
        for name, action in self.tool_actions.items():
            action.setIcon(icon(name))

    def _build_toolbars(self) -> None:
        tb = QToolBar(self.tr("Datei"))
        tb.setObjectName("tb_file")
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(20, 20))
        for a in (self.act_new, self.act_open, self.act_save, None, self.act_undo, self.act_redo, None,
                  self.act_grid_finer, self.act_grid_coarser, None, self.act_compile, None, self.act_expert):
            tb.addSeparator() if a is None else tb.addAction(a)
        for a in (self.act_grid_finer, self.act_grid_coarser):
            tb.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonIconOnly)
        # Rechts oben: welches Werkzeug gerade aktiv ist
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        self.mode_icon = QLabel()
        self.mode_label = QLabel()
        self.mode_label.setObjectName("modeLabel")
        self.mode_label.setStyleSheet("#modeLabel { color: #ff8c28; font-weight: bold; padding-right: 8px; }")
        tb.addWidget(self.mode_icon)
        tb.addWidget(self.mode_label)
        self.addToolBar(Qt.TopToolBarArea, tb)
        tools = QToolBar(self.tr("Werkzeuge"))
        tools.setObjectName("tb_tools")
        tools.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tools.setIconSize(QSize(28, 28))
        tools.setStyleSheet(TOOLBAR_STYLE)
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
        tool = self.editor.tools.get(name)
        if tool is None:
            return
        self.mode_icon.setPixmap(pixmap(name, 20, ACTIVE))
        self.mode_label.setText(self.tr("Werkzeug: {0}").format(self.tr(tool.label)))
        self.mode_label.setToolTip(self.tr(tool.hint))
        self.statusBar().showMessage(self.tr(tool.hint), 6000)

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

    def surf_wizard(self) -> None:
        profile = self.profiles.active_profile()
        dlg = SurfWizard(profile.key if profile else None, self)
        if dlg.exec() and self._confirm_discard():
            self.new_surf_map(dlg.settings())

    def new_surf_map(self, settings: SurfMapSettings) -> bool:
        doc = MapDocument()
        try:
            objs = new_surf_map(doc, settings)
        except ValueError as exc:
            QMessageBox.warning(self, self.tr("Neue Surf-Map"), str(exc))
            return False
        doc._insert(objs)
        spawn = next((o.origin for o in objs if isinstance(o, Entity) and o.classname.startswith("info_player")
                      and o.origin), None)
        if spawn is not None:
            # Hinter dem Spawn, Blick die Strecke entlang
            doc.editor.camera_position = (spawn[0] - 256, spawn[1], spawn[2] + 160)
            doc.editor.camera_angles = (0.0, -12.0)
        self.editor.set_document(doc, None)
        self._update_title()
        QTimer.singleShot(0, self._center_2d_on_map)
        self.statusBar().showMessage(self.tr("Surf-Map erzeugt: F9 zum Testen"), 5000)
        return True

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
        self._clipboard = objs + self.editor.doc.attached(o.id for o in objs)

    def edit_cut(self) -> None:
        self.edit_copy()
        self.editor.delete_selection()

    def edit_paste(self) -> None:
        if not self._clipboard:
            return
        new, roots = clone_objects(self.editor.doc, self._clipboard)
        self.editor.run(AddObjects(new, self.tr("Einfügen")))
        self.editor.set_selection(roots)

    def carve_selection(self) -> bool:
        if not self.editor.selection:
            self.editor.status_message.emit(self.tr("Erst die Brushes auswählen, die herausgeschnitten werden sollen"))
            return False
        cmd, ids = carve_with(self.editor.doc, self.editor.selection)
        if cmd is None:
            self.editor.status_message.emit(self.tr("Die Auswahl durchdringt keine anderen Brushes"))
            return False
        self.editor.run(cmd)
        self.editor.status_message.emit(self.tr("Ausgehöhlt: {0} Brushes").format(len(ids)))
        return True

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
        self._reload_materials()

    def texture_packs(self) -> list[str]:
        """Eigene Texturpakete: Ordner mit materials/ darin, wie ein Spielordner."""
        try:
            packs = json.loads(self.settings.value("texture_packs", "[]"))
        except (TypeError, ValueError):
            packs = []
        return [str(p) for p in packs if isinstance(p, str)]

    def set_texture_packs(self, packs: list[str]) -> None:
        self.settings.setValue("texture_packs", json.dumps(packs))
        self._reload_materials()

    def _reload_materials(self) -> None:
        profile = self.profiles.active_profile()
        folders = [textures_dir(), *self.texture_packs()]
        self.editor.set_material_library(MaterialLibrary.for_game(profile.game_dir if profile else None, folders))

    # ---- Texturen ---------------------------------------------------------------
    def ramp_assistant(self) -> bool:
        theme = get_theme(self.editor.doc)
        c = theme.colors or {}
        _, ramp, lines, wall = PRESETS[0]
        start = AssistantChoice(from_hex(c.get("ramp", ""), ramp), from_hex(c.get("lines", ""), lines),
                                from_hex(c.get("wall", ""), wall), clip=theme.collision == "clip")
        dlg = RampAssistant(start, bool(self.editor.selection), self)
        if dlg.exec() != QDialog.Accepted:
            return False
        return self.apply_ramp_colors(dlg.choice())

    def apply_ramp_colors(self, choice: AssistantChoice) -> bool:
        """Texturen aus den Farben erzeugen und die Map (oder die Auswahl) umfärben."""
        root = textures_dir()
        try:
            ramp = ramp_material(root, choice.ramp, choice.lines).upper()
            side = wall_material(root, side_color(choice.ramp)).upper()
            wall = wall_material(root, choice.wall).upper() if choice.walls else ""
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, self.tr("Texturen konnten nicht gespeichert werden:\n{0}").format(exc))
            return False
        old = get_theme(self.editor.doc)
        colors = {"ramp": to_hex(choice.ramp), "lines": to_hex(choice.lines), "wall": to_hex(choice.wall)}
        applied = Theme(ramp, side, wall, "clip" if choice.clip else "detail", colors)
        ids = sorted(self.editor.selection) if choice.only_selection else None
        cmds: list[Command] = []
        if choice.remember:
            cmds.append(SetTheme(Theme(ramp, side, wall or old.wall, applied.collision, colors), "Rampenfarben"))
        cmd = apply_theme(self.editor.doc, applied, ids)
        if cmd is not None:
            cmds.append(cmd)
        self.editor.refresh_materials()
        if cmds:
            self.editor.run(MacroCommand(cmds, self.tr("Rampenfarben")))
        self.library.refresh()
        self.editor.set_current_material(ramp)
        self.editor.status_message.emit(self.tr("Rampenfarben angewendet"))
        return True

    def world_style(self) -> bool:
        dlg = WorldStylesDialog(get_theme(self.editor.doc).collision == "clip", self)
        if dlg.exec() != QDialog.Accepted:
            return False
        return self.apply_world_style(dlg.chosen(), dlg.clip.isChecked())

    def apply_world_style(self, style: WorldStyle, clip: bool = True) -> bool:
        lib = self.editor.materials
        root = textures_dir()
        try:
            ramp = ramp_material(root, style.ramp, style.lines).upper()
            side = wall_material(root, side_color(style.ramp)).upper()
            wall = (pick_wall(style, lib) or wall_material(root, style.wall)).upper()
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, self.tr("Texturen konnten nicht gespeichert werden:\n{0}").format(exc))
            return False
        colors = {"ramp": to_hex(style.ramp), "lines": to_hex(style.lines), "wall": to_hex(style.wall)}
        theme = Theme(ramp, side, wall, "clip" if clip else "detail", colors)
        self.editor.refresh_materials()
        self.editor.run(style_command(self.editor.doc, style, pick_sky(style, lib), theme))
        self.library.refresh()
        self.editor.status_message.emit(self.tr("Welt-Stil „{0}“ angewendet").format(self.tr(style.name)))
        return True

    def set_ramp_clip(self, on: bool) -> None:
        if (get_theme(self.editor.doc).collision == "clip") == on:
            return
        self.editor.run(apply_collision(self.editor.doc, "clip" if on else "detail"))
        self.library.refresh()
        self.editor.status_message.emit(
            self.tr("Playerclip auf Rampen an") if on else self.tr("Playerclip auf Rampen aus"))

    def _sync_ramp_clip(self) -> None:
        on = get_theme(self.editor.doc).collision == "clip"
        if self.act_ramp_clip.isChecked() != on:
            self.act_ramp_clip.setChecked(on)

    def import_texture(self, paths: list[str] | None = None) -> list[str]:
        if not paths:
            paths, _ = QFileDialog.getOpenFileNames(
                self, self.tr("Bild als Textur importieren"), "",
                self.tr("Bilder (*.png *.jpg *.jpeg *.tga *.bmp);;Alle Dateien (*)"))
        names: list[str] = []
        for path in paths:
            try:
                names.append(import_image(textures_dir(), path))
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, APP_NAME, self.tr("„{0}“ ließ sich nicht importieren:\n{1}").format(path, exc))
        if names:
            self.editor.refresh_materials()
            self.editor.set_current_material(names[-1])
            self.editor.status_message.emit(self.tr("{0} Textur(en) importiert, sie stehen unter „Eigene“").format(len(names)))
        return names

    def edit_texture_packs(self) -> bool:
        dlg = TexturePacksDialog(self.texture_packs(), self)
        if dlg.exec() != QDialog.Accepted:
            return False
        self.set_texture_packs(dlg.packs())
        return True

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
        zones = collect_zones(self.editor.doc)
        for problem in zone_problems(zones):
            warnings.append(LogLine(self.tr("Zonen: {0}").format(problem), Level.WARNING))
        if zones and profile.key == "momentum" and momentum_zones(zones) is None:
            warnings.append(LogLine(self.tr(
                "Zonen: Ohne Start- und Zielzone der Hauptstrecke wird keine Momentum-Zonendatei geschrieben."),
                Level.WARNING))
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

    def _insert_point(self) -> tuple[float, float, float]:
        """Wohin „Einfügen“ aus der Bibliothek setzt: Mitte der Ansicht von oben, Höhe 0."""
        for vp in self.grid_view.viewports():
            if vp.view == "top":
                return (vp.cam2d.center_h, vp.cam2d.center_v, 0.0)
        return (0.0, 0.0, 0.0)

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
        self.lib_dock.setFloating(False)
        self.lib_dock.show()
        self.addDockWidget(Qt.LeftDockWidgetArea, self.lib_dock)
        self.mat_dock.setFloating(False)
        self.mat_dock.show()
        self.addDockWidget(Qt.BottomDockWidgetArea, self.mat_dock)

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
        restored = state is not None and self.restoreState(state, LAYOUT_VERSION)
        self.resizeDocks([self.tool_dock, self.sel_dock, self.lib_dock], [DOCK_MIN_WIDTH] * 3, Qt.Horizontal)
        if not restored:
            self.resizeDocks([self.mat_dock], [260], Qt.Vertical)
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
        self.settings.setValue("window_state", self.saveState(LAYOUT_VERSION))
        self.settings.setValue("viewports", json.dumps(self.grid_view.save_state()))
        e.accept()
