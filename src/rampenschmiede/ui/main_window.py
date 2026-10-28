"""Hauptfenster: Menüs, Werkzeugleiste, Ansichten, Panels, Datei-Operationen."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QProcess, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
    QWidgetAction,
)

from .. import __version__, i18n
from ..core import organize, search
from ..core.blocks import clone_objects, is_block_root, upgrade_roots
from ..core.commands import AddObjects, Command, MacroCommand, RemoveObjects
from ..core.compile import CompileSettings, Level, LogLine
from ..core.cutting import carve_with, hollow
from ..core.entities.io import unique_targetname
from ..core.geometry.transform import translate
from ..core.instances import INSTANCE
from ..core.io import bsp, rsmap, vmf
from ..core.materials import MaterialLibrary
from ..core.materials.authoring import import_image, ramp_material, wall_material
from ..core.materials.styles import WorldStyle, pick_sky, pick_wall, sky_command, style_command
from ..core.materials.theme import SetTheme, Theme, apply_collision, apply_theme, get_theme
from ..core.model import Entity, MapDocument, MapObject
from ..core.models.props import prop_problems
from ..core.profiles import ProfileStore, detect_profiles
from ..core.skybox3d import STYLE_BY_KEY as SKY3D_BY_KEY
from ..core.skybox3d import STYLES as SKY3D_STYLES
from ..core.skybox3d import pick_material, remove_command, skybox_command, skybox_ids
from ..core.templates import SurfMapSettings, enclose_map, new_surf_map, starter_room
from ..core.validation.problems import find_problems
from ..core.validation.seal import check_seal
from ..core.validation.seal import describe as describe_seal
from ..core.zones import collect_zones, momentum_zones, zone_problems
from ..i18n import N_
from .autosave import DEFAULT_MINUTES, Autosaver, backup_before_save, backups_dir, latest_autosave
from .compile_controller import CompileController, load_pointfile, load_portalfile
from .dialogs.compile_dialog import CompileDialog
from .dialogs.entity_report import EntityReport
from .dialogs.find_dialog import FindDialog
from .dialogs.free_assets import FreeAssetsDialog
from .dialogs.organize_dialogs import MultiCopyDialog, TieEntityDialog
from .dialogs.problems_dialog import ProblemsDialog
from .dialogs.profiles_dialog import ProfilesDialog
from .dialogs.ramp_assistant import (
    PRESETS,
    AssistantChoice,
    RampAssistant,
    from_hex,
    side_color,
    to_hex,
)
from .dialogs.sky_dialog import SkyDialog
from .dialogs.sound_browser import SoundBrowser
from .dialogs.stats_dialog import StatsDialog
from .dialogs.surf_wizard import SurfWizard
from .dialogs.texture_packs import TexturePacksDialog
from .dialogs.transform_dialog import TransformDialog
from .dialogs.world_styles import StyleGallery, WorldStylesDialog
from .editor import EditorContext
from .icons import ACTIVE, icon, pixmap
from .panels.compile_log import CompileLogPanel
from .panels.library_panel import LibraryPanel
from .panels.material_browser import MaterialBrowser
from .panels.model_browser import ModelBrowser
from .panels.scene_panel import ScenePanel
from .panels.selection_panel import SelectionPanel
from .panels.tool_options import ToolOptionsPanel
from .paths import bsp_textures_dir, profiles_file, textures_dir
from .seal_watcher import SealWatcher
from .tools.clip_tool import ClipTool, HoleTool
from .tools.cordon_tool import CordonTool
from .tools.entity_tool import EntityTool
from .tools.face_tool import FaceTool
from .tools.measure_tool import MeasureTool
from .tools.paint_tool import PaintTool
from .tools.path_tool import PathTool
from .tools.scatter_tool import ScatterTool
from .tools.select_tool import SelectTool
from .tools.shape_tool import ShapeTool
from .tools.sticker_tool import StickerTool
from .tools.terrain_tool import TerrainTool
from .tools.vertex_tool import VertexTool
from .tools.wall_tool import WallTool
from .viewports.layout import ViewportGrid
from .viewports.viewport import MAP_SUFFIXES, dropped_maps

APP_NAME = "Rampenschmiede"
#: Reihenfolge der Werkzeuge links (wie oft man sie braucht)
TOOL_ORDER = ("select", "paint", "shape", "wall", "vertex", "terrain", "scatter", "entity", "path", "decal", "face", "clip", "hole", "measure", "cordon")
#: Werkzeugleiste links: aktives Werkzeug orange hinterlegt, wie in Hammer eingedrückt
TOOLBAR_STYLE = """
QToolButton { min-width: 58px; padding: 4px 2px; border: 1px solid transparent; border-radius: 5px; }
QToolButton:hover { background: rgba(255, 255, 255, 0.08); }
QToolButton:checked { background: rgba(255, 140, 40, 0.25); border: 1px solid #ff8c28; color: #ffb070; }
"""
FILE_FILTER = "Rampenschmiede-Projekt (*.rsmap)"
OPEN_FILTER = (N_("Maps (*.rsmap *.vmf *.bsp);;Rampenschmiede-Projekt (*.rsmap);;Hammer-Map (*.vmf);;"
               "Kompilierte Map (*.bsp)"))
BSP_FILTER = N_("Kompilierte Map (*.bsp)")
VMF_FILTER = N_("Hammer-Map (*.vmf)")
MAX_RECENT = 8
#: Steigt, wenn neue Panels dazukommen: Alte gespeicherte Anordnungen werden dann verworfen
LAYOUT_VERSION = 6
DOCK_MIN_WIDTH = 340
#: Tempo der 3D-Kamera beim Fliegen (Units pro Sekunde)
CAMERA_SPEEDS = ((250, N_("Langsam")), (600, N_("Normal")), (1200, N_("Schnell")), (2500, N_("Sehr schnell")))
#: Gemerkte Kameras in `doc.extra`
CAMERAS_KEY = "kameras"
#: Bildgröße der Stile im Stil-Knopf oben
STYLE_THUMB = QSize(150, 96)

CONTROLS_HELP = N_("""
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
<tr><td>[ und ]</td><td>Raster feiner / gröber (im Gelände-Werkzeug: Pinsel kleiner / größer)</td></tr>
<tr><td>Pfeiltasten (2D)</td><td>Auswahl um eine Rasterweite verschieben</td></tr>
<tr><td>Shift + Ziehen</td><td>Auswahl kopieren</td></tr>
<tr><td>Zweiter Klick auf Auswahl</td><td>Dreh- statt Skaliergriffe</td></tr>
<tr><td>Strg+M</td><td>Transformieren mit exakten Zahlen</td></tr>
<tr><td>Strg+L / Strg+I</td><td>Spiegeln horizontal / vertikal (bezogen auf die aktive 2D-Ansicht)</td></tr>
<tr><td>H / Strg+H / U</td><td>Auswahl ausblenden / Rest ausblenden / alles einblenden</td></tr>
<tr><td>Strg+G / Strg+U / Strg+W</td><td>Gruppieren / Gruppe auflösen / Gruppen ignorieren</td></tr>
<tr><td>Strg+T / Strg+Shift+W</td><td>An Entity binden (func_detail, Trigger …) / zurück zur Welt</td></tr>
<tr><td>Strg+Shift+V</td><td>Mehrfach kopieren mit Versatz und Drehung</td></tr>
<tr><td>Strg+B</td><td>Auswahl ans Raster legen</td></tr>
<tr><td>Enter / Esc</td><td>Form erstellen / Rahmen oder Auswahl verwerfen</td></tr>
</table>
<h3>Wände (Shift+K)</h3>
<table>
<tr><td>Klick in „Oben“ oder 3D</td><td>Punkt setzen, die Wände werden an den Ecken verbunden</td></tr>
<tr><td>Klick auf den ersten Punkt</td><td>Raum schließen</td></tr>
<tr><td>Enter / zweiter Klick auf den letzten Punkt</td><td>fertig</td></tr>
<tr><td>Rücktaste / Esc</td><td>letzten Punkt zurück / verwerfen</td></tr>
</table>
<h3>Aufkleber (Shift+T)</h3>
<table>
<tr><td>Klick in 3D auf eine Fläche</td><td>Overlay oder Decal mit dem Material aus dem Browser setzen</td></tr>
<tr><td>Overlay / Decal</td><td>beliebige Größe und jedes Material / Bild aus decals/ in Originalgröße</td></tr>
</table>
<h3>Bereich / Cordon (Shift+O)</h3>
<table>
<tr><td>Rechteck ziehen in 2D</td><td>Bereich setzen: beim Kompilieren wird nur er gebaut</td></tr>
<tr><td>Kante oder Ecke ziehen / innen ziehen</td><td>Größe ändern / verschieben</td></tr>
<tr><td>Entf</td><td>Bereich löschen, wieder die ganze Map bauen</td></tr>
</table>
<h3>Ecken (Shift+V)</h3>
<table>
<tr><td>Ecke oder Kantenmitte ziehen</td><td>Brush verformen; Kantenmitte zieht beide Ecken</td></tr>
<tr><td>Strg + Klick / Rahmen ziehen</td><td>mehrere Ecken wählen</td></tr>
<tr><td>Pfeiltasten (2D)</td><td>gewählte Ecken um eine Rasterweite schieben</td></tr>
<tr><td><b>3D</b>: Shift + Ziehen</td><td>Ecke nach oben/unten</td></tr>
</table>
<h3>Gelände (Shift+G) und Streuen (Shift+D)</h3>
<table>
<tr><td>Ziehen über Gelände</td><td>formen mit der gewählten Pinsel-Art</td></tr>
<tr><td>Shift + Ziehen</td><td>umgekehrt: Senken statt Heben, Textur weg statt malen; beim Streuen: Props entfernen</td></tr>
<tr><td>[ und ]</td><td>Pinsel bzw. Streu-Kreis kleiner / größer</td></tr>
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
<tr><td>Alt+P</td><td>Probleme suchen, mit Hinspringen und Reparieren</td></tr>
<tr><td>Strg+F / Strg+Shift+G</td><td>Suchen und Ersetzen / Gehe zu ID</td></tr>
<tr><td>Shift+M</td><td>Messen: Abstand, Versatz und Steigung</td></tr>
</table>
""")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.editor = EditorContext()
        for tool in (SelectTool(self.editor), ShapeTool(self.editor), EntityTool(self.editor), FaceTool(self.editor),
                     ClipTool(self.editor), HoleTool(self.editor), TerrainTool(self.editor), VertexTool(self.editor),
                     MeasureTool(self.editor), WallTool(self.editor), CordonTool(self.editor), StickerTool(self.editor),
                     PathTool(self.editor)):
            self.editor.register_tool(tool)
        self._clipboard: list[MapObject] = []
        self.settings = QSettings("Rampenschmiede", "Rampenschmiede")
        self.profiles = self._load_profiles()
        #: Texturen der zuletzt geöffneten BSP (aus ihr ausgepackt)
        self._map_textures: list[str] = []
        self.compile_settings = self._load_compile_settings()
        self.compiler = CompileController(self.editor, self)
        self.seal = SealWatcher(self.editor, self)
        self.autosaver = Autosaver(self.editor, int(self.settings.value("autosave_minutes", DEFAULT_MINUTES)), self)
        self._reload_materials()

        self.grid_view = ViewportGrid(self.editor)
        self.setCentralWidget(self.grid_view)
        self._build_docks()
        self._build_actions()
        self._set_icons()
        self.material_browser.add_actions([self.act_ramp_assistant, self.act_world_style, None, self.act_free_assets,
                                           self.act_import_texture, self.act_texture_packs])
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
        ed.selection_changed.connect(self._show_selection_in_scene)
        ed.tool_changed.connect(self._on_tool_changed)
        ed.document_changed.connect(self._sync_ramp_clip)
        ed.document_replaced.connect(self._sync_ramp_clip)
        ed.document_replaced.connect(self._sync_cordon)
        ed.cordon_changed.connect(self._sync_cordon)
        self.compiler.started.connect(self._on_compile_started)
        self.compiler.finished.connect(self._on_compile_finished)

        ed.set_tool("select")
        self._sync_cordon()
        self._restore_window()
        self.seal.checked.connect(self._on_seal_checked)
        self.setAcceptDrops(True)
        ed.files_dropped.connect(lambda paths: QTimer.singleShot(0, lambda: self.open_dropped(paths)))
        self._new_document()
        self._update_undo_actions()
        # Letzte Sitzung abgestürzt? Neueste automatische Sicherung anbieten
        crashed = self.settings.value("clean_exit", "true") == "false"
        self.settings.setValue("clean_exit", "false")
        if crashed:
            QTimer.singleShot(0, self._offer_recovery)

    # ---- Aufbau ------------------------------------------------------------------
    def _build_docks(self) -> None:
        self.tool_dock = QDockWidget(self.tr("Werkzeug"), self)
        self.tool_dock.setObjectName("dock_tool")
        self.tool_options = ToolOptionsPanel(self.editor)
        self.tool_dock.setWidget(self.tool_options)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tool_dock)
        self.sel_dock = QDockWidget(self.tr("Auswahl"), self)
        self.sel_dock.setObjectName("dock_selection")
        self.selection_panel = SelectionPanel(self.editor)
        self.sel_dock.setWidget(_scrollable(self.selection_panel))
        self.lib_dock = QDockWidget(self.tr("Bibliothek"), self)
        self.lib_dock.setObjectName("dock_library")
        self.library = LibraryPanel(self.editor, self._insert_point)
        self.lib_dock.setWidget(_scrollable(self.library))
        self.editor.register_tool(PaintTool(self.editor, self.library))
        self.tool_options.add_paint_page(self.library)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.lib_dock)
        self.scene_dock = QDockWidget(self.tr("Szene"), self)
        self.scene_dock.setObjectName("dock_scene")
        self.scene = ScenePanel(self.editor, self.center_on_selection)
        self.scene_dock.setWidget(self.scene)
        self._arrange_left()
        # Ohne Mindestbreite drücken die Ansichten die Panels auf wenige Pixel zusammen.
        for dock in (self.tool_dock, self.sel_dock, self.lib_dock, self.scene_dock):
            dock.widget().setMinimumWidth(DOCK_MIN_WIDTH)
        self.log_dock = QDockWidget(self.tr("Kompilieren"), self)
        self.log_dock.setObjectName("dock_compile_log")
        self.compile_log = CompileLogPanel(self.compiler, self._center_views_on)
        self.log_dock.setWidget(self.compile_log)
        self.mat_dock = QDockWidget(self.tr("Materialien"), self)
        self.mat_dock.setObjectName("dock_materials")
        self.material_browser = MaterialBrowser(self.editor)
        self.mat_dock.setWidget(self.material_browser)
        self.model_dock = QDockWidget(self.tr("Modelle"), self)
        self.model_dock.setObjectName("dock_models")
        self.model_browser = ModelBrowser(self.editor, self._insert_point)
        self.model_dock.setWidget(self.model_browser)
        self.editor.register_tool(ScatterTool(self.editor, self.model_browser))
        self.tool_options.add_scatter_page()
        self.addDockWidget(Qt.BottomDockWidgetArea, self.mat_dock)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)
        self.tabifyDockWidget(self.mat_dock, self.model_dock)
        self.tabifyDockWidget(self.mat_dock, self.log_dock)
        self._bottom_height = 260
        for dock in (self.mat_dock, self.model_dock, self.log_dock):
            dock.visibilityChanged.connect(lambda visible, d=dock: self._bottom_tab_switched(d, visible))
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
        self.act_open_bsp = self._action("&BSP öffnen …", self.file_open_bsp, None,
                                         "Kompilierte Map (.bsp) öffnen, z. B. zum Nachbauen oder Ansehen. "
                                         "Geht auch per Ziehen ins Fenster")
        self.act_export_vmf = self._action("Als VMF e&xportieren …", self.file_export_vmf, "Ctrl+Shift+E",
                                           "Map als .vmf für Hammer oder andere Werkzeuge speichern")
        self.act_autosave = self._action("Automatisch &sichern (alle 5 Minuten)", self._toggle_autosave, None,
                                         "Geänderte Maps regelmäßig in den Sicherungsordner schreiben; vor jedem "
                                         "Speichern wird die alte Fassung dort abgelegt", checkable=True)
        self.act_autosave.setChecked(self.autosaver.minutes > 0)
        self.act_open_backup = self._action("Sicherung ö&ffnen …", lambda: self.open_backup(), None,
                                            "Automatische Sicherungen und alte Fassungen vor dem Speichern")
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
        self.act_hollow = self._action("&Hohl machen …", lambda: self.hollow_selection(), "Ctrl+Shift+H",
                                       "Aus jedem ausgewählten Brush werden Wände mit der gewählten Stärke "
                                       "(Make Hollow wie in Hammer)")
        self.align_actions: list[QAction | None] = []
        for axis, (lo, hi) in enumerate((("Links (−X)", "Rechts (+X)"), ("Vorne (−Y)", "Hinten (+Y)"),
                                         ("Unten (−Z)", "Oben (+Z)"))):
            self.align_actions += [
                self._action(lo, lambda _c=False, a=axis: self.align_selection(a, "min")),
                self._action(hi, lambda _c=False, a=axis: self.align_selection(a, "max")),
                self._action("Mitte " + "XYZ"[axis], lambda _c=False, a=axis: self.align_selection(a, "mitte")),
                None]
        self.distribute_actions = [
            self._action(f"Entlang {'XYZ'[axis]}", lambda _c=False, a=axis: self.distribute_selection(a))
            for axis in range(3)]
        self.act_flip_h = self._action("Spiegeln &horizontal", lambda: self._flip(0), "Ctrl+L")
        self.act_flip_v = self._action("Spiegeln &vertikal", lambda: self._flip(1), "Ctrl+I")
        self.act_find = self._action("&Suchen und Ersetzen …", self.show_find, "Ctrl+F",
                                     "Entities nach Klasse, Name oder Wert suchen; Texturen ersetzen")
        self.act_sounds = self._action("&Sounds anhören …", self.show_sounds, None,
                                       "Alle Sounds des Spiels durchsuchen und abspielen")
        self.act_instance_insert = self._action("&Instanz einfügen …", lambda: self.insert_instance(), None,
                                                "Eine andere Map-Datei (.vmf, .rsmap) als func_instance einsetzen; "
                                                "Änderungen an der Datei erscheinen überall")
        self.act_instance_save = self._action("Auswahl als Instanz &speichern …", lambda: self.save_as_instance(), None,
                                              "Die Auswahl in eine eigene Datei schreiben und hier durch eine "
                                              "Instanz ersetzen (z. B. Startraum, Checkpoint)")
        self.act_instance_open = self._action("Instanz-Datei ö&ffnen", self.open_instance_file, None,
                                              "Die Datei der gewählten Instanz in einem zweiten Fenster bearbeiten")
        self.act_entity_report = self._action("&Entity-Bericht …", self.show_entity_report, "Alt+E",
                                              "Alle Entities als Liste: filtern, hinspringen, auswählen, löschen")
        self.act_goto = self._action("&Gehe zu ID …", self.goto_dialog, "Ctrl+Shift+G",
                                     "Objekt über seine Nummer (wie im Kompilier-Log oder in Hammer) oder "
                                     "seinen Namen finden")
        self.act_multi_copy = self._action("&Mehrfach kopieren …", self.multi_copy, "Ctrl+Shift+V",
                                           "Auswahl mehrmals kopieren, jede Kopie weiter verschoben und gedreht "
                                           "(Treppen, Säulenreihen, Wendel)")
        self.act_snap_selection = self._action("Auswahl ans &Raster", self.snap_selection, "Ctrl+B",
                                               "Schiebt die Auswahl so, dass ihre Ecke auf dem Raster liegt")
        self.act_group = self._action("&Gruppieren", self.group_selection, "Ctrl+G",
                                      "Auswahl zu einer Gruppe: ein Klick wählt dann alle Mitglieder")
        self.act_ungroup = self._action("Gruppe a&uflösen", self.ungroup_selection, "Ctrl+U")
        self.act_ignore_groups = self._action("Gruppen &ignorieren", self._toggle_ignore_groups, "Ctrl+W",
                                              "Klick wählt einzelne Objekte statt ganzer Gruppen",
                                              checkable=True)
        self.act_tie = self._action("An &Entity binden …", self.tie_to_entity, "Ctrl+T",
                                    "Ausgewählte Brushes zu func_detail, Trigger, Tür usw. machen")
        self.act_to_world = self._action("Zur &Welt", self.move_to_world, "Ctrl+Shift+W",
                                         "Brushes aus ihrer Entity lösen, sie werden wieder Welt-Brushes")

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
        self.speed_group = QActionGroup(self)
        self.speed_actions: dict[int, QAction] = {}
        for speed, label in CAMERA_SPEEDS:
            a = self._action(label, lambda _c=False, v=speed: self.set_camera_speed(v), checkable=True)
            self.speed_group.addAction(a)
            self.speed_actions[speed] = a
        self.act_camera_save = self._action("Kamera &merken", self.save_camera, "Ctrl+Shift+K",
                                            "Die aktuelle 3D-Ansicht merken; im Menü Kameras springt man zurück")
        self.act_camera_clear = self._action("Gemerkte Kameras löschen", self.clear_cameras)
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
        self.act_load_portals = self._action("P&ortal-Datei laden …", self.open_portalfile, None,
                                             "Die Portale von vbsp (.prt) als blaue Umrisse zeigen: wo viele liegen, "
                                             "rechnet VIS lange")
        self.act_clear_portals = self._action("Portale aus&blenden", lambda: self.editor.set_portals([]))
        self.act_problems = self._action("&Probleme suchen …", self.show_problems, "Alt+P",
                                         "Kaputte Brushes, fehlende Texturen und Modelle, Teleporter ohne Ziel, "
                                         "Spawns, Zonen, Engine-Grenzen, zu flache Rampen und Rampbug-Gefahr")
        self.act_check_seal = self._action("&Dichtheit prüfen", self.show_seal_problem, None,
                                           "Prüft ohne Kompilieren, ob alle Entities umschlossen sind")
        self.act_cordon = self._action("Nur &Bereich bauen (Cordon)", self._toggle_cordon, None,
                                       "Kompiliert nur, was im Bereich liegt, und dichtet ihn mit Skybox ab. "
                                       "Den Bereich zieht das Werkzeug „Bereich“ (Shift+O).", checkable=True)
        self.act_cordon_selection = self._action("Bereich = Aus&wahl", self.cordon_from_selection, None,
                                                 "Bereich um die Auswahl legen (mit etwas Luft) und einschalten")
        self.act_cordon_clear = self._action("Bereich &löschen", lambda: self.editor.set_cordon(None))
        self.act_enclose = self._action("Map mit Skybox &umhüllen", self.enclose_with_skybox, None,
                                        "Legt eine dichte Skybox-Hülle um alles, was in der Map ist")

        self.act_ramp_assistant = self._action("&Rampen-Assistent …", self.ramp_assistant, "Ctrl+Shift+R",
                                               "Farben für Rampen, Linien und Wände wählen, den Rest macht die "
                                               "Rampenschmiede")
        self.act_world_style = self._action("&Welt-Stil …", self.world_style, None,
                                            "Himmel, Sonne, Nebel, Wände und Rampenfarben mit einem Klick")
        self.act_sky = self._action("&Himmel …", self.choose_sky, None,
                                    "Skybox der Map wählen; die 3D-Ansicht zeigt sie in „Texturiert“ und "
                                    "„Licht-Vorschau“")
        self.act_skybox3d = self._action("&3D-Skybox …", self.skybox3d_dialog, None,
                                         "Berge, Stadt oder Dünen am Horizont: legt einen 3D-Skybox-Raum mit "
                                         "Kamera und Kulisse an")
        self.act_ramp_clip = self._action("&Playerclip auf Rampen", self.set_ramp_clip, None,
                                          "Glatte Playerclip-Hülle auf allen Rampen (empfohlen). Aus: Die Rampe "
                                          "selbst ist die Kollision.", checkable=True)
        self.act_import_texture = self._action("Bild als Textur &importieren …", self.import_texture, None,
                                               "PNG, JPG, TGA oder BMP als eigenes Material übernehmen")
        self.act_texture_packs = self._action("Textur&pakete …", self.edit_texture_packs, None,
                                              "Eigene Ordner mit Materialien einbinden")
        self.act_stats = self._action("Map-&Statistik …", self.show_stats, None,
                                      "Brushes, Entities, Overlays … und wie nah die Map an den Grenzen von Source ist")
        self.act_free_assets = self._action("&Freie Texturen und Himmel …", self.free_assets, None,
                                            "Texturen und Himmel von Poly Haven (CC0) mit einem Klick laden")

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
        for a in (self.act_save, self.act_save_as, None, self.act_autosave, self.act_open_backup, None,
                  self.act_import_vmf, self.act_open_bsp, self.act_export_vmf):
            m.addSeparator() if a is None else m.addAction(a)
        m.addSeparator()
        m.addAction(self.act_quit)

        m = mb.addMenu(self.tr("&Bearbeiten"))
        for a in (self.act_undo, self.act_redo, None, self.act_cut, self.act_copy, self.act_paste, self.act_delete,
                  None, self.act_select_all, self.act_find, self.act_goto, self.act_entity_report, self.act_sounds, None, self.act_group, self.act_ungroup, self.act_ignore_groups, None,
                  self.act_tie, self.act_to_world, None, self.act_carve, self.act_hollow, None, self.act_instance_insert, self.act_instance_save, self.act_instance_open, None, self.act_transform,
                  self.act_flip_h, self.act_flip_v, self.act_multi_copy, self.act_snap_selection):
            m.addSeparator() if a is None else m.addAction(a)
        sub = m.addMenu(self.tr("&Ausrichten"))
        for a in self.align_actions[:-1]:
            sub.addSeparator() if a is None else sub.addAction(a)
        sub = m.addMenu(self.tr("Gleichmäßig &verteilen"))
        for a in self.distribute_actions:
            sub.addAction(a)

        m = mb.addMenu(self.tr("&Ansicht"))
        for a in (self.act_grid_finer, self.act_grid_coarser, None, self.act_center, None, self.act_hide,
                  self.act_hide_others, self.act_unhide, None, self.act_expert, self.act_reset_layout):
            m.addSeparator() if a is None else m.addAction(a)
        m.addSeparator()
        sub = m.addMenu(self.tr("Kamera-&Tempo"))
        for a in self.speed_actions.values():
            sub.addAction(a)
        self.cameras_menu = m.addMenu(self.tr("&Kameras"))
        self.cameras_menu.aboutToShow.connect(self._fill_cameras_menu)
        # zweisprachig, damit man das Menü auch in einer fremden Sprache findet
        title = self.tr("Sprache")
        self.language_menu = m.addMenu(icon("language"), title if title == "Language" else f"{title} / Language")
        group = QActionGroup(self)
        for code, name in i18n.LANGUAGES.items():
            a = self.language_menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(code == i18n.saved_language())
            a.triggered.connect(lambda _=False, c=code: self.choose_language(c))
            group.addAction(a)
        m.addSeparator()
        m.addAction(self.tool_dock.toggleViewAction())
        m.addAction(self.sel_dock.toggleViewAction())
        m.addAction(self.lib_dock.toggleViewAction())
        m.addAction(self.mat_dock.toggleViewAction())
        m.addAction(self.model_dock.toggleViewAction())

        m = mb.addMenu(self.tr("&Werkzeuge"))
        for a in self.tool_actions.values():
            m.addAction(a)

        m = mb.addMenu(self.tr("Te&xturen"))
        for a in (self.act_ramp_assistant, self.act_world_style, self.act_sky, self.act_skybox3d, self.act_ramp_clip, None,
                  self.act_free_assets, self.act_import_texture, self.act_texture_packs):
            m.addSeparator() if a is None else m.addAction(a)

        m = mb.addMenu(self.tr("&Testen"))
        for a in (self.act_compile, self.act_compile_again, self.act_compile_cancel, None,
                  self.act_problems, self.act_check_seal, self.act_stats, self.act_enclose, None,
                  self.act_cordon, self.act_cordon_selection, self.act_cordon_clear, None,
                  self.act_load_pointfile, self.act_clear_leak, self.act_load_portals, self.act_clear_portals, None, self.act_profiles):
            m.addSeparator() if a is None else m.addAction(a)
        m.addAction(self.log_dock.toggleViewAction())

        m = mb.addMenu(self.tr("&Hilfe"))
        m.addAction(self.act_controls)
        m.addAction(self.act_about)

    def choose_language(self, lang: str) -> None:
        """Sprache merken; sie gilt nach dem Neustart (alle Texte werden beim Start übersetzt)."""
        if lang == i18n.saved_language():
            return
        i18n.save_language(lang)
        QMessageBox.information(self, self.tr("Sprache"), self.tr(
            "Die Sprache wird beim nächsten Start gewechselt. Bitte die Rampenschmiede neu starten."))

    def _set_icons(self) -> None:
        for action, name in ((self.act_new, "new"), (self.act_open, "open"), (self.act_save, "save"),
                             (self.act_undo, "undo"), (self.act_redo, "redo"),
                             (self.act_grid_finer, "grid_finer"), (self.act_grid_coarser, "grid_coarser"),
                             (self.act_compile, "compile"), (self.act_expert, "expert"),
                             (self.act_ramp_assistant, "palette"), (self.act_carve, "carve"), (self.act_world_style, "sun"),
                             (self.act_sky, "sky")):
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
        tb.addSeparator()
        tb.addWidget(self._style_button())
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

    def _style_button(self) -> QToolButton:
        """Stil der Map: Klick zeigt alle Welt-Stile als Bilder, ein Klick auf eins wendet ihn an."""
        button = QToolButton()
        button.setIcon(icon("palette"))
        button.setText(self.tr("Stil"))
        button.setToolTip(self.tr("Stil der ganzen Map wählen: Himmel, Sonne, Nebel, Texturen (Tag, Nacht, Neon …)"))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(button)
        self.style_gallery = StyleGallery(STYLE_THUMB, columns=4)
        gallery_action = QWidgetAction(menu)
        gallery_action.setDefaultWidget(self.style_gallery)
        menu.addAction(gallery_action)
        menu.addSeparator()
        menu.addAction(self.act_world_style)

        def picked(item) -> None:
            style = self.style_gallery.style_at(item)
            menu.close()
            if style is not None:
                self.apply_world_style(style, get_theme(self.editor.doc).collision == "clip")

        self.style_gallery.itemClicked.connect(picked)
        button.setMenu(menu)
        self.style_button = button
        return button

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

    def _show_selection_in_scene(self) -> None:
        """Beim Anklicken in den Ansichten links die Szenen-Liste zeigen. Bei Rampen bleibt die
        Bibliothek vorn, dort stehen ihre Regler."""
        ed = self.editor
        if not ed.selection or ed.tool is None or ed.tool.name != "select":
            return
        if any(is_block_root(o) for o in ed.selected_objects()):
            return
        self.scene_dock.raise_()

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
        if name == "paint":
            # Beim Malen gehören die Regler der Vorlage nach vorne, nicht der Szenen-Baum
            self.lib_dock.show()
            self.lib_dock.raise_()

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

    # ---- Bereich (Cordon) --------------------------------------------------------
    def _sync_cordon(self) -> None:
        box, on = self.editor.cordon()
        self.act_cordon.blockSignals(True)
        self.act_cordon.setChecked(box is not None and on)
        self.act_cordon.blockSignals(False)
        self.act_cordon_clear.setEnabled(box is not None)

    def _toggle_cordon(self, on: bool) -> None:
        box, _ = self.editor.cordon()
        if box is None:
            if on and not self.cordon_from_selection():
                self.editor.set_tool("cordon")
            self._sync_cordon()
            return
        self.editor.set_cordon(box, on)
        self.statusBar().showMessage(self.tr("Beim Kompilieren wird nur der Bereich gebaut") if on else
                                     self.tr("Es wird wieder die ganze Map gebaut"), 4000)

    def cordon_from_selection(self) -> bool:
        return self.editor.cordon_from_selection()

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

    def file_open_bsp(self) -> None:
        if not self._confirm_discard():
            return
        start = self.settings.value("last_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, self.tr("BSP öffnen"), start, self.tr(BSP_FILTER))
        if path:
            self.open_path(Path(path))

    def open_dropped(self, paths: list[Path]) -> bool:
        """Ins Fenster gezogene Dateien: die erste passende Map wird geöffnet."""
        path = next((p for p in paths if p.suffix.lower() in MAP_SUFFIXES), None)
        if path is None or not self._confirm_discard():
            return False
        return self.open_path(path)

    def open_path(self, path: Path) -> bool:
        path = path.absolute()
        if path.suffix.lower() == ".vmf":
            return self._import_vmf(path)
        if path.suffix.lower() == ".bsp":
            return self._open_bsp(path)
        try:
            doc = rsmap.load(path)
            upgrade_roots(doc)
        except (OSError, rsmap.ProjectFormatError, KeyError, ValueError, TypeError) as exc:
            QMessageBox.critical(self, APP_NAME, self.tr("Datei konnte nicht geöffnet werden:\n{0}").format(exc))
            return False
        self.editor.set_document(doc, path)
        self._remember(path)
        self._update_title()
        self.statusBar().showMessage(self.tr("{0} geladen ({1} Objekte)").format(path.name, len(doc)), 5000)
        return True

    # ---- Sicherungen ---------------------------------------------------------------
    def _toggle_autosave(self, on: bool) -> None:
        minutes = DEFAULT_MINUTES if on else 0
        self.settings.setValue("autosave_minutes", minutes)
        self.autosaver.set_minutes(minutes)

    def open_backup(self, path: Path | None = None) -> bool:
        """Sicherung öffnen; Speichern fragt danach nach einem Ort (nie in den Sicherungsordner)."""
        if path is None:
            name, _ = QFileDialog.getOpenFileName(self, self.tr("Sicherung öffnen"), str(backups_dir()),
                                                  self.tr(FILE_FILTER))
            if not name:
                return False
            path = Path(name)
        if not self._confirm_discard() or not self.open_path(path):
            return False
        self.editor.file_path = None
        self.editor.stack.set_dirty()  # ungespeichert, bis man einen Ort wählt
        self.statusBar().showMessage(self.tr("Sicherung geöffnet: {0}. Mit „Speichern unter“ ablegen").format(
            path.name), 8000)
        return True

    def _offer_recovery(self) -> None:
        latest = latest_autosave()
        if latest is None:
            return
        answer = QMessageBox.question(
            self, APP_NAME, self.tr("Die letzte Sitzung wurde nicht sauber beendet.\n"
                                    "Neueste automatische Sicherung öffnen?\n\n{0}").format(latest.name),
            QMessageBox.Yes | QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.open_backup(latest)

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

    def _open_bsp(self, path: Path) -> bool:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            doc, report = bsp.load_bsp(path)
        except (OSError, bsp.BspError) as exc:
            QMessageBox.critical(self, APP_NAME, self.tr("BSP konnte nicht geöffnet werden:\n{0}").format(exc))
            return False
        finally:
            QApplication.restoreOverrideCursor()
        # In die BSP gepackte Texturen auspacken, damit die Map ihre echten Farben zeigt
        try:
            folder = bsp_textures_dir(path.stem)
            packed = bsp.extract_materials(path, folder)
        except OSError:
            packed = 0
        if packed:
            self._map_textures = [str(folder)]
            self._reload_materials()
        # Eigener Name, damit Kompilieren nie die Original-BSP überschreibt
        self.editor.set_document(doc, None, import_path=path.with_name(f"{path.stem}_bearbeitet.vmf"))
        self._remember(path)
        self._update_title()
        msg = self.tr("{0} geöffnet: {1} Brushes, {2} Entities").format(path.name, report.solids, report.entities)
        if packed:
            msg += self.tr(" · {0} eingepackte Textur-Dateien übernommen").format(packed)
        if report.warnings:
            msg += " · " + " · ".join(report.warnings)
        self.statusBar().showMessage(msg, 12000)
        self.center_on_selection()
        self.scene_dock.show()
        self.scene_dock.raise_()
        return True

    def dragEnterEvent(self, e) -> None:
        if dropped_maps(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = dropped_maps(e.mimeData())
        if paths:
            e.acceptProposedAction()
            self.editor.files_dropped.emit(paths)

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
        backup_before_save(path)
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

    def show_stats(self) -> StatsDialog:
        dlg = StatsDialog(self.editor.doc, self)
        dlg.show()
        return dlg

    # ---- Kamera ----------------------------------------------------------------------
    def views_3d(self) -> list:
        return [v for v in self.grid_view.viewports() if v.is_3d]

    def set_camera_speed(self, speed: int) -> None:
        for v in self.views_3d():
            v.cam3d.speed = float(speed)
        self.settings.setValue("camera_speed", speed)
        if speed in self.speed_actions:
            self.speed_actions[speed].setChecked(True)

    def cameras(self) -> list[dict]:
        return list(self.editor.doc.extra.get(CAMERAS_KEY, []))

    def save_camera(self) -> int:
        views = self.views_3d()
        if not views:
            return 0
        cam = views[0].cam3d
        entry = {"pos": [round(float(c), 1) for c in cam.position], "yaw": round(cam.yaw, 2),
                 "pitch": round(cam.pitch, 2)}
        cams = self.cameras() + [entry]
        self.editor.doc.extra[CAMERAS_KEY] = cams
        self.editor.stack.set_dirty()
        self.editor.status_message.emit(self.tr("Kamera {0} gemerkt").format(len(cams)))
        return len(cams)

    def goto_camera(self, index: int) -> bool:
        cams = self.cameras()
        if not 0 <= index < len(cams):
            return False
        c = cams[index]
        for v in self.views_3d():
            v.cam3d.position = np.array(c["pos"], dtype=float)
            v.cam3d.yaw, v.cam3d.pitch = float(c["yaw"]), float(c["pitch"])
            v.update()
        return True

    def clear_cameras(self) -> None:
        if self.editor.doc.extra.pop(CAMERAS_KEY, None) is not None:
            self.editor.stack.set_dirty()

    def _fill_cameras_menu(self) -> None:
        m = self.cameras_menu
        m.clear()
        m.addAction(self.act_camera_save)
        cams = self.cameras()
        if cams:
            m.addSeparator()
            for i, c in enumerate(cams):
                pos = " ".join(f"{v:.0f}" for v in c["pos"])
                m.addAction(self.tr("Kamera {0}  ({1})").format(i + 1, pos), lambda i=i: self.goto_camera(i))
            m.addSeparator()
            m.addAction(self.act_camera_clear)

    def hollow_selection(self, thickness: int | None = None) -> bool:
        ed = self.editor
        if not ed.selection:
            ed.status_message.emit(self.tr("Erst die Brushes auswählen, die hohl werden sollen"))
            return False
        if thickness is None:
            last = int(self.settings.value("hollow_thickness", 32))
            value, ok = QInputDialog.getInt(
                self, self.tr("Hohl machen"),
                self.tr("Wandstärke in Units (positiv: Wände nach innen, negativ: nach außen)"), last, -1024, 1024, 8)
            if not ok or value == 0:
                return False
            self.settings.setValue("hollow_thickness", value)
            thickness = value
        cmd, ids = hollow(ed.doc, ed.selection, thickness)
        if cmd is None:
            ed.status_message.emit(self.tr("Nichts hohl gemacht: Bausteine erst lösen, Brushes dicker als die Wand"))
            return False
        ed.run(cmd)
        ed.set_selection(ids)
        ed.status_message.emit(self.tr("Hohl gemacht: {0} Wände").format(len(ids)))
        return True

    def align_selection(self, axis: int, mode: str) -> bool:
        cmd = organize.align(self.editor.doc, self.editor.selected_objects(), axis, mode, self.editor.texture_lock)
        if cmd is None:
            self.editor.status_message.emit(self.tr("Zum Ausrichten mindestens zwei Objekte auswählen"))
            return False
        return self.editor.run(cmd)

    def distribute_selection(self, axis: int) -> bool:
        cmd = organize.distribute(self.editor.doc, self.editor.selected_objects(), axis, self.editor.texture_lock)
        if cmd is None:
            self.editor.status_message.emit(self.tr("Zum Verteilen mindestens drei Objekte auswählen"))
            return False
        return self.editor.run(cmd)

    # ---- Probleme ------------------------------------------------------------------
    def find_problems(self):
        ed = self.editor
        try:
            catalog = ed.entity_catalog
        except Exception:  # ohne Katalog fehlt nur die Prüfung leerer Brush-Entities
            catalog = None
        game = ed.materials is not None and ed.materials.has_game
        return find_problems(ed.doc, ed.materials if game else None, ed.models if game else None, catalog,
                             self.seal.check_now())

    def show_sounds(self) -> SoundBrowser:
        dlg = SoundBrowser(self.editor.sounds(), "", self, choose=False)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.show()
        return dlg

    # ---- Instanzen ----------------------------------------------------------------------
    def _instance_ref(self, path: Path) -> str:
        """Dateiverweis für `file`: relativ zur Map, wenn sie gespeichert ist."""
        base = self.editor.map_dir()
        if base is not None:
            try:
                return os.path.relpath(path, base).replace("\\", "/")
            except ValueError:  # anderes Laufwerk
                pass
        return str(path).replace("\\", "/")

    def insert_instance(self, path: str | None = None) -> int | None:
        if path is None:
            start = str(self.editor.map_dir() or self.settings.value("last_dir", ""))
            path, _ = QFileDialog.getOpenFileName(self, self.tr("Instanz einfügen"), start,
                                                  self.tr("Maps (*.vmf *.rsmap)"))
            if not path:
                return None
        ed = self.editor
        x, y, z = (ed.snap(c) for c in self._insert_point())
        ent = Entity(id=ed.doc.new_id(), classname=INSTANCE, keyvalues=(
            ("targetname", unique_targetname(ed.doc, "instanz_1")), ("file", self._instance_ref(Path(path))),
            ("origin", f"{x:g} {y:g} {z:g}"), ("angles", "0 0 0"), ("fixup_style", "0")))
        ed.run(AddObjects([ent], self.tr("Instanz einfügen")))
        ed.set_selection([ent.id])
        if ed.instance_objects(ent) is None:
            ed.status_message.emit(self.tr("Instanz-Datei nicht gefunden: {0}").format(path))
        return ent.id

    def save_as_instance(self, path: str | None = None) -> int | None:
        ed = self.editor
        bb = ed.selection_bbox()
        if bb is None:
            ed.status_message.emit(self.tr("Erst auswählen, was in die Instanz soll"))
            return None
        if path is None:
            start = str((ed.map_dir() or Path(self.settings.value("last_dir", str(Path.home())))) / "instanz.vmf")
            path, _ = QFileDialog.getSaveFileName(self, self.tr("Auswahl als Instanz speichern"), start,
                                                  self.tr("Hammer-Map (*.vmf);;Rampenschmiede-Projekt (*.rsmap)"))
            if not path:
                return None
        target = Path(path)
        if target.suffix.lower() not in (".vmf", ".rsmap"):
            target = target.with_suffix(".vmf")
        # Ursprung: Mitte unten auf dem Raster, damit sich die Instanz gut setzen und drehen lässt
        center = tuple(float(ed.snap((bb.mins[i] + bb.maxs[i]) / 2)) for i in range(2)) + (float(ed.snap(bb.mins[2])),)
        ids = set(ed.selection)
        objs = [o for i in ids if (o := ed.doc.get(i)) is not None] + [s for s in ed.doc.attached(ids) if s.id not in ids]
        content = MapDocument()
        content.reserve_ids_above(max(o.id for o in objs))
        content._insert([translate(o, (-center[0], -center[1], -center[2])) for o in objs])
        try:
            if target.suffix.lower() == ".vmf":
                vmf.save_vmf(content, target)
            else:
                rsmap.save(content, target)
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, self.tr("Speichern fehlgeschlagen:\n{0}").format(exc))
            return None
        ed.instance_cache.forget()
        ent = Entity(id=ed.doc.new_id(), classname=INSTANCE, keyvalues=(
            ("targetname", unique_targetname(ed.doc, target.stem)), ("file", self._instance_ref(target)),
            ("origin", " ".join(f"{c:g}" for c in center)), ("angles", "0 0 0"), ("fixup_style", "0")))
        ed.run(MacroCommand([RemoveObjects(sorted(ids)), AddObjects([ent])], self.tr("Als Instanz speichern")))
        ed.set_selection([ent.id])
        ed.status_message.emit(self.tr("Instanz gespeichert: {0}").format(target))
        return ent.id

    def open_instance_file(self) -> bool:
        ents = [o for o in self.editor.selected_objects() if isinstance(o, Entity) and o.classname.lower() == INSTANCE]
        path = self.editor.instance_file(ents[0]) if ents else None
        if path is None:
            self.editor.status_message.emit(self.tr("Erst eine Instanz mit vorhandener Datei auswählen"))
            return False
        args = [str(path)] if getattr(sys, "frozen", False) else ["-m", "rampenschmiede", str(path)]
        return QProcess.startDetached(sys.executable, args)[0]

    def changeEvent(self, e) -> None:
        # Zurück im Fenster: Instanz-Dateien, die woanders geändert wurden, neu zeigen
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.editor.reload_instances()
        super().changeEvent(e)

    def show_entity_report(self) -> EntityReport:
        if getattr(self, "entity_report", None) is None:
            self.entity_report = EntityReport(self)
        self.entity_report.refresh()
        self.entity_report.show()
        self.entity_report.raise_()
        return self.entity_report

    def show_find(self) -> FindDialog:
        if getattr(self, "find_dialog", None) is None:
            self.find_dialog = FindDialog(self)
        self.find_dialog.refresh()
        self.find_dialog.show()
        self.find_dialog.raise_()
        return self.find_dialog

    def goto_dialog(self, text: str | None = None) -> bool:
        if not text:
            text, ok = QInputDialog.getText(self, self.tr("Gehe zu ID"),
                                            self.tr("Nummer (wie im Kompilier-Log: „Brush 12“) oder Name:"))
            if not ok or not text.strip():
                return False
        oid = search.goto_id(self.editor.doc, text)
        if oid is None:
            self._status(self.tr("Nichts gefunden: {0}").format(text))
            return False
        self.editor.set_selection([oid])
        self.center_on_selection()
        return True

    def show_problems(self) -> ProblemsDialog:
        if getattr(self, "problems_dialog", None) is None:
            self.problems_dialog = ProblemsDialog(self)
        self.problems_dialog.refresh()
        self.problems_dialog.show()
        self.problems_dialog.raise_()
        return self.problems_dialog

    # ---- Ordnen -------------------------------------------------------------------
    def _status(self, text: str) -> None:
        self.editor.status_message.emit(text)

    def group_selection(self) -> bool:
        res = organize.group(self.editor.doc, self.editor.selected_objects())
        if res is None:
            self._status(self.tr("Zum Gruppieren mindestens zwei Objekte auswählen"))
            return False
        self.editor.run(res[0])
        self._status(self.tr("Gruppe {0} erstellt").format(res[1]))
        return True

    def ungroup_selection(self) -> bool:
        cmd = organize.ungroup(self.editor.doc, self.editor.selected_objects())
        if cmd is None:
            self._status(self.tr("In der Auswahl ist keine Gruppe"))
            return False
        return self.editor.run(cmd)

    def _toggle_ignore_groups(self, on: bool) -> None:
        self.editor.ignore_groups = bool(on)
        self._status(self.tr("Gruppen werden ignoriert") if on else self.tr("Klick wählt ganze Gruppen"))

    def _tie_classes(self) -> list[str]:
        try:
            return self.editor.entity_catalog.classnames("solid")
        except Exception:  # Katalog fehlt: nur die häufigen Klassen
            return []

    def tie_to_entity(self, classname: str | None = None) -> bool:
        if not self.editor.selection:
            self._status(self.tr("Erst die Brushes auswählen, die zur Entity werden sollen"))
            return False
        if not classname:
            dlg = TieEntityDialog(self._tie_classes(), parent=self)
            if not dlg.exec() or not dlg.value():
                return False
            classname = dlg.value()
        cat = self.editor.entity_catalog
        cls = cat.get(classname) if cat is not None else None
        try:
            cmd, ent_id = organize.tie_to_entity(self.editor.doc, self.editor.selected_objects(), classname,
                                                 cls.defaults() if cls is not None else ())
        except organize.OrganizeError as exc:
            self._status(str(exc))
            return False
        self.editor.run(cmd)
        self.editor.set_selection([ent_id])
        self._status(self.tr("Brushes sind jetzt {0}").format(classname))
        return True

    def move_to_world(self) -> bool:
        try:
            cmd, ids = organize.move_to_world(self.editor.doc, self.editor.selected_objects())
        except organize.OrganizeError as exc:
            self._status(str(exc))
            return False
        self.editor.run(cmd)
        self.editor.set_selection(ids)
        return True

    def multi_copy(self, values: dict | None = None) -> bool:
        bb = self.editor.selection_bbox()
        if bb is None:
            self._status(self.tr("Erst etwas auswählen, das kopiert werden soll"))
            return False
        if values is None:
            dlg = MultiCopyDialog(tuple(b - a for a, b in zip(bb.mins, bb.maxs)), self)  # type: ignore[arg-type]
            if not dlg.exec():
                return False
            values = dlg.values()
        try:
            cmd, ids = organize.multi_copy(self.editor.doc, self.editor.selected_objects(),
                                           texture_lock=self.editor.texture_lock, **values)
            ok = self.editor.run(cmd)
        except Exception as exc:  # z. B. TransformError oder OrganizeError
            self._status(str(exc))
            return False
        if ok:
            self.editor.set_selection(ids)
        return ok

    def snap_selection(self) -> bool:
        bb = self.editor.selection_bbox()
        if bb is None:
            return False
        delta = organize.snap_delta(bb.mins, self.editor.grid)
        if not any(abs(d) > 1e-9 for d in delta):
            self._status(self.tr("Auswahl liegt schon auf dem Raster"))
            return False
        return self.editor.move_selection(delta)

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
        folders = [textures_dir(), *self.texture_packs(), *self._map_textures]
        self.editor.set_material_library(MaterialLibrary.for_game(profile.game_dir if profile else None, folders))
        self.editor.set_entity_fgds(list(profile.fgds) if profile else [])

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
        self.tool_options.suggest_kit(style.key)
        self.editor.status_message.emit(self.tr("Welt-Stil „{0}“ angewendet").format(self.tr(style.name)))
        return True

    def skybox3d_dialog(self) -> bool:
        has = bool(skybox_ids(self.editor.doc))
        items = [f"{self.tr(st.name)}: {self.tr(st.description)}" for st in SKY3D_STYLES]
        if has:
            items.append(self.tr("Entfernen: 3D-Skybox aus der Map löschen"))
        choice, ok = QInputDialog.getItem(
            self, self.tr("3D-Skybox"),
            self.tr("Was soll am Horizont stehen? Die Kulisse erscheint im Spiel 16-mal so groß hinter dem "
                    "Himmel.") + ("\n" + self.tr("Die vorhandene 3D-Skybox wird ersetzt.") if has else ""),
            items, 0, False)
        if not ok:
            return False
        index = items.index(choice)
        if index >= len(SKY3D_STYLES):
            cmd = remove_command(self.editor.doc)
            if cmd is not None:
                self.editor.run(cmd)
                self.editor.status_message.emit(self.tr("3D-Skybox entfernt"))
            return cmd is not None
        return self.make_skybox3d(SKY3D_STYLES[index].key)

    def make_skybox3d(self, key: str) -> bool:
        style = SKY3D_BY_KEY[key]
        lib = self.editor.materials
        try:
            ground = (pick_material(lib, style.ground, style.ground_words)
                      or wall_material(textures_dir(), style.ground_color)).upper()
            detail = (pick_material(lib, style.detail, style.detail_words)
                      or wall_material(textures_dir(), style.detail_color)).upper()
        except OSError as exc:
            QMessageBox.critical(self, APP_NAME, self.tr("Texturen konnten nicht gespeichert werden:\n{0}").format(exc))
            return False
        self.editor.refresh_materials()
        cmd, objs = skybox_command(self.editor.doc, style, ground, detail)
        self.editor.run(cmd)
        self.editor.set_selection([o.id for o in objs])
        self.editor.status_message.emit(self.tr(
            "3D-Skybox „{0}“ angelegt und ausgewählt. Strg+E springt hin; im Spiel steht sie hinter dem Himmel."
        ).format(self.tr(style.name)))
        return True

    def choose_sky(self) -> bool:
        current = self.editor.doc.world_get("skyname")
        dlg = SkyDialog(self.editor.materials, current, self)
        if dlg.exec() != QDialog.Accepted or not dlg.chosen() or dlg.chosen() == current:
            return False
        self.editor.run(sky_command(self.editor.doc, dlg.chosen()))
        if self.editor.sky_images() is None:
            self.editor.status_message.emit(
                self.tr("Himmel „{0}“ gesetzt, das Spielprofil kennt ihn aber nicht").format(dlg.chosen()))
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

    def free_assets(self) -> FreeAssetsDialog:
        if getattr(self, "free_assets_dialog", None) is None:
            self.free_assets_dialog = FreeAssetsDialog(self.editor, parent=self)
        self.free_assets_dialog.show()
        self.free_assets_dialog.raise_()
        return self.free_assets_dialog

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
        doc, cordon = self.compiler.build_doc()
        seal = self.seal.check_now() if cordon is None else check_seal(doc)
        warnings = []
        if cordon is not None:
            warnings.append(LogLine(self.tr(
                "Bereich (Cordon) aktiv: Es wird nur gebaut, was darin liegt ({0} Objekte außerhalb weggelassen). "
                "Ganze Map: Testen → Nur Bereich bauen ausschalten.").format(cordon.dropped), Level.WARNING))
            if not cordon.spawns:
                warnings.append(LogLine(self.tr(
                    "Bereich: Darin liegt kein Spawn. Im Spiel startest du dann nicht im Bereich."), Level.WARNING))
        if not seal.sealed:
            warnings.append(LogLine(
                self.tr("Vorab-Prüfung: {0}. vbsp wird vermutlich ein Leck melden. "
                        "Tipp: Testen → Map mit Skybox umhüllen.").format(describe_seal(doc, seal)),
                Level.WARNING, position=seal.path[0] if seal.path else None))
        zones = collect_zones(doc)
        for problem in zone_problems(zones):
            warnings.append(LogLine(self.tr("Zonen: {0}").format(problem), Level.WARNING))
        if zones and profile.key == "momentum" and momentum_zones(zones) is None:
            warnings.append(LogLine(self.tr(
                "Zonen: Ohne Start- und Zielzone der Hauptstrecke wird keine Momentum-Zonendatei geschrieben."),
                Level.WARNING))
        for ent, problem in prop_problems(doc, self.editor.models):
            warnings.append(LogLine(self.tr("Props: {0}").format(problem), Level.WARNING, position=ent.origin))
        started = self.compiler.start(profile, self.compile_settings, warnings, doc)
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

    def open_portalfile(self, path: str | None = None) -> int:
        if path is None:
            start = self.compiler.plan.portalfile_path if self.compiler.plan else self.settings.value("last_dir", "")
            path, _ = QFileDialog.getOpenFileName(self, self.tr("Portal-Datei laden"), start, "Portale (*.prt)")
        if not path:
            return 0
        try:
            n = load_portalfile(self.editor, Path(path))
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, APP_NAME, str(exc))
            return 0
        self.statusBar().showMessage(self.tr("{0} Portale geladen").format(n), 5000)
        return n

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
        self.tool_dock.setFloating(False)
        self.tool_dock.show()
        self.addDockWidget(Qt.RightDockWidgetArea, self.tool_dock)
        for dock in (self.lib_dock, self.scene_dock, self.sel_dock):
            dock.setFloating(False)
            dock.show()
        self._arrange_left()
        self.mat_dock.setFloating(False)
        self.mat_dock.show()
        self.addDockWidget(Qt.BottomDockWidgetArea, self.mat_dock)
        self.model_dock.setFloating(False)
        self.model_dock.show()
        self.tabifyDockWidget(self.mat_dock, self.model_dock)
        self.mat_dock.raise_()

    def _bottom_tab_switched(self, dock: QDockWidget, visible: bool) -> None:
        """Beim Wechsel der Reiter unten (Materialien, Modelle, Kompilieren) die Höhe behalten:
        Qt nimmt sonst beim ersten Zeigen eines Reiters dessen eigene, viel größere Höhe."""
        if dock.isFloating():
            return
        if not visible:
            if dock.height() > 40:
                self._bottom_height = dock.height()
            return
        QTimer.singleShot(0, lambda: dock.isVisible() and not dock.isFloating()
                          and self.resizeDocks([dock], [self._bottom_height], Qt.Vertical))

    def _initial_dock_sizes(self) -> None:
        self.resizeDocks([self.lib_dock, self.sel_dock], [320, 420], Qt.Vertical)
        # Unten nur so hoch, dass die Ansichten das meiste Platz behalten
        self.resizeDocks([self.mat_dock], [260], Qt.Vertical)

    def _arrange_left(self) -> None:
        """Links oben Bibliothek und Szene als Reiter, darunter, was ausgewählt ist. Erst teilen,
        dann Reiter bilden: Ein Dock in einem Reiter-Stapel lässt sich nicht mehr teilen."""
        self.addDockWidget(Qt.LeftDockWidgetArea, self.lib_dock)
        self.splitDockWidget(self.lib_dock, self.sel_dock, Qt.Vertical)
        self.tabifyDockWidget(self.lib_dock, self.scene_dock)
        self.lib_dock.raise_()
        self.resizeDocks([self.lib_dock, self.sel_dock], [320, 420], Qt.Vertical)

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
        self.resizeDocks([self.tool_dock, self.sel_dock, self.lib_dock, self.scene_dock], [DOCK_MIN_WIDTH] * 4,
                         Qt.Horizontal)
        if not restored:
            self.resizeDocks([self.mat_dock], [260], Qt.Vertical)
            # Szene oben etwas kleiner als das, was ausgewählt ist (erst wenn das Fenster steht)
            QTimer.singleShot(0, self._initial_dock_sizes)
        try:
            self.grid_view.restore_state(json.loads(self.settings.value("viewports", "{}")))
        except (TypeError, ValueError):
            pass
        try:
            speed = int(self.settings.value("camera_speed", 600))
        except (TypeError, ValueError):
            speed = 600
        self.set_camera_speed(speed if speed in self.speed_actions else 600)

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
        self.settings.setValue("clean_exit", "true")
        e.accept()


def _scrollable(widget: QWidget) -> QScrollArea:
    """Panel in eine Scrollfläche: Links liegen zwei Panels übereinander, ohne Scrollbar würde
    die Mindesthöhe des einen das andere zusammendrücken oder das Fenster in die Höhe treiben."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area
