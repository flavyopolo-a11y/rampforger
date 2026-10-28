"""Übersetzungen: jeder Text im Code hat Englisch und Russisch, Platzhalter passen."""
import json
import re
import sys
from pathlib import Path

import pytest

from rampenschmiede import i18n

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import i18n_extract  # noqa: E402

TEXTS = i18n_extract.strings()


@pytest.fixture
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("de")


def _shape(text: str) -> tuple:
    """Was eine Übersetzung behalten muss: Platzhalter, HTML-Tags, Zeilenende, Tastenkürzel."""
    return (sorted(re.findall(r"\{[^{}]*\}", text)), sorted(re.findall(r"</?\w+", text)), text.endswith("\n"),
            "&" in text)


@pytest.mark.parametrize("lang", ["en", "ru"])
def test_every_text_is_translated(lang):
    table = i18n.table(lang)
    missing = [t for t in TEXTS if t not in table]
    assert not missing, missing[:10]


@pytest.mark.parametrize("lang", ["en", "ru"])
def test_translations_keep_placeholders_and_markup(lang):
    table = i18n.table(lang)
    wrong = [(de, table[de]) for de in TEXTS if de in table and _shape(de) != _shape(table[de])]
    assert not wrong, wrong[:5]
    # Platzhalter lassen sich auch wirklich einsetzen
    for de in TEXTS:
        if "{0" in de:
            args = [1.5] * 8
            assert table[de].format(*args) is not None


def test_no_stale_entries():
    for lang in ("en", "ru"):
        path = Path(i18n.__file__).parent / "resources" / "i18n" / f"{lang}.json"
        stale = set(json.loads(path.read_text(encoding="utf-8"))) - set(TEXTS)
        assert not stale, sorted(stale)[:10]


def test_tr_follows_the_language(english):
    assert i18n.language() == "en"
    assert i18n.tr("Gerade Rampe") == "Straight ramp"
    assert i18n.tr("gibt es nicht im Katalog") == "gibt es nicht im Katalog"  # fehlt: bleibt deutsch
    assert i18n.tr("") == ""


def test_german_and_unknown_languages():
    assert i18n.table("de") == {}
    assert i18n.set_language("xx") == i18n.DEFAULT
    i18n.set_language("de")
    assert i18n.tr("Gerade Rampe") == "Gerade Rampe"
