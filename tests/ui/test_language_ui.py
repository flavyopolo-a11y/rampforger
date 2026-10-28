"""Sprache der Oberfläche: Qt-Texte gehen über die Tabelle, das Menü merkt die Wahl."""
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QMessageBox

from rampenschmiede import i18n


def test_install_translates_qt_texts(qapp):
    try:
        i18n.install(qapp, "ru")
        assert QCoreApplication.translate("MainWindow", "&Datei") == "&Файл"
        assert QCoreApplication.translate("MainWindow", "nicht übersetzt") == "nicht übersetzt"
    finally:
        for t in qapp._rs_translators:
            qapp.removeTranslator(t)
        i18n.set_language("de")
    assert QCoreApplication.translate("MainWindow", "&Datei") == "&Datei"


def test_language_menu_saves_choice(window, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2])))
    names = [a.text() for a in window.language_menu.actions()]
    assert names == list(i18n.LANGUAGES.values())
    assert window.language_menu.title().endswith("/ Language")
    before = i18n.saved_language()  # die Einstellung liegt nicht im Testordner: hinterher zurücksetzen
    try:
        i18n.save_language("en")
        window.choose_language("ru")
        assert i18n.saved_language() == "ru"
        assert shown and "neu starten" in shown[0]
        window.choose_language("ru")  # schon gewählt: keine zweite Meldung
        assert len(shown) == 1
    finally:
        i18n.save_language(before)
