"""Startpunkt: python -m rampenschmiede [datei.rsmap]"""
import sys


def main() -> int:
    from .app import run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
