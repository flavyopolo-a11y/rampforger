"""Alle zu übersetzenden Texte aus dem Quellcode sammeln und fehlende Übersetzungen zeigen.

Gesammelt werden feste Texte als erstes Argument von `tr(...)`, `self.tr(...)`, `N_(...)` und
`self._action(...)` (dort auch der Hinweis), als Schlüsselwort `label=`, `hint=`, `tip=`, `desc=`
… und als Klassen-Attribute `label` und `hint` (Werkzeuge).

    python tools/i18n_extract.py            # Zahl der fehlenden Texte je Sprache
    python tools/i18n_extract.py --missing en > fehlt.json
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "rampenschmiede"
I18N = SRC / "resources" / "i18n"
CALLS = {"tr", "N_", "_action"}
KEYWORDS = {"label", "hint", "tip", "desc", "description", "title", "text", "message", "unit"}
ATTRS = {"label", "hint"}


def _name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def strings(src: Path = SRC) -> dict[str, str]:
    """Text → erste Fundstelle."""
    found: dict[str, str] = {}
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        where = str(path.relative_to(ROOT))

        def add(value: ast.expr | None, line: int, where: str = where) -> None:
            if isinstance(value, ast.IfExp):  # tr("a" if x else "b")
                add(value.body, line)
                add(value.orelse, line)
            elif isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value.strip():
                found.setdefault(value.value, f"{where}:{line}")

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _name(node.func)
                if name in CALLS and node.args:
                    add(node.args[0], node.lineno)
                if name == "_action" and len(node.args) >= 4:
                    add(node.args[3], node.lineno)
                for kw in node.keywords:
                    if kw.arg in KEYWORDS:
                        add(kw.value, node.lineno)
            elif isinstance(node, ast.ClassDef):
                for stmt in node.body:
                    if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ATTRS
                                                            for t in stmt.targets):
                        add(stmt.value, stmt.lineno)
    return found


def load(lang: str) -> dict[str, str]:
    path = I18N / f"{lang}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def missing(lang: str) -> dict[str, str]:
    have = load(lang)
    return {s: where for s, where in strings().items() if not have.get(s)}


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--missing":
        json.dump({s: "" for s in missing(argv[1])}, sys.stdout, ensure_ascii=False, indent=1)
        return 0
    total = len(strings())
    for lang in ("en", "ru"):
        print(f"{lang}: {total - len(missing(lang))}/{total} übersetzt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
