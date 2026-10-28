"""Rampen sehen, bevor man sie baut: Bilder in Bibliothek und Malen-Galerie, Geist in 3D."""
from PySide6.QtCore import Qt

from rampenschmiede.core.attach import ZONE_TEMPLATES
from rampenschmiede.core.blocks import build_block
from rampenschmiede.core.commands import AddObjects
from rampenschmiede.core.scene import SceneIndex, kind_of
from rampenschmiede.core.surf.catalog import CATALOG, Placement
from rampenschmiede.ui.widgets.template_preview import render, template_faces


def _visible_pixels(pixmap):
    img = pixmap.toImage()
    return sum(1 for x in range(0, img.width(), 4) for y in range(0, img.height(), 4)
               if img.pixelColor(x, y).alpha() > 0)


def test_every_template_renders_a_picture(qapp):
    for key in CATALOG:
        faces = template_faces(key)
        assert faces, key
        assert _visible_pixels(render(faces, 96)) > 5, key


def test_clicking_a_ramp_shows_its_picture_and_raises_the_library(window):
    lib = window.library
    window.scene_dock.raise_()
    lib.select_template("kurve")
    assert window.editor.tool is window.editor.tools["paint"]
    assert lib.preview.isVisibleTo(lib) and not lib.preview.pixmap().isNull()
    # Malen bringt die Bibliothek (mit den Reglern) nach vorne
    assert not window.lib_dock.visibleRegion().isEmpty() or window.lib_dock.isVisible()
    # Rechts zeigt das Malen-Werkzeug dieselbe Vorlage groß und in der Galerie markiert
    opts = window.tool_options
    assert opts.currentWidget() is opts._pages["paint"]
    assert opts.paint_gallery.currentItem().data(Qt.UserRole) == "kurve"
    assert opts.paint_name.text() == CATALOG["kurve"].name
    assert not opts.paint_preview.pixmap().isNull()


def test_gallery_click_selects_template_and_ghost_appears_in_3d(window):
    opts = window.tool_options
    gallery = opts.paint_gallery
    item = next(gallery.item(i) for i in range(gallery.count()) if gallery.item(i).data(Qt.UserRole) == "halfpipe")
    gallery.itemClicked.emit(item)
    assert window.library.current_key() == "halfpipe"
    paint = window.editor.tools["paint"]
    # Ohne Mausbewegung steht die Vorschau schon in der Mitte der Ansicht
    assert paint.hover is not None
    tris = paint.tris_3d(None)
    assert tris is not None and len(tris) % 3 == 0 and tris.shape[1] == 6


def test_slider_change_updates_picture(window):
    lib = window.library
    lib.select_template("gerade")
    before = lib.preview.pixmap().toImage()
    widget, _read, write, _label = lib._fields["laenge"]
    write(4096)
    lib._field_changed("laenge")
    assert lib.preview.pixmap().toImage() != before


def test_zones_are_triggers_not_ramps(qapp):
    from rampenschmiede.core.model import MapDocument

    doc = MapDocument()
    key = next(iter(ZONE_TEMPLATES))
    objs, _gen = build_block(doc, key, {}, Placement(0, 0, 0, 0))
    AddObjects(objs).do(doc)
    folders = SceneIndex().folders(doc)
    assert objs[0].id in folders["trigger"]
    assert objs[0].id not in folders.get("rampen", [])
    assert kind_of(doc, objs[0]) == "Trigger"
