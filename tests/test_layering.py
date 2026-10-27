"""Der Kern darf weder Qt noch OpenGL importieren (Entscheidung E1)."""
import pathlib
import re

CORE = pathlib.Path(__file__).parent.parent / "src" / "rampenschmiede" / "core"
FORBIDDEN = re.compile(r"^\s*(from|import)\s+(PySide6|moderngl|rampenschmiede\.(ui|render))\b", re.M)


def test_core_has_no_ui_imports():
    offenders = [p for p in CORE.rglob("*.py") if FORBIDDEN.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
