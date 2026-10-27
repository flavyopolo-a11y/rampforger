"""Baut dist/Rampenschmiede/Rampenschmiede.exe (Ordner-Modus, startet schneller als eine Einzeldatei)."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent

if __name__ == "__main__":
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
        str(HERE / "rampenschmiede.spec"),
    ], cwd=HERE)
    print("Fertig:", ROOT / "dist" / "Rampenschmiede")
