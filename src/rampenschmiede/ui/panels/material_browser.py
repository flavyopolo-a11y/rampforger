"""Material-Browser: alle Materialien des Spiels als Kacheln, mit Suche und Favoriten.

Klick wählt das aktuelle Material (für neue Brushes), Doppelklick wendet es auf die
Auswahl an. Der Index und die Vorschaubilder werden im Hintergrund geladen, damit das
Fenster auch bei zehntausenden Materialien sofort bedienbar bleibt.
"""
from __future__ import annotations

import json

from PySide6.QtCore import (
    QAbstractListModel,
    QMimeData,
    QModelIndex,
    QObject,
    QRunnable,
    QSettings,
    QSize,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.materials import MaterialLibrary, normalize
from ...core.materials.apply import SCOPE_ALL, SCOPE_ONE, apply_to_objects, expand_scope
from ...render.scene_mesh import material_color
from ..editor import EditorContext

THUMB = 72
FILTERS = (("all", "Alle"), ("favorites", "Favoriten"), ("map", "In dieser Map"), ("recent", "Zuletzt benutzt"),
           ("own", "Eigene Texturen"))
MAX_RECENT = 40
#: Material per Ziehen aus dem Browser in eine Ansicht
MIME_MATERIAL = "application/x-rampenschmiede-material"
SCOPES = ((SCOPE_ALL, "Alle Rampen"), (SCOPE_ONE, "Nur diese Rampe"))


class _Bridge(QObject):
    index_ready = Signal(object, object)      # Bibliothek, Namen
    thumb_ready = Signal(object, str, object)  # Bibliothek, Name, QImage oder None


class _IndexJob(QRunnable):
    def __init__(self, lib: MaterialLibrary, bridge: _Bridge) -> None:
        super().__init__()
        self.lib, self.bridge = lib, bridge

    def run(self) -> None:
        try:
            names = self.lib.names()
        except Exception:  # noqa: BLE001 - kaputte VPKs dürfen den Editor nicht stoppen
            names = []
        self.bridge.index_ready.emit(self.lib, names)


class _ThumbJob(QRunnable):
    def __init__(self, lib: MaterialLibrary, name: str, bridge: _Bridge) -> None:
        super().__init__()
        self.lib, self.name, self.bridge = lib, name, bridge

    def run(self) -> None:
        image = None
        try:
            tex = self.lib.texture(self.name)
        except Exception:  # noqa: BLE001
            tex = None
        if tex is not None:
            image = QImage(tex.rgba, tex.width, tex.height, tex.width * 4, QImage.Format_RGBA8888).copy()
        self.bridge.thumb_ready.emit(self.lib, self.name, image)


def _fit(image: QImage, size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(QColor(30, 31, 34))
    scaled = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p = QPainter(pix)
    p.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    p.end()
    return pix


def _swatch(name: str, size: int) -> QPixmap:
    """Platzhalter, solange (oder wenn) es kein Bild gibt: die Farbe aus den Ansichten."""
    r, g, b = material_color(name)
    pix = QPixmap(size, size)
    pix.fill(QColor(int(r * 255), int(g * 255), int(b * 255)))
    return pix


class MaterialModel(QAbstractListModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.names: list[str] = []
        self.lib: MaterialLibrary | None = None
        self._thumbs: dict[str, QPixmap] = {}
        self._missing: set[str] = set()
        self._pending: set[str] = set()
        self._rows: dict[str, int] = {}
        self.bridge = _Bridge()
        self.bridge.thumb_ready.connect(self._on_thumb)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)

    def set_library(self, lib: MaterialLibrary | None) -> None:
        self.pool.clear()
        self.lib = lib
        self._thumbs.clear()
        self._missing.clear()
        self._pending.clear()

    def set_names(self, names: list[str]) -> None:
        self.beginResetModel()
        self.names = names
        self._rows = {n: i for i, n in enumerate(names)}
        self.endResetModel()

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        base = super().flags(index)
        return base | Qt.ItemIsDragEnabled if index.isValid() else base

    def mimeTypes(self) -> list[str]:
        return [MIME_MATERIAL]

    def mimeData(self, indexes) -> QMimeData:
        mime = QMimeData()
        if indexes:
            name = self.names[indexes[0].row()]
            mime.setData(MIME_MATERIAL, name.encode("utf-8"))
            mime.setText(name)
        return mime

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.names)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        name = self.names[index.row()]
        if role == Qt.DisplayRole:
            return name.rsplit("/", 1)[-1]
        if role == Qt.ToolTipRole:
            info = self.lib.material(name) if self.lib else None
            tex = self.lib.texture(name) if self.lib and name in self._thumbs else None
            size = f"<br>{tex.source_width} × {tex.source_height}" if tex else ""
            keys = f"<br><i>{', '.join(info.keywords)}</i>" if info and info.keywords else ""
            return f"<b>{name}</b>{size}{keys}"
        if role == Qt.UserRole:
            return name
        if role == Qt.DecorationRole:
            pix = self._thumbs.get(name)
            if pix is not None:
                return QIcon(pix)
            if name not in self._missing:
                self._request(name)
            return QIcon(_swatch(name, THUMB))
        return None

    def _request(self, name: str) -> None:
        if self.lib is None or name in self._pending:
            return
        self._pending.add(name)
        self.pool.start(_ThumbJob(self.lib, name, self.bridge))

    def _on_thumb(self, lib: MaterialLibrary, name: str, image: QImage | None) -> None:
        if lib is not self.lib:
            return
        self._pending.discard(name)
        if image is None:
            self._missing.add(name)
            return
        self._thumbs[name] = _fit(image, THUMB)
        row = self._rows.get(name)
        if row is not None:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [Qt.DecorationRole])


