"""Freie Assets: Texturen und Himmel von Poly Haven (CC0) durchsuchen und mit einem Klick laden.

Liste, Bilder und Downloads laufen im Hintergrund, das Fenster bleibt bedienbar. Geladene
Texturen erscheinen sofort im Material-Browser und werden das aktuelle Material; ein Himmel
wird zur Skybox umgerechnet und gleich für die Map gesetzt (Strg+Z nimmt das zurück).
"""
from __future__ import annotations

import io
from typing import Any, Callable

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTabBar,
    QVBoxLayout,
)

from ...core.assets.convert import skybox_from_panorama, surfaceprop_for, texture_material
from ...core.assets.polyhaven import ATTRIBUTION, KINDS, Asset, PolyHaven, sky_url, texture_urls
from ...core.materials.styles import sky_command
from ..editor import EditorContext
from ..paths import data_dir, textures_dir

THUMB = 128
#: Kategorien, die oben in der Auswahl stehen, wenn es sie gibt (für Surf-Maps die nützlichsten)
FAVORITE_CATEGORIES = {
    "textures": ("brick", "concrete", "metal", "rock", "wood", "floor", "wall", "terrain", "plaster", "sand"),
    "hdris": ("skies", "night", "sunrise-sunset", "outdoor", "nature", "urban"),
}


class _Bridge(QObject):
    done = Signal(str, object, object)  # Auftrag, Ergebnis, Fehler


class _Job(QRunnable):
    def __init__(self, token: str, work: Callable[[], Any], bridge: _Bridge) -> None:
        super().__init__()
        self.token, self.work, self.bridge = token, work, bridge

    def run(self) -> None:
        try:
            result, error = self.work(), None
        except Exception as exc:  # noqa: BLE001 - Netzfehler, kaputte Bilder: im Fenster melden
            result, error = None, exc
        self.bridge.done.emit(self.token, result, error)


def _thumb(data: bytes) -> QImage:
    img = Image.open(io.BytesIO(data)).convert("RGBA")
    img.thumbnail((THUMB, THUMB))
    return QImage(img.tobytes(), img.width, img.height, img.width * 4, QImage.Format_RGBA8888).copy()


