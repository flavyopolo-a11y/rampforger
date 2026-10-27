"""Texturpakete verwalten: eigene Ordner mit Materialien, die zusätzlich zum Spiel gelesen werden."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)


def pack_root(folder: str | Path) -> Path:
    """Wählt jemand den materials-Ordner selbst, gilt der Ordner darüber als Paket."""
    p = Path(folder)
    return p.parent if p.name.lower() == "materials" else p


def pack_problem(folder: str | Path) -> str:
    p = Path(folder)
    if not p.is_dir():
        return "Ordner fehlt"
    if not (p / "materials").is_dir():
        return "kein materials-Ordner darin"
    return ""


class TexturePacksDialog(QDialog):
    def __init__(self, packs: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Texturpakete"))
        self.resize(560, 340)
        lay = QVBoxLayout(self)
        intro = QLabel(self.tr(
            "Ein Texturpaket ist ein Ordner mit einem Unterordner „materials“, so wie im Spiel. "
            "Seine Materialien erscheinen im Material-Browser unter „Eigene“ und werden beim Kompilieren "
            "automatisch in die Map gepackt. Pakete weiter unten haben Vorrang."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        self.list = QListWidget()
        row.addWidget(self.list, 1)
        side = QVBoxLayout()
        add = QPushButton(self.tr("Hinzufügen …"))
        add.clicked.connect(self._add)
        self.remove = QPushButton(self.tr("Entfernen"))
        self.remove.clicked.connect(self._remove)
        side.addWidget(add)
        side.addWidget(self.remove)
        side.addStretch(1)
        row.addLayout(side)
        lay.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        for p in packs:
            self.add_pack(p)

    def add_pack(self, folder: str | Path) -> bool:
        root = str(pack_root(folder))
        if root in self.packs():
            return False
        problem = pack_problem(root)
        self.list.addItem(root if not problem else f"{root}   ⚠ {self.tr(problem)}")
        self.list.item(self.list.count() - 1).setData(256, root)
        return True

    def packs(self) -> list[str]:
        return [self.list.item(i).data(256) for i in range(self.list.count())]

    def _add(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self.tr("Texturpaket wählen"))
        if folder:
            self.add_pack(folder)

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))


__all__ = ["TexturePacksDialog", "pack_problem", "pack_root"]
