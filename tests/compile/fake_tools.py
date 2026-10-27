"""Attrappen für vbsp, vvis und vrad: kleine Python-Skripte mit steuerbarem Verhalten.

Verhalten steht in behaviour.json im bin-Ordner, z. B.
{"vbsp": {"leak": true, "lines": ["Brush 2: WARNING"], "code": 0, "sleep": 0}}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from rampenschmiede.core.profiles import GameProfile

SCRIPT = r'''
import json, sys, time, pathlib
tool = {tool!r}
here = pathlib.Path({bindir!r})
cfg = json.loads((here / "behaviour.json").read_text()).get(tool, {{}})
args = sys.argv[1:]
base = pathlib.Path(args[-1])
with open(here / "calls.log", "a") as log:
    log.write(json.dumps([tool, args]) + "\n")
print(f"{{tool}}.exe fake (args: {{len(args)}})", flush=True)
sys.stdout.write("0...1...2...")
sys.stdout.flush()
time.sleep(cfg.get("sleep", 0))
print("...10", flush=True)
for line in cfg.get("lines", []):
    print(line, flush=True)
if tool == "vbsp":
    if cfg.get("leak"):
        print("**** leaked ****", flush=True)
        print("Entity info_player_counterterrorist (64.00 64.00 32.00) leaked!", flush=True)
        base.with_suffix(".lin").write_text("64 64 32\n64 64 -100\n0 0 -4000\n")
    else:
        base.with_suffix(".prt").write_text("PRT1\n")
    if not cfg.get("no_bsp"):
        base.with_suffix(".bsp").write_bytes(b"VBSP")
sys.exit(cfg.get("code", 0))
'''


def make_tools(root: Path, behaviour: dict | None = None) -> Path:
    bindir = root / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    (bindir / "behaviour.json").write_text(json.dumps(behaviour or {}))
    for tool in ("vbsp", "vvis", "vrad"):
        script = bindir / f"{tool}_fake.py"
        script.write_text(SCRIPT.format(tool=tool, bindir=str(bindir)))
        if sys.platform == "win32":
            (bindir / f"{tool}.bat").write_text(f'@"{sys.executable}" "{script}" %*\r\n')
        else:
            exe = bindir / tool
            exe.write_text(f"#!{sys.executable}\n" + script.read_text())
            exe.chmod(0o755)
    return bindir


def set_behaviour(bindir: Path, behaviour: dict) -> None:
    (bindir / "behaviour.json").write_text(json.dumps(behaviour))


def calls(bindir: Path) -> list:
    log = bindir / "calls.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def fake_profile(root: Path, behaviour: dict | None = None) -> GameProfile:
    bindir = make_tools(root, behaviour)
    game = root / "game" / "cstrike"
    game.mkdir(parents=True, exist_ok=True)
    (game / "gameinfo.txt").write_text('"GameInfo" {}')
    return GameProfile(key="css", name="Test", game_dir=str(game), bin_dir=str(bindir),
                       game_exe="", app_id=240, steam_exe="", launch_via_steam=False)