class FreeAssetsDialog(QDialog):
    def __init__(self, editor: EditorContext, source: PolyHaven | None = None, parent=None) -> None:
        super().__init__(parent)
        self.editor = editor
        self.source = source or PolyHaven(data_dir() / "cache" / "polyhaven")
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)
        self.bridge = _Bridge(self)
        self.bridge.done.connect(self._done)
        self._assets: list[Asset] = []
        self._items: dict[str, QListWidgetItem] = {}
        #: Wofür das zuletzt Geladene benutzt wurde: Material- bzw. Himmelsname
        self.last_result: str | None = None
        self.setWindowTitle(self.tr("Freie Assets"))
        self.resize(900, 640)

        lay = QVBoxLayout(self)
        intro = QLabel(self.tr(
            "Freie Texturen und Himmel von <a href='https://polyhaven.com'>Poly Haven</a>. Alles ist CC0: frei "
            "nutzbar, auch kommerziell, ohne Bedingungen. Ein Klick lädt das Asset, wandelt es für Source um und "
            "packt es beim Kompilieren in die Map."))
        intro.setWordWrap(True)
        intro.setOpenExternalLinks(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        self.tabs = QTabBar()
        for kind, label in KINDS.items():
            self.tabs.addTab(self.tr(label))
            self.tabs.setTabData(self.tabs.count() - 1, kind)
        self.tabs.currentChanged.connect(lambda _i: self.load_list())
        row.addWidget(self.tabs)
        self.category = QComboBox()
        self.category.setMinimumWidth(180)
        self.category.currentIndexChanged.connect(lambda _i: self._refilter())
        row.addWidget(self.category)
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("Suchen … (z. B. brick, rock, night)"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _t: self._refilter())
        row.addWidget(self.search, 1)
        lay.addLayout(row)

        self.list = QListWidget()
        self.list.setViewMode(QListView.IconMode)
        self.list.setIconSize(QSize(THUMB, THUMB))
        self.list.setGridSize(QSize(THUMB + 24, THUMB + 36))
        self.list.setResizeMode(QListView.Adjust)
        self.list.setMovement(QListView.Static)
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(True)
        self.list.currentItemChanged.connect(lambda *_a: self._show_current())
        self.list.itemDoubleClicked.connect(lambda _i: self.fetch_current())
        lay.addWidget(self.list, 1)

        bottom = QHBoxLayout()
        self.info = QLabel()
        self.info.setOpenExternalLinks(True)
        self.info.setWordWrap(True)
        bottom.addWidget(self.info, 1)
        self.fetch_btn = QPushButton()
        self.fetch_btn.clicked.connect(self.fetch_current)
        bottom.addWidget(self.fetch_btn)
        close = QPushButton(self.tr("Schließen"))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        lay.addLayout(bottom)
        self.status = QLabel(self.tr(ATTRIBUTION))
        self.status.setStyleSheet("color: #9aa4b2;")
        lay.addWidget(self.status)
        self.load_list()

    # ---- Liste -------------------------------------------------------------------------
    def kind(self) -> str:
        return self.tabs.tabData(self.tabs.currentIndex()) or "textures"

    def load_list(self) -> None:
        kind = self.kind()
        self.list.clear()
        self._items.clear()
        self._assets = []
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem(self.tr("Alle Kategorien"), "")
        self.category.blockSignals(False)
        self.status.setText(self.tr("Liste wird geladen …"))
        self.pool.start(_Job(f"list:{kind}", lambda: (self.source.assets(kind), self.source.categories(kind)),
                             self.bridge))
        self._show_current()

    def _fill(self, assets: list[Asset], categories: list[str]) -> None:
        self._assets = assets
        favs = [c for c in FAVORITE_CATEGORIES.get(self.kind(), ()) if c in categories]
        self.category.blockSignals(True)
        for c in favs + [c for c in categories if c not in favs]:
            self.category.addItem(c, c)
        self.category.blockSignals(False)
        for a in assets:
            item = QListWidgetItem(QIcon(_placeholder()), a.name)
            item.setData(Qt.UserRole, a.id)
            item.setToolTip(", ".join(a.categories))
            self.list.addItem(item)
            self._items[a.id] = item
            if a.thumbnail:
                self.pool.start(_Job(f"thumb:{a.id}", lambda a=a: _thumb(self.source.download(a.thumbnail)),
                                     self.bridge))
        self._refilter()
        self.status.setText(self.tr("{0} Assets · {1}").format(len(assets), self.tr(ATTRIBUTION)))

    def _refilter(self) -> None:
        cat = self.category.currentData() or ""
        text = self.search.text().strip()
        by_id = {a.id: a for a in self._assets}
        for aid, item in self._items.items():
            a = by_id[aid]
            item.setHidden(bool(cat and cat not in a.categories) or bool(text and not a.matches(text)))

    def current(self) -> Asset | None:
        item = self.list.currentItem()
        if item is None:
            return None
        aid = item.data(Qt.UserRole)
        return next((a for a in self._assets if a.id == aid), None)

    def _show_current(self) -> None:
        a = self.current()
        sky = self.kind() == "hdris"
        self.fetch_btn.setText(self.tr("Laden und als Himmel setzen") if sky else self.tr("Laden und als Material wählen"))
        self.fetch_btn.setEnabled(a is not None)
        if a is None:
            self.info.setText(self.tr("Asset anklicken, Doppelklick lädt es."))
            return
        authors = ", ".join(a.authors)
        self.info.setText(f"<b>{a.name}</b>" + (f" · {authors}" if authors else "")
                          + f" · <a href='{a.page}'>{self.tr('Seite')}</a>")

    # ---- Laden -------------------------------------------------------------------------
    def fetch_current(self) -> None:
        a = self.current()
        if a is None:
            return
        self.fetch_btn.setEnabled(False)
        self.status.setText(self.tr("„{0}“ wird geladen und umgewandelt …").format(a.name))
        self.pool.start(_Job(f"fetch:{a.kind}:{a.id}", lambda: self._fetch(a), self.bridge))

    def _fetch(self, a: Asset) -> str:
        """Im Hintergrund: laden und umwandeln. Liefert Material- bzw. Himmelsname."""
        files = self.source.files(a.id)
        root = textures_dir()
        if a.kind == "hdris":
            url = sky_url(files)
            if url is None:
                raise ValueError("Für diesen Himmel gibt es kein Rundum-Bild")
            return skybox_from_panorama(root, a.id, self.source.download(url))
        diffuse, normal = texture_urls(files)
        if diffuse is None:
            raise ValueError("Für diese Textur gibt es kein Farbbild")
        return texture_material(root, a.id, self.source.download(diffuse),
                                self.source.download(normal) if normal else None,
                                surfaceprop_for((*a.categories, *a.tags)))

    def _done(self, token: str, result: Any, error: Exception | None) -> None:
        kind, _, rest = token.partition(":")
        if kind == "list":
            if rest != self.kind():
                return
            if error is not None:
                self.status.setText(self.tr("Keine Verbindung zu Poly Haven: {0}").format(error))
                return
            self._fill(*result)
        elif kind == "thumb":
            item = self._items.get(rest)
            if item is not None and result is not None:
                item.setIcon(QIcon(QPixmap.fromImage(result)))
        elif kind == "fetch":
            self.fetch_btn.setEnabled(self.current() is not None)
            if error is not None:
                self.status.setText(self.tr("Laden fehlgeschlagen: {0}").format(error))
                return
            self._apply(rest.split(":", 1)[0], result)

    def _apply(self, kind: str, name: str) -> None:
        ed = self.editor
        ed.refresh_materials()
        self.last_result = name
        if kind == "hdris":
            ed.run(sky_command(ed.doc, name))
            self.status.setText(self.tr("Himmel „{0}“ gesetzt (Strg+Z nimmt ihn zurück)").format(name))
        else:
            ed.set_current_material(name)
            self.status.setText(self.tr("Material {0} geladen und gewählt").format(name))


def _placeholder() -> QPixmap:
    pix = QPixmap(THUMB, THUMB)
    pix.fill(Qt.darkGray)
    return pix


__all__ = ["FreeAssetsDialog"]
