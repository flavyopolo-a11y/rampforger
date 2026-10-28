"""Freie Assets im Fenster: Liste mit Bildern, Textur laden, Himmel setzen (ohne Netz)."""
from PySide6.QtCore import Qt

from rampenschmiede.core.assets.polyhaven import PolyHaven
from rampenschmiede.ui.dialogs.free_assets import FreeAssetsDialog

from ..assets.fake_polyhaven import FakeNet


def _dialog(window, tmp_path, qtbot, net=None):
    dlg = FreeAssetsDialog(window.editor, PolyHaven(tmp_path / "cache", net or FakeNet()), window)
    qtbot.addWidget(dlg)
    qtbot.waitUntil(lambda: dlg.list.count() == 2)
    return dlg


def _select(dlg, asset_id):
    for i in range(dlg.list.count()):
        if dlg.list.item(i).data(Qt.UserRole) == asset_id:
            dlg.list.setCurrentRow(i)
            return
    raise AssertionError(asset_id)


def test_texture_tab_lists_filters_and_loads(window, tmp_path, qtbot):
    dlg = _dialog(window, tmp_path, qtbot)
    assert dlg.category.findData("brick") > 0
    dlg.search.setText("rock")
    assert [dlg.list.item(i).isHidden() for i in range(2)] == [True, False]
    dlg.search.clear()
    dlg.category.setCurrentIndex(dlg.category.findData("brick"))
    assert [dlg.list.item(i).isHidden() for i in range(2)] == [False, True]
    _select(dlg, "red_brick_03")
    assert "Red Brick 03" in dlg.info.text() and "polyhaven.com/a/red_brick_03" in dlg.info.text()
    dlg.fetch_current()
    qtbot.waitUntil(lambda: dlg.last_result is not None, timeout=10000)
    assert window.editor.current_material.lower() == "rampenschmiede/frei/red_brick_03"
    assert window.editor.materials.exists("rampenschmiede/frei/red_brick_03")


def test_sky_tab_sets_the_map_sky(window, tmp_path, qtbot):
    dlg = FreeAssetsDialog(window.editor, PolyHaven(tmp_path / "cache", FakeNet()), window)
    qtbot.addWidget(dlg)
    dlg.tabs.setCurrentIndex(1)
    qtbot.waitUntil(lambda: dlg.list.count() == 1)
    _select(dlg, "moonless_golf")
    assert "Himmel" in dlg.fetch_btn.text()
    dlg.fetch_current()
    qtbot.waitUntil(lambda: dlg.last_result is not None, timeout=20000)
    assert dict(window.editor.doc.world_keyvalues)["skyname"] == "rs_moonless_golf"
    assert window.editor.sky_images() is not None  # der Editor zeigt den neuen Himmel
    window.editor.undo()
    assert dict(window.editor.doc.world_keyvalues).get("skyname") != "rs_moonless_golf"


def test_offline_shows_a_message(window, tmp_path, qtbot):
    def offline(url):
        raise OSError("keine Verbindung")

    dlg = FreeAssetsDialog(window.editor, PolyHaven(tmp_path / "cache", offline), window)
    qtbot.addWidget(dlg)
    qtbot.waitUntil(lambda: "Keine Verbindung" in dlg.status.text())
    assert dlg.list.count() == 0


def test_menu_entry_opens_the_dialog(window, monkeypatch):
    monkeypatch.setattr(FreeAssetsDialog, "load_list", lambda self: None)
    dlg = window.free_assets()
    assert dlg.isVisible() and window.free_assets() is dlg
    dlg.close()
