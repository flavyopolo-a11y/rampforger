"""Spielprofile: Erkennung in einer nachgebauten Steam-Installation."""
from pathlib import Path

from rampenschmiede.core.profiles import (
    GameProfile,
    ProfileStore,
    detect_profiles,
    library_folders,
)


def touch(p: Path, text: str = "") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def fake_steam(tmp_path: Path) -> Path:
    """Steam mit zwei Bibliotheken: CS:S in der Haupt-, Momentum in der zweiten."""
    root = tmp_path / "Steam"
    lib2 = tmp_path / "Games" / "SteamLibrary"
    touch(root / "steam.exe")
    lib2_escaped = str(lib2).replace("\\", "\\\\")
    root_escaped = str(root).replace("\\", "\\\\")
    touch(root / "steamapps" / "libraryfolders.vdf", f'''"libraryfolders"
{{
	"0"
	{{
		"path"		"{root_escaped}"
		"apps" {{ "240" "1" }}
	}}
	"1"
	{{
		"path"		"{lib2_escaped}"
		"apps" {{ "1802710" "1" }}
	}}
}}
''')
    css = root / "steamapps" / "common" / "Counter-Strike Source"
    touch(css / "cstrike" / "gameinfo.txt", '"GameInfo" { game "Counter-Strike Source" }')
    touch(css / "cstrike_win64.exe")
    touch(css / "hl2.exe")
    for tool in ("vbsp", "vvis", "vrad", "bspzip"):
        touch(css / "bin" / f"{tool}.exe")
    touch(css / "bin" / "cstrike.fgd")
    touch(css / "bin" / "base.fgd")

    mom = lib2 / "steamapps" / "common" / "Momentum Mod Playtest"
    touch(mom / "momentum" / "gameinfo.txt", '"GameInfo" { game "Momentum Mod" }')
    touch(mom / "momentum.exe")
    for tool in ("vbsp", "vvis", "vrad"):
        touch(mom / "bin" / "win64" / f"{tool}.exe")
    touch(mom / "bin" / "momentum.fgd")
    return root


def test_library_folders(tmp_path):
    root = fake_steam(tmp_path)
    libs = library_folders(root)
    assert libs[0] == root
    assert libs[1] == tmp_path / "Games" / "SteamLibrary"


def test_detect_finds_both_games(tmp_path):
    root = fake_steam(tmp_path)
    profiles = {p.key: p for p in detect_profiles([root])}
    assert set(profiles) == {"css", "momentum"}

    css = profiles["css"]
    assert css.app_id == 240
    assert Path(css.game_dir).name == "cstrike"
    assert Path(css.bin_dir).name == "bin"
    assert Path(css.game_exe).name == "cstrike_win64.exe"
    assert [Path(f).name for f in css.fgds] == ["cstrike.fgd"]
    assert css.launch_via_steam and Path(css.steam_exe).name == "steam.exe"
    assert css.problems() == []
    assert css.tool_path("bspzip") is not None

    mom = profiles["momentum"]
    assert Path(mom.bin_dir).parts[-2:] == ("bin", "win64")
    assert Path(mom.game_exe).name == "momentum.exe"
    assert [Path(f).name for f in mom.fgds] == ["momentum.fgd"]
    assert mom.problems() == []


def test_problems_name_what_is_missing(tmp_path):
    p = GameProfile(key="custom", name="Leer", launch_via_steam=False)
    problems = p.problems()
    assert "Spielordner mit gameinfo.txt fehlt" in problems
    assert "vbsp nicht gefunden" in problems
    assert "Spiel-Exe fehlt zum Starten" in problems


def test_no_steam_means_no_profiles(tmp_path):
    assert detect_profiles([tmp_path]) == []


def test_store_roundtrip_and_merge(tmp_path):
    root = fake_steam(tmp_path)
    store = ProfileStore()
    assert store.merge_detected(detect_profiles([root])) == 2
    assert store.active == "Counter-Strike: Source"
    store.profiles[0].launch_args = "-novid -windowed"
    path = tmp_path / "cfg" / "profiles.json"
    store.save(path)
    again = ProfileStore.load(path)
    assert again.to_dict() == store.to_dict()
    # Erneute Erkennung überschreibt nichts und doppelt nichts
    assert again.merge_detected(detect_profiles([root])) == 0
    assert again.profiles[0].launch_args == "-novid -windowed"
    assert again.active_profile().name == "Counter-Strike: Source"


def test_store_load_tolerates_missing_or_broken_file(tmp_path):
    assert ProfileStore.load(tmp_path / "fehlt.json").profiles == []
    bad = touch(tmp_path / "kaputt.json", "{nicht json")
    assert ProfileStore.load(bad).profiles == []
