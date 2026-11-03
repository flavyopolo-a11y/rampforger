"""Easy-Mode-Leiste oben im Fenster: führt nach dem Assistenten durch die nächsten Schritte.

Sie zeigt, was schon erledigt ist (Welt-Stil, Rampentextur, Räume), und für den jetzigen Schritt einen
Satz, was zu tun ist, plus Knöpfe für das Naheliegende: Rampen malen, Wände malen, Farben und Stil
ändern, testen. Beim ersten Start lädt sie zum Easy Mode ein.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QToolBar, QToolButton, QWidget

from ...i18n import N_
from ..icons import ACTIVE, icon

#: Was im jeweiligen Werkzeug zu tun ist (Werkzeugname -> Satz)
TOOL_HINTS = {
    "paint": N_("Zieh in der Ansicht von oben in einem Raum vom Anfang zum Ende einer Rampe, in jede Richtung "
                "(Umschalt: schräg). Für Kurven wählst du links „Kurve“ oder „S-Kurve“. Das rote Ziel schiebst du "
                "ans Ende deiner Strecke."),
    "wall": N_("Klick in der Ansicht von oben Punkt für Punkt, wo die Wand stehen soll. Enter beendet die Wand, "
               "Klick auf den ersten Punkt schließt den Raum."),
    "select": N_("Klick auf eine Rampe, dann stellst du sie links mit Reglern ein. Ziehen verschiebt sie."),
}
DEFAULT_HINT = N_("Wähle oben eine Aktion. F9 startet die Map im Spiel.")
WELCOME = N_("Neu hier? Der Easy Mode führt dich Schritt für Schritt zu deiner ersten Surf-Map.")

DONE_STEPS = (N_("Welt-Stil"), N_("Rampentextur"), N_("Räume"))


class EasyGuideBar(QToolBar):
    """Leiste mit Fortschritt und Knöpfen. `action` meldet, welcher Knopf gedrückt wurde."""

    action = Signal(str)  # start, paint, wall, colors, style, test, close

    def __init__(self, parent=None) -> None:
        super().__init__(self.tr("Easy Mode"), parent)
        self.setObjectName("tb_easy")
        self.setMovable(False)
        self.setIconSize(QSize(18, 18))
        self.setStyleSheet("QToolBar#tb_easy { background: rgba(255,140,40,0.10); border-bottom: 1px solid "
                           "rgba(255,140,40,0.45); spacing: 6px; padding: 3px; }")
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(10)
        title = QLabel(self.tr("Easy Mode"))
        title.setStyleSheet(f"color: {ACTIVE}; font-weight: bold;")
        lay.addWidget(title)
        self.progress = QLabel()
        lay.addWidget(self.progress)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self.hint, 1)
        self.buttons: dict[str, QToolButton] = {}
        for key, text, name in (("start", N_("Easy Mode starten"), "easy"), ("paint", N_("Rampen malen"), "paint"),
                                ("wall", N_("Wände malen"), "wall"), ("colors", N_("Rampenfarben"), "palette"),
                                ("style", N_("Welt-Stil"), "sun"), ("test", N_("Testen (F9)"), "play")):
            b = QToolButton()
            b.setText(self.tr(text))
            b.setIcon(icon(name))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.clicked.connect(lambda _=False, k=key: self.action.emit(k))
            lay.addWidget(b)
            self.buttons[key] = b
        self.buttons["start"].setStyleSheet(f"QToolButton {{ background: {ACTIVE}; color: #111; font-weight: bold; "
                                            "border-radius: 4px; padding: 3px 10px; }")
        close = QToolButton()
        close.setText("×")
        close.setAutoRaise(True)
        close.setToolTip(self.tr("Leiste schließen (Datei → Easy Mode holt sie zurück)"))
        close.clicked.connect(self.hide)
        close.clicked.connect(lambda: self.action.emit("close"))
        lay.addWidget(close)
        self.addWidget(box)
        self.guiding = False
        self.welcome()

    def welcome(self) -> None:
        """Einladung: nur der Start-Knopf."""
        self.guiding = False
        self.progress.setText("")
        self.hint.setText(self.tr(WELCOME))
        for key, b in self.buttons.items():
            b.setVisible(key == "start")

    def guide(self, tool: str = "paint") -> None:
        """Nach dem Assistenten: Stil, Textur und Räume stehen, jetzt malen."""
        self.guiding = True
        done = "  ".join(f"✓ {self.tr(s)}" for s in DONE_STEPS)
        self.progress.setText(f"<span style='color:#6c6'>{done}</span>  <b style='color:{ACTIVE}'>"
                              f"4 {self.tr('Rampen malen')}</b>")
        for key, b in self.buttons.items():
            b.setVisible(key != "start")
        self.show_tool(tool)
        self.show()

    def show_tool(self, tool: str) -> None:
        if self.guiding:
            self.hint.setText(self.tr(TOOL_HINTS.get(tool, DEFAULT_HINT)))
            for key in ("paint", "wall"):
                self.buttons[key].setCheckable(True)
                self.buttons[key].setChecked(key == tool)


__all__ = ["EasyGuideBar", "TOOL_HINTS"]