class MaterialBrowser(QWidget):
    def __init__(self, editor: EditorContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.settings = QSettings("Rampenschmiede", "Rampenschmiede")
        self._all: list[str] = []
        self._bridge = _Bridge()
        self._bridge.index_ready.connect(self._on_index)
        self._index_pool = QThreadPool(self)
        self._index_pool.setMaxThreadCount(1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Suchen … (z. B. concrete, brick, metal)"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refilter)
        self.filter = QComboBox()
        for key, label in FILTERS:
            self.filter.addItem(self.tr(label), key)
        self.filter.currentIndexChanged.connect(self._refilter)
        self.count_label = QLabel()
        self.count_label.setStyleSheet("color: #888;")
        top.addWidget(self.search, 1)
        top.addWidget(self.filter)
        top.addWidget(self.count_label)
        self.more_button = QToolButton()
        self.more_button.setText(self.tr("Eigene Texturen"))
        self.more_button.setPopupMode(QToolButton.InstantPopup)
        self.more_button.setMenu(QMenu(self.more_button))
        self.more_button.setVisible(False)
        top.addWidget(self.more_button)
        lay.addLayout(top)

        self.model = MaterialModel(self)
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setViewMode(QListView.IconMode)
        self.view.setIconSize(QSize(THUMB, THUMB))
        self.view.setGridSize(QSize(THUMB + 28, THUMB + 34))
        self.view.setUniformItemSizes(True)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setMovement(QListView.Static)
        self.view.setWordWrap(False)
        self.view.setTextElideMode(Qt.ElideMiddle)
        self.view.clicked.connect(self._on_click)
        self.view.doubleClicked.connect(self._on_double_click)
        self.view.setDragEnabled(True)
        self.view.setDragDropMode(QListView.DragOnly)
        self.view.setToolTip(self.tr("Klick wählt, Doppelklick legt auf die Auswahl, "
                                     "Ziehen auf eine Fläche in der 3D-Ansicht legt es genau dort hin"))
        lay.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(48, 48)
        self.current_label = QLabel()
        self.current_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.fav_button = QToolButton()
        self.fav_button.setCheckable(True)
        self.fav_button.setToolTip(self.tr("Favorit"))
        self.fav_button.toggled.connect(self._toggle_favorite)
        self.apply_button = QPushButton(self.tr("Auf Auswahl anwenden"))
        self.apply_button.setToolTip(self.tr("Alle Seiten der ausgewählten Objekte bekommen das Material (Doppelklick)"))
        self.apply_button.clicked.connect(self.apply_to_selection)
        bottom.addWidget(self.preview)
        bottom.addWidget(self.current_label, 1)
        bottom.addWidget(self.fav_button)
        self.scope = QComboBox()
        for key, label in SCOPES:
            self.scope.addItem(self.tr(label), key)
        self.scope.setToolTip(self.tr(
            "Alle Rampen: Eine Textur auf der Surf-Fläche oder den Seiten einer Rampe gilt für alle Rampen "
            "und für neue. Nur diese Rampe: nur die eine, auf die du sie legst."))
        self.scope.setCurrentIndex(max(0, self.scope.findData(self.settings.value("material_scope", SCOPE_ALL))))
        self.scope.currentIndexChanged.connect(self._scope_changed)
        bottom.addWidget(self.scope)
        bottom.addWidget(self.apply_button)
        lay.addLayout(bottom)

        self._scope_changed()
        editor.materials_changed.connect(self.reload)
        editor.current_material_changed.connect(self._show_current)
        self.reload()
        self._show_current(editor.current_material)

    def add_actions(self, actions) -> None:
        """Menü „Eigene Texturen“ füllen (Rampen-Assistent, Import, Texturpakete)."""
        menu = self.more_button.menu()
        for a in actions:
            menu.addSeparator() if a is None else menu.addAction(a)
        self.more_button.setVisible(not menu.isEmpty())

    # ---- Index -------------------------------------------------------------------------
    def reload(self) -> None:
        lib = self.editor.materials
        self.model.set_library(lib)
        self._all = []
        self.model.set_names([])
        if lib is None:
            self.count_label.setText(self.tr("kein Spielprofil"))
            return
        self.count_label.setText(self.tr("lädt …"))
        self._index_pool.start(_IndexJob(lib, self._bridge))

    def _on_index(self, lib: MaterialLibrary, names: list[str]) -> None:
        if lib is not self.editor.materials:
            return
        self._all = names
        self._refilter()
        self._show_current(self.editor.current_material)

    # ---- Filter ------------------------------------------------------------------------
    def _list(self, key: str) -> list[str]:
        try:
            value = json.loads(self.settings.value(key, "[]"))
        except (TypeError, ValueError):
            return []
        return [normalize(v) for v in value if isinstance(v, str)]

    def _store(self, key: str, names: list[str]) -> None:
        self.settings.setValue(key, json.dumps(names))

    def favorites(self) -> list[str]:
        return self._list("material_favorites")

    def recent(self) -> list[str]:
        return self._list("material_recent")

    def _refilter(self) -> None:
        mode = self.filter.currentData()
        if mode == "favorites":
            base = self.favorites()
        elif mode == "recent":
            base = self.recent()
        elif mode == "map":
            base = sorted({normalize(f.material) for s in self.editor.doc.solids() for f in s.faces})
        elif mode == "own":
            base = self.editor.materials.own_names() if self.editor.materials else []
        else:
            base = self._all
        words = self.search.text().lower().split()
        if words:
            base = [n for n in base if all(w in n for w in words)]
        self.model.set_names(base)
        self.count_label.setText(self.tr("{0} Materialien").format(len(base)))

    # ---- Aktionen ----------------------------------------------------------------------
    def _on_click(self, index: QModelIndex) -> None:
        self.editor.set_current_material(index.data(Qt.UserRole))

    def _on_double_click(self, index: QModelIndex) -> None:
        self.editor.set_current_material(index.data(Qt.UserRole))
        self.apply_to_selection()

    def apply_to_selection(self) -> bool:
        material = self.editor.current_material
        face_tool = self.editor.tools.get("face")
        if face_tool is not None and self.editor.tool is face_tool and getattr(face_tool, "faces", None):
            ok = face_tool.apply_material(material)  # type: ignore[attr-defined]
        else:
            ids = expand_scope(self.editor.doc, self.editor.selection, self.editor.material_scope)
            cmd = apply_to_objects(self.editor.doc, ids, material)
            ok = cmd is not None and self.editor.run(cmd)
        if ok:
            self.remember(material)
        else:
            self.editor.status_message.emit(self.tr("Erst Objekte oder Seiten auswählen"))
        return ok

    def _scope_changed(self, *_args) -> None:
        self.editor.material_scope = self.scope.currentData()
        self.settings.setValue("material_scope", self.editor.material_scope)

    def remember(self, material: str) -> None:
        name = normalize(material)
        recent = [n for n in self.recent() if n != name]
        self._store("material_recent", [name, *recent][:MAX_RECENT])

    def _toggle_favorite(self, on: bool) -> None:
        name = normalize(self.editor.current_material)
        favs = [n for n in self.favorites() if n != name]
        if on:
            favs.insert(0, name)
        self._store("material_favorites", favs)
        self.fav_button.setText("★" if on else "☆")
        if self.filter.currentData() == "favorites":
            self._refilter()

    def _show_current(self, material: str) -> None:
        name = normalize(material)
        lib = self.editor.materials
        tex = lib.texture(name) if lib else None
        if tex is not None:
            image = QImage(tex.rgba, tex.width, tex.height, tex.width * 4, QImage.Format_RGBA8888)
            self.preview.setPixmap(_fit(image, 48))
            size = f"  ·  {tex.source_width} × {tex.source_height}"
        else:
            self.preview.setPixmap(_swatch(name, 48))
            size = "" if lib is None or lib.exists(name) else self.tr("  ·  nicht im Spiel gefunden")
        self.current_label.setText(f"<b>{name}</b>{size}")
        fav = name in self.favorites()
        self.fav_button.blockSignals(True)
        self.fav_button.setChecked(fav)
        self.fav_button.blockSignals(False)
        self.fav_button.setText("★" if fav else "☆")
