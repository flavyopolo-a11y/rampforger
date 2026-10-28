"""Sprachen der Oberfläche. Die Texte im Code sind deutsch; `resources/i18n/<sprache>.json`
ordnet jedem deutschen Text die Übersetzung zu (fehlt einer, bleibt er deutsch).

Qt-Texte (`self.tr(...)`) laufen über einen QTranslator, der nur in dieser Tabelle nachschlägt
(der Kontext spielt keine Rolle). Texte außerhalb von Qt-Klassen gehen über `tr(...)` hier.
Die Sprache wird beim Start gewählt; ein Wechsel gilt nach dem Neustart."""
from __future__ import annotations

import json
from importlib import resources

#: Sprachen in der Reihenfolge des Menüs: Kürzel → eigener Name
LANGUAGES = {"en": "English", "de": "Deutsch", "ru": "Русский"}
DEFAULT = "en"
SETTINGS_KEY = "language"

_table: dict[str, str] = {}
_lang = "de"


def table(lang: str) -> dict[str, str]:
    """Übersetzungstabelle einer Sprache (leer für Deutsch und Unbekanntes)."""
    if lang == "de" or lang not in LANGUAGES:
        return {}
    try:
        text = resources.files("rampenschmiede.resources.i18n").joinpath(f"{lang}.json").read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return {}
    data = json.loads(text)
    return {k: v for k, v in data.items() if isinstance(v, str) and v}


def set_language(lang: str) -> str:
    global _table, _lang
    _lang = lang if lang in LANGUAGES else DEFAULT
    _table = table(_lang)
    return _lang


def language() -> str:
    return _lang


def tr(text: str) -> str:
    """Übersetzung eines deutschen Textes in die gewählte Sprache."""
    return _table.get(text, text) if text else text


def N_(text: str) -> str:  # noqa: N802 - übliche Schreibweise für „später übersetzen“
    """Markiert einen Text fürs Übersetzen, ohne ihn jetzt zu übersetzen (Konstanten, die erst
    beim Anzeigen durch `tr` gehen)."""
    return text


def saved_language() -> str:
    from PySide6.QtCore import QSettings

    value = QSettings("Rampenschmiede", "Rampenschmiede").value(SETTINGS_KEY, DEFAULT)
    return value if value in LANGUAGES else DEFAULT


def save_language(lang: str) -> None:
    from PySide6.QtCore import QSettings

    QSettings("Rampenschmiede", "Rampenschmiede").setValue(SETTINGS_KEY, lang)


def install(app, lang: str) -> None:
    """Sprache setzen und Qt-Übersetzer einhängen (auch Qts eigene Texte wie „Abbrechen“)."""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    set_language(lang)

    class _DictTranslator(QTranslator):
        def translate(self, context, source, disambiguation=None, n=-1):  # noqa: ARG002
            return _table.get(source)  # None = keine Übersetzung, Qt nimmt den Text selbst

        def isEmpty(self) -> bool:  # noqa: N802
            return not _table

    app._rs_translators = []  # gegen die Müllabfuhr festhalten
    base = QTranslator(app)
    if base.load(QLocale(lang), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(base)
        app._rs_translators.append(base)
    own = _DictTranslator(app)
    app.installTranslator(own)
    app._rs_translators.append(own)


__all__ = ["DEFAULT", "LANGUAGES", "N_", "install", "language", "save_language", "saved_language", "set_language",
           "table", "tr"]
