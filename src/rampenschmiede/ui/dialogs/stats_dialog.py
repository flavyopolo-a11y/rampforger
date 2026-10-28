"""Map-Statistik: Zahlen der Map und wie weit sie von den Grenzen von Source entfernt sind."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...core.model import MapDocument
from ...core.validation.stats import map_stats

LEVEL_COLORS = {"ok": "#3a3", "knapp": "#d80", "zu viel": "#d33"}


class StatsDialog(QDialog):
    def __init__(self, doc: MapDocument, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Map-Statistik"))
        self.resize(560, 470)
        lay = QVBoxLayout(self)
        intro = QLabel(self.tr("Was in der Map steckt und wie viel Source davon erlaubt (BSP-Version 20: CS:S, "
                               "Momentum). Ab 75 % wird es gelb."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.stats = map_stats(doc)
        self.table = QTableWidget(len(self.stats), 3)
        self.table.setHorizontalHeaderLabels([self.tr("Was"), self.tr("Anzahl"), self.tr("Grenze")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for row, st in enumerate(self.stats):
            name = QTableWidgetItem(self.tr(st.label))
            name.setToolTip(st.hint)
            value = QTableWidgetItem(f"{st.value:,}".replace(",", "."))
            value.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if st.limit:
                value.setForeground(QColor(LEVEL_COLORS[st.level]))
                bar = QProgressBar()
                bar.setRange(0, st.limit)
                bar.setValue(min(st.value, st.limit))
                bar.setFormat(f"{st.share * 100:.0f} % von {st.limit:,}".replace(",", "."))
                bar.setToolTip(st.hint)
                self.table.setCellWidget(row, 2, bar)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, value)
        lay.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)


__all__ = ["StatsDialog"]
