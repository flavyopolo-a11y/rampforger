"""Stil-Knopf oben: alle Welt-Stile als Bilder, ein Klick wendet den Stil an."""
from rampenschmiede.core.materials.styles import STYLE_BY_KEY, STYLES
from rampenschmiede.core.model import Entity


def test_style_button_lists_all_styles(window):
    gallery = window.style_gallery
    assert gallery.count() == len(STYLES)
    keys = {gallery.item(i).data(0x0100) for i in range(gallery.count())}
    for key in ("neon", "nacht", "eis", "dschungel", "retro", "weltraum", "inferno", "pastell"):
        assert key in keys
    assert window.style_button.menu() is not None


def test_clicking_a_style_applies_it(window):
    gallery = window.style_gallery
    item = next(gallery.item(i) for i in range(gallery.count()) if gallery.item(i).data(0x0100) == "neon")
    gallery.itemClicked.emit(item)
    doc = window.editor.doc
    suns = [o for o in doc.objects() if isinstance(o, Entity) and o.classname == "light_environment"]
    assert suns and suns[0].get("_light") == STYLE_BY_KEY["neon"].sun
    # Ein Undo-Schritt nimmt alles zurück
    window.editor.undo()
    suns = [o for o in window.editor.doc.objects() if isinstance(o, Entity) and o.classname == "light_environment"]
    assert all(s.get("_light") != STYLE_BY_KEY["neon"].sun for s in suns)
