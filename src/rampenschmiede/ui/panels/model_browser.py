"""Modell-Browser: alle Modelle des Spiels als Bildchen, mit Suche, Ordnern und großer Vorschau.

Ein Modell zieht man in eine Ansicht (es wird dort als Prop gesetzt) oder setzt es mit
„In Map setzen“ in die Mitte der Ansichten. Sind Props ausgewählt, tauscht
„Für Auswahl übernehmen“ ihr Modell. Index und Bildchen werden im Hintergrund geladen.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import (
    QAbstractListModel,
    QMimeData,
    QModelIndex,
    QObject,
    QPointF,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ...core.commands import AddObjects, ReplaceObjects
from ...core.model import Entity
from ...core.models.library import LoadedModel, ModelLibrary
from ...core.models.props import (
    PROP_LABELS,
    best_class,
    class_problem,
    is_model_entity,
    new_prop,
)
from ...render.model_preview import render_preview
from ..editor import EditorContext

THUMB = 88
PREVIEW = 180
#: Modell per Ziehen aus dem Browser in eine Ansicht
MIME_MODEL = "application/x-rampenschmiede-modell"
ALL_FOLDERS = "*"
IN_MAP = "map"


class _Bridge(QObject):
    index_ready = Signal(object, object)       # Bibliothek, Namen
    thumb_ready = Signal(object, str, object)  # Bibliothek, Name, QImage oder None


class _IndexJob(QRunnable):
    def __init__(self, lib: ModelLibrary, bridge: _Bridge) -> None:
        super().__init__()
        self.lib, self.bridge = lib, bridge

    def run(self) -> None:
        try:
            names = self.lib.names()
        except Exception:  # noqa: BLE001 - kaputte VPKs dürfen den Editor nicht stoppen
            names = []
        self.bridge.index_ready.emit(self.lib, names)


class _ThumbJob(QRunnable):
    def __init__(self, lib: ModelLibrary, name: str, bridge: _Bridge) -> None:
        super().__init__()
        self.lib, self.name, self.bridge = lib, name, bridge

    def run(self) -> None:
        image = None
        try:
            model = self.lib.load(self.name)
            if model is not None:
                data = render_preview(model, self.lib.materials, THUMB)
                image = QImage(data, THUMB, THUMB, THUMB * 4, QImage.Format_RGBA8888).copy()
        except Exception:  # noqa: BLE001 - ein kaputtes Modell zeigt eben kein Bild
            image = None
        self.bridge.thumb_ready.emit(self.lib, self.name, image)


def short_name(name: str) -> str:
    return name.rsplit("/", 1)[-1][:-4]


def folder_of(name: str) -> str:
    """'models/props_c17/oildrum001.mdl' → 'props_c17'."""
    parts = name.split("/")
    return parts[1] if len(parts) > 2 else ""


class ModelListModel(QAbstractListModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.names: list[str] = []
        self.lib: ModelLibrary | None = None
        self._thumbs: dict[str, QPixmap] = {}
        self._missing: set[str] = set()
        self._pending: set[str] = set()
        self._rows: dict[str, int] = {}
        self.bridge = _Bridge()
        self.bridge.thumb_ready.connect(self._on_thumb)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._placeholder = _placeholder(THUMB)

    def set_library(self, lib: ModelLibrary | None) -> None:
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
        return [MIME_MODEL]

    def mimeData(self, indexes) -> QMimeData:
        mime = QMimeData()
        if indexes:
            name = self.names[indexes[0].row()]
            mime.setData(MIME_MODEL, name.encode("utf-8"))
            mime.setText(name)
        return mime

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.names)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        name = self.names[index.row()]
        if role == Qt.DisplayRole:
            return short_name(name)
        if role == Qt.ToolTipRole:
            return name
        if role == Qt.UserRole:
            return name
        if role == Qt.DecorationRole:
            pix = self._thumbs.get(name)
            if pix is not None:
                return QIcon(pix)
            if name not in self._missing:
                self._request(name)
            return QIcon(self._placeholder)
        return None

    def _request(self, name: str) -> None:
        if self.lib is None or name in self._pending:
            return
        self._pending.add(name)
        self.pool.start(_ThumbJob(self.lib, name, self.bridge))

    def _on_thumb(self, lib: ModelLibrary, name: str, image: QImage | None) -> None:
        if lib is not self.lib:
            return
        self._pending.discard(name)
        if image is None:
            self._missing.add(name)
            return
        self._thumbs[name] = QPixmap.fromImage(image)
        row = self._rows.get(name)
        if row is not None:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [Qt.DecorationRole])


def _placeholder(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(QColor(30, 31, 34))
    p = QPainter(pix)
    p.setPen(QColor(90, 92, 98))
    p.drawRect(size // 4, size // 4, size // 2, size // 2)
    p.end()
    return pix


class ModelPreview(QLabel):
    """Große Vorschau. Ziehen mit der Maus dreht das Modell."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(PREVIEW, PREVIEW)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background: #1e1f22; border: 1px solid #3a3d42;")
        self.setToolTip(self.tr("Ziehen dreht das Modell"))
        self.model: LoadedModel | None = None
        self.lib: ModelLibrary | None = None
        self.yaw, self.pitch, self.skin = 30.0, 20.0, 0
        self._last: QPointF | None = None
        self.setText(self.tr("Kein Modell gewählt"))

    def show_model(self, lib: ModelLibrary | None, model: LoadedModel | None, skin: int = 0) -> None:
        self.lib, self.model, self.skin = lib, model, skin
        self.redraw()

    def redraw(self) -> None:
        if self.model is None or self.lib is None:
            self.setPixmap(QPixmap())
            self.setText(self.tr("Kein Modell gewählt"))
            return
        data = render_preview(self.model, self.lib.materials, PREVIEW - 2, self.yaw, self.pitch, self.skin)
        img = QImage(data, PREVIEW - 2, PREVIEW - 2, (PREVIEW - 2) * 4, QImage.Format_RGBA8888).copy()
        self.setPixmap(QPixmap.fromImage(img))

    def mousePressEvent(self, e: QMouseEvent) -> None:
        self._last = e.position()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._last is None:
            return
        d = e.position() - self._last
        self._last = e.position()
        self.yaw = (self.yaw - d.x() * 0.8) % 360
        self.pitch = max(-85.0, min(85.0, self.pitch + d.y() * 0.6))
        self.redraw()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        self._last = None


