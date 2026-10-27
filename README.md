# Rampenschmiede

Desktop-Map-Editor für Windows, spezialisiert auf Surf-, Bhop- und Trick-Maps für
Counter-Strike: Source und Momentum Mod. Ziel: Ein Anfänger baut in 30 Minuten eine
spielbare Surf-Map, ein Profi vermisst keine Funktion aus Hammer.

> **Stand:** Grundgerüst. Architekturplan liegt vor, Etappe 1 (Fenster, Ansichten,
> Grundformen, Speichern/Laden) folgt nach Freigabe.

## Installation (Entwicklung)

Voraussetzung: Python 3.12 unter Windows.

```powershell
git clone https://github.com/flavyopolo-a11y/rampforger
cd rampforger
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
python -m rampenschmiede
```

Tests: `pytest`

## Bedienung

Folgt mit Etappe 1.

## Dokumentation

- [Architektur](docs/architektur.md)
- [Entscheidungslog](docs/entscheidungen.md)

## Bekannte Grenzen

- Noch keine Oberfläche, nur Projektgerüst.
- Kompilieren und Spielstart werden in der Entwicklungsumgebung nicht automatisch
  getestet (kein Spiel verfügbar); der Praxistest erfolgt auf Windows.
