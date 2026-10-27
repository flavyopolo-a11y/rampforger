"""Rampen-Assistent, Playerclip-Schalter, Textur-Import und Texturpakete."""
from PIL import Image

from rampenschmiede.core.blocks import block_info, is_clip_member
from rampenschmiede.core.commands import AddObjects, solids_from_faces
from rampenschmiede.core.geometry import primitives
from rampenschmiede.core.materials.theme import get_theme
from rampenschmiede.ui.dialogs.ramp_assistant import AssistantChoice, RampAssistant
from rampenschmiede.ui.dialogs.texture_packs import TexturePacksDialog, pack_problem, pack_root
from rampenschmiede.ui.paths import textures_dir

BLUE = (20, 60, 200)
WHITE = (240, 240, 240)
GREY = (100, 100, 100)


def _wall(window):
    s = solids_from_faces(window.editor.doc, primitives.block((0, 0, -64), (512, 512, 0)))[0]
    window.editor.run(AddObjects([s]))
    return s


def test_assistant_dialog_returns_choice(qtbot):
    dlg = RampAssistant(AssistantChoice(WHITE, BLUE, GREY, clip=False), has_selection=False)
    qtbot.addWidget(dlg)
    assert not dlg.selection.isEnabled()
    choice = dlg.choice()
    assert (choice.ramp, choice.lines, choice.wall, choice.clip) == (WHITE, BLUE, GREY, False)
    dlg.set_colors(BLUE, WHITE, GREY)
    assert dlg.choice().ramp == BLUE
    assert not dlg.preview.pixmap().isNull()


def test_assistant_colors_map_and_new_ramps(window):
    ramp_id = window.library.insert("gerade", (0, 0, 0))
    wall = _wall(window)
    assert window.apply_ramp_colors(AssistantChoice(WHITE, BLUE, GREY))
    doc = window.editor.doc
    theme = get_theme(doc)
    assert theme.ramp.startswith("RAMPENSCHMIEDE/RAMPE_")
    assert window.editor.materials.is_own(theme.ramp)
    values = block_info(doc.get(ramp_id))["values"]
    assert values["mat_surf"] == theme.ramp and values["mat_seite"] == theme.ramp_side
    assert {f.material for f in doc.get(wall.id).faces} == {theme.wall}
    assert (textures_dir() / "materials" / f"{theme.ramp.lower()}.vtf").is_file()
    # Neue Rampen übernehmen die Farben
    new_id = window.library.insert("gerade", (0, 2048, 0))
    assert block_info(doc.get(new_id))["values"]["mat_surf"] == theme.ramp
    # Alles ist ein Undo-Schritt (plus das Einfügen)
    window.editor.undo()
    window.editor.undo()
    assert not get_theme(doc).is_set()
    assert block_info(doc.get(ramp_id))["values"]["mat_surf"] != theme.ramp


def test_assistant_selection_only_keeps_walls(window):
    a = window.library.insert("gerade", (0, 0, 0))
    b = window.library.insert("gerade", (0, 2048, 0))
    wall = _wall(window)
    window.editor.set_selection({a})
    window.apply_ramp_colors(AssistantChoice(WHITE, BLUE, GREY, walls=False, only_selection=True))
    doc = window.editor.doc
    theme = get_theme(doc)
    assert block_info(doc.get(a))["values"]["mat_surf"] == theme.ramp
    assert block_info(doc.get(b))["values"]["mat_surf"] != theme.ramp
    assert all(f.material != theme.ramp_side for f in doc.get(wall.id).faces)


def test_playerclip_toggle(window):
    root = window.library.insert("gerade", (0, 0, 0))
    doc = window.editor.doc
    assert window.act_ramp_clip.isChecked()
    assert any(is_clip_member(s) for s in doc.attached([root]))
    window.act_ramp_clip.trigger()
    assert not window.act_ramp_clip.isChecked()
    assert block_info(doc.get(root))["values"]["kollision"] == "detail"
    assert not any(is_clip_member(s) for s in doc.attached([root]))
    # Neue Rampen ohne Clip
    other = window.library.insert("gerade", (0, 2048, 0))
    assert block_info(doc.get(other))["values"]["kollision"] == "detail"
    window.editor.undo()
    window.editor.undo()
    assert window.act_ramp_clip.isChecked()
    assert block_info(doc.get(root))["values"]["kollision"] == "clip"


def test_import_texture(window, tmp_path):
    img = tmp_path / "Mein Bild.png"
    Image.new("RGB", (300, 200), (200, 10, 10)).save(img)
    names = window.import_texture([str(img)])
    assert names == ["rampenschmiede/mein_bild"]
    assert window.editor.current_material == "RAMPENSCHMIEDE/MEIN_BILD"
    assert window.editor.materials.is_own("rampenschmiede/mein_bild")
    tex = window.editor.materials.texture("rampenschmiede/mein_bild")
    assert (tex.source_width, tex.source_height) == (256, 128)


def test_import_rejects_broken_file(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Ok))
    bad = tmp_path / "kaputt.png"
    bad.write_bytes(b"kein bild")
    assert window.import_texture([str(bad)]) == []


def test_texture_packs(window, tmp_path, qtbot):
    pack = tmp_path / "paket"
    (pack / "materials" / "paket").mkdir(parents=True)
    (pack / "materials" / "paket" / "boden.vmt").write_text('"LightmappedGeneric" { "$basetexture" "paket/boden" }')
    assert pack_root(pack / "materials") == pack
    assert pack_problem(pack) == ""
    assert pack_problem(tmp_path / "fehlt") == "Ordner fehlt"
    dlg = TexturePacksDialog([], window)
    qtbot.addWidget(dlg)
    assert dlg.add_pack(pack / "materials")
    assert not dlg.add_pack(pack)
    window.set_texture_packs(dlg.packs())
    assert window.texture_packs() == [str(pack)]
    assert window.editor.materials.exists("paket/boden")
    assert window.editor.materials.is_own("paket/boden")