class ModelBrowser(QWidget):
    #: Ein Prop wurde gesetzt (ID)
    placed = Signal(int)

    def __init__(self, editor: EditorContext, insert_point: Callable[[], tuple[float, float, float]],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.insert_point = insert_point
        self._all: list[str] = []
        self._lib: ModelLibrary | None = None
        self._bridge = _Bridge()
        self._bridge.index_ready.connect(self._on_index)
        self._index_pool = QThreadPool(self)
        self._index_pool.setMaxThreadCount(1)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        split = QSplitter(Qt.Horizontal)
        lay.addWidget(split)

        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Modell suchen, z. B. tree, rock, barrel …"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refilter)
        row.addWidget(self.search, 2)
        self.folder = QComboBox()
        self.folder.setToolTip(self.tr("Ordner unter models/"))
        self.folder.currentIndexChanged.connect(self._refilter)
        row.addWidget(self.folder, 1)
        left_l.addLayout(row)
        self.model = ModelListModel(self)
        self.view = QListView()
        self.view.setViewMode(QListView.IconMode)
        self.view.setResizeMode(QListView.Adjust)
        self.view.setIconSize(QSize(THUMB, THUMB))
        self.view.setGridSize(QSize(THUMB + 26, THUMB + 30))
        self.view.setUniformItemSizes(True)
        self.view.setWordWrap(True)
        self.view.setMinimumHeight(THUMB + 40)
        self.view.setDragEnabled(True)
        self.view.setDragDropMode(QListView.DragOnly)
        self.view.setModel(self.model)
        self.view.selectionModel().currentChanged.connect(lambda cur, _prev: self._show(cur.data(Qt.UserRole)))
        self.view.doubleClicked.connect(lambda _i: self.use_current())
        left_l.addWidget(self.view, 1)
        self.status = QLabel()
        self.status.setStyleSheet("color: #9aa0a6;")
        left_l.addWidget(self.status)
        split.addWidget(left)

        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(4, 0, 0, 0)
        self.preview = ModelPreview()
        right_l.addWidget(self.preview, 0, Qt.AlignHCenter)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        right_l.addWidget(self.info)
        skin_row = QHBoxLayout()
        skin_row.addWidget(QLabel(self.tr("Skin")))
        self.skin = QSpinBox()
        self.skin.setRange(0, 0)
        self.skin.valueChanged.connect(self._skin_changed)
        skin_row.addWidget(self.skin)
        skin_row.addStretch(1)
        right_l.addLayout(skin_row)
        self.place_btn = QPushButton(self.tr("In Map setzen"))
        self.place_btn.setToolTip(self.tr("Setzt das Modell in die Mitte der Ansichten. Oder einfach in eine Ansicht ziehen."))
        self.place_btn.clicked.connect(self.place_current)
        self.swap_btn = QPushButton(self.tr("Für Auswahl übernehmen"))
        self.swap_btn.setToolTip(self.tr("Ausgewählte Props bekommen dieses Modell"))
        self.swap_btn.clicked.connect(self.apply_to_selection)
        right_l.addWidget(self.place_btn)
        right_l.addWidget(self.swap_btn)
        right_l.addStretch(1)
        # Scrollbar statt Mindesthöhe: sonst drückt die Vorschau den unteren Bereich hoch
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(right)
        scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        split.addWidget(scroll)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)

        editor.materials_changed.connect(self.reload)
        editor.selection_changed.connect(self._update_buttons)
        editor.model_dropped.connect(self.place)
        self.reload()

    def sizeHint(self) -> QSize:
        # So hoch wie der Material-Browser: beim Umschalten der Reiter springt der Bereich nicht
        return QSize(900, 240)

    # ---- Index ----------------------------------------------------------------------------
    def reload(self) -> None:
        lib = self.editor.models
        if lib is self._lib and self._all:
            return
        self._lib = lib
        self.model.set_library(lib)
        self._all = []
        self.preview.show_model(None, None)
        self._update_buttons()
        if lib is None:
            self.model.set_names([])
            self.status.setText(self.tr("Kein Spielprofil: Modelle kommen aus dem Spiel (Einstellungen → Spielprofil)."))
            return
        self.status.setText(self.tr("Lese Modelle …"))
        self._index_pool.start(_IndexJob(lib, self._bridge))

    def wait_for_index(self, msecs: int = 30000) -> None:
        self._index_pool.waitForDone(msecs)

    def _on_index(self, lib: ModelLibrary, names: list[str]) -> None:
        if lib is not self._lib:
            return
        self._all = names
        current = self.folder.currentData()
        self.folder.blockSignals(True)
        self.folder.clear()
        self.folder.addItem(self.tr("Alle Ordner"), ALL_FOLDERS)
        self.folder.addItem(self.tr("In dieser Map"), IN_MAP)
        for f in sorted({folder_of(n) for n in names} - {""}, key=str.lower):
            self.folder.addItem(f, f)
        idx = self.folder.findData(current)
        self.folder.setCurrentIndex(max(0, idx))
        self.folder.blockSignals(False)
        self._refilter()

    def _refilter(self) -> None:
        words = self.search.text().lower().split()
        folder = self.folder.currentData() or ALL_FOLDERS
        if folder == IN_MAP:
            pool = sorted({e.get("model").lower() for e in self.editor.doc.entities() if is_model_entity(e)})
        elif folder == ALL_FOLDERS:
            pool = self._all
        else:
            pool = [n for n in self._all if folder_of(n) == folder]
        names = [n for n in pool if all(w in n for w in words)]
        self.model.set_names(names)
        if self._lib is not None and self._all:
            self.status.setText(self.tr("{0} von {1} Modellen").format(len(names), len(self._all)))

    # ---- Anzeige ----------------------------------------------------------------------------
    def current_name(self) -> str | None:
        idx = self.view.currentIndex()
        return idx.data(Qt.UserRole) if idx.isValid() else None

    def select_name(self, name: str) -> bool:
        row = self.model._rows.get(name.lower())
        if row is None:
            return False
        self.view.setCurrentIndex(self.model.index(row))
        return True

    def _show(self, name: str | None) -> None:
        model = self._lib.load(name) if self._lib is not None and name else None
        self.skin.blockSignals(True)
        self.skin.setRange(0, (model.skin_count - 1) if model else 0)
        self.skin.setValue(0)
        self.skin.blockSignals(False)
        self.preview.show_model(self._lib, model, 0)
        self.info.setText(describe(model, name) if name else "")
        self._update_buttons()

    def _skin_changed(self, value: int) -> None:
        self.preview.skin = value
        self.preview.redraw()

    def _selected_props(self) -> list[Entity]:
        return [o for o in self.editor.selected_objects() if isinstance(o, Entity) and is_model_entity(o)]

    def _update_buttons(self) -> None:
        has = self.current_name() is not None
        self.place_btn.setEnabled(has)
        props = self._selected_props()
        self.swap_btn.setEnabled(has and bool(props))
        self.swap_btn.setText(self.tr("Für Auswahl übernehmen ({0})").format(len(props)) if props
                              else self.tr("Für Auswahl übernehmen"))

    # ---- Aktionen ---------------------------------------------------------------------------
    def use_current(self) -> None:
        """Doppelklick: ausgewählte Props bekommen das Modell, sonst wird es gesetzt."""
        if self._selected_props():
            self.apply_to_selection()
        else:
            self.place_current()

    def place_current(self) -> int | None:
        name = self.current_name()
        return self.place(name, self.insert_point()) if name else None

    def place(self, name: str, point) -> int | None:
        """Prop mit dem Modell an `point` setzen und auswählen."""
        lib = self.editor.models
        model = lib.load(name) if lib is not None else None
        snap = self.editor.snap
        ent = new_prop(name, (snap(point[0]), snap(point[1]), round(point[2])), model, skin=self.skin_for(name))
        ent = ent.replace(id=self.editor.doc.new_id())
        if not self.editor.run(AddObjects([ent], self.tr("Prop setzen"))):
            return None
        self.editor.set_selection({ent.id})
        hint = self.tr(PROP_LABELS[ent.classname]) if ent.classname in PROP_LABELS else ent.classname
        self.editor.status_message.emit(self.tr("{0} gesetzt ({1})").format(short_name(ent.get("model")), hint))
        self.placed.emit(ent.id)
        return ent.id

    def skin_for(self, name: str) -> int:
        return self.skin.value() if name == self.current_name() else 0

    def apply_to_selection(self) -> int:
        """Modell (und Skin) der ausgewählten Props tauschen. Passt die Klasse nicht zum neuen
        Modell (z. B. prop_static mit einem dynamischen Modell), wird sie mit angepasst."""
        name = self.current_name()
        props = self._selected_props()
        if not name or not props:
            return 0
        lib = self.editor.models
        model = lib.load(name) if lib is not None else None
        new = []
        for ent in props:
            e = ent.with_keyvalue("model", name).with_keyvalue("skin", str(self.skin.value()))
            if class_problem(e.classname, model):
                e = e.replace(classname=best_class(model))
            new.append(e)
        self.editor.run(ReplaceObjects(new, self.tr("Modell tauschen")))
        return len(new)


def describe(model: LoadedModel | None, name: str) -> str:
    if model is None:
        return f"<b>{short_name(name)}</b><br><span style='color:#e57373'>Nicht lesbar</span>"
    lo, hi = model.bounds()
    size = " × ".join(str(round(hi[i] - lo[i])) for i in range(3))
    kinds = []
    kinds.append("statisch" if model.static_prop else "nur dynamisch")
    if model.has_physics:
        kinds.append("Physik möglich")
    lines = [f"<b>{short_name(name)}</b>", f"<span style='color:#9aa0a6'>{name}</span>",
             f"Größe {size} Units", f"{model.triangle_count} Dreiecke · {', '.join(kinds)}"]
    if model.skin_count > 1:
        lines.append(f"{model.skin_count} Skins")
    if model.problem:
        lines.append(f"<span style='color:#e5a050'>Nur als Kasten: {model.problem}</span>")
    return "<br>".join(lines)
