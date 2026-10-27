import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QSettings  # noqa: E402

from rampenschmiede.app import configure_opengl  # noqa: E402

# Vor dem Anlegen der QApplication durch pytest-qt
configure_opengl()


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    """Rückfragen würden die Tests blockieren: immer verwerfen."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Discard))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: QMessageBox.Ok))


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QCoreApplication.setOrganizationName("RampenschmiedeTest")
    # Spielprofile und Kompilier-Ordner landen im Testordner, Steam wird nicht gesucht
    monkeypatch.setenv("RAMPENSCHMIEDE_DATA_DIR", str(tmp_path / "daten"))
    monkeypatch.setattr("rampenschmiede.ui.main_window.detect_profiles", lambda: [])
    yield


@pytest.fixture
def window(qtbot):
    from rampenschmiede.ui.main_window import MainWindow

    w = MainWindow()
    w.resize(1400, 900)
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    yield w
    w.editor.stack.set_clean()
    w.close()
