"""Bibliothek: Einfügen, Regler eines Bausteins ändern, Auswahl als Ganzes."""
from PySide6.QtCore import Qt

from rampenschmiede.core.blocks import MEMBER_KEY, block_info
from rampenschmiede.core.model import Entity


def _select_template(panel, key):
    tree = panel.tree
    for i in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(i)
        for j in range(group.childCount()):
            if group.child(j).data(0, Qt.UserRole) == key:
                tree.setCurrentItem(group.child(j))
                return
    raise AssertionError(key)


def test_insert_and_edit_block(window):
    panel = window.library
    _select_template(panel, "kurve")
    panel._fields["bogen"][2](30.0)  # Wert für das nächste Einfügen
    panel.insert_current()
    doc = window.editor.doc
    (root,) = [o for o in doc.objects() if isinstance(o, Entity)]
    assert window.editor.selection == {root.id}
    assert block_info(root)["values"]["bogen"] == 30
    assert len(doc.children(root.id)) == 12
    assert "Surf-Winkel" in panel.angle_label.text() and "✓" in panel.angle_label.text()

    # Regler am ausgewählten Baustein: sofort neu gebaut, mehrere Schritte = ein Undo
    assert panel.box.title().startswith("Baustein")
    before = len(window.editor.stack)
    panel._fields["bogen"][2](45.0)
    panel._fields["bogen"][2](60.0)
    assert len(doc.children(root.id)) == 24
    assert len(window.editor.stack) == before + 1
    assert window.editor.selection == {root.id}
    window.editor.undo()
    assert len(doc.children(root.id)) == 12
    assert panel._fields["bogen"][1]() == 30

    # Zu flach: Warnung im Panel
    panel._fields["winkel"][2](35.0)
    assert "Zu flach" in panel.angle_label.text()

    # Richtung ändern dreht den Baustein (neu erzeugt)
    panel._fields["_yaw"][2](90.0)
    assert block_info(doc.get(root.id))["placement"][3] == 90


def test_clicking_clip_selects_whole_block(window):
    from rampenschmiede.ui.tools.base import selection_root

    window.library.insert("gerade", (0, 0, 0))
    doc = window.editor.doc
    (root,) = [o for o in doc.objects() if isinstance(o, Entity)]
    clip = next(s for s in doc.solids() if s.extra.get(MEMBER_KEY) == root.id)
    assert selection_root(window.editor, clip) is root
    # Löschen nimmt die Kollision mit
    window.editor.set_selection({root.id})
    window.editor.delete_selection()
    assert len(doc) == 0


def test_drop_point_in_2d_view(window):
    from PySide6.QtCore import QPointF

    top = next(vp for vp in window.grid_view.viewports() if vp.view == "top")
    p = top.drop_point(QPointF(top.width() / 2, top.height() / 2))
    assert p[2] == 0
    window.editor.template_dropped.emit("pyramide", p)
    roots = [o for o in window.editor.doc.objects() if isinstance(o, Entity)]
    assert len(roots) == 1 and block_info(roots[0])["template"] == "pyramide"


def test_duplicate_block_keeps_collision(window):
    window.library.insert("gerade", (0, 0, 0))
    ed = window.editor
    ed.duplicate(ed.selected_objects(), (0, 2048, 0))
    roots = [o for o in ed.doc.objects() if isinstance(o, Entity)]
    assert len(roots) == 2
    for r in roots:
        assert len(ed.doc.attached([r.id])) == 2


def test_surf_wizard_builds_sealed_map(window, qtbot):
    from rampenschmiede.core.templates import SurfMapSettings
    from rampenschmiede.ui.dialogs.surf_wizard import SurfWizard

    dlg = SurfWizard("momentum")
    dlg.stages.setValue(2)
    settings = dlg.settings()
    assert settings.game == "momentum" and settings.stages == 2
    dlg.stages.setValue(12)
    dlg.ramps.setValue(8)
    assert not dlg.buttons.button(dlg.buttons.StandardButton.Ok).isEnabled()
    dlg.close()

    assert window.new_surf_map(SurfMapSettings(game="momentum", stages=2))
    assert window.seal.check_now().sealed
    assert window.editor.stack.is_clean()
    assert any(o.classname == "info_player_start" for o in window.editor.doc.entities())


def test_save_and_insert_own_prefab(window):
    panel = window.library
    panel.insert("gerade", (0, 0, 0))
    path = panel.save_selection_as_prefab("Startrampe")
    assert path is not None and path.exists()
    assert panel.current_key() == "prefab:" + str(path)
    window.editor.set_selection(())
    assert panel.box.title() == "Prefab: Startrampe"
    root = panel.insert(panel.current_key(), (0, 4096, 0))
    ed = window.editor
    assert ed.selection == {root}
    roots = [o for o in ed.doc.objects() if isinstance(o, Entity)]
    assert len(roots) == 2 and all(block_info(r) for r in roots)
    assert ed.doc.bbox([root]).center[1] == 4096
