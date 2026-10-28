"""Anwendungsstart: OpenGL-Format, Qt-Anwendung, Farbschema, Hauptfenster."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QColor, QPalette, QSurfaceFormat
from PySide6.QtWidgets import QApplication

from . import __version__


def configure_opengl() -> None:
    """Muss vor dem Anlegen der QApplication laufen."""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    fmt.setSamples(4)
    QSurfaceFormat.setDefaultFormat(fmt)
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)


def dark_palette() -> QPalette:
    p = QPalette()
    base = QColor(37, 40, 46)
    window = QColor(45, 48, 55)
    text = QColor(225, 228, 232)
    accent = QColor(255, 140, 40)  # Schmiede-Orange
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, window)
    p.setColor(QPalette.ToolTipBase, QColor(20, 22, 26))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, window)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor(255, 80, 80))
    p.setColor(QPalette.Highlight, accent)
    p.setColor(QPalette.HighlightedText, QColor(20, 20, 20))
    p.setColor(QPalette.Link, accent)
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 120))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 120))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(120, 120, 120))
    return p


def create_app(argv: list[str]) -> QApplication:
    configure_opengl()
    app = QApplication.instance() or QApplication(argv)
    app.setApplicationName("Rampenschmiede")
    app.setOrganizationName("Rampenschmiede")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    from . import i18n

    i18n.install(app, i18n.saved_language())
    return app  # type: ignore[return-value]


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = create_app(argv)
    from .ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    files = [a for a in argv[1:] if not a.startswith("-")]
    if files:
        win.open_path(Path(files[0]))
    return app.exec()
