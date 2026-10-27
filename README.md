# Rampenschmiede

Desktop-Map-Editor für Windows, spezialisiert auf Surf-, Bhop- und Trick-Maps für
Counter-Strike: Source und Momentum Mod. Ziel: Ein Anfänger baut in 30 Minuten eine
spielbare Surf-Map, ein Profi vermisst keine Funktion aus Hammer.

> **Stand: Etappe 2 von 11** – Fenster, 3D- und 2D-Ansichten, Grundformen, Auswählen,
> Verschieben, Drehen, Skalieren, Undo/Redo, Speichern als `.rsmap`, VMF-Import und -Export
> ohne Verluste, Kompilieren und Testen mit einem Tastendruck (F9) für CS:S und Momentum Mod.

![Rampenschmiede, Etappe 2: Kompilier-Log mit Leck-Spur](docs/bilder/etappe2.png)

## Installation

### Fertige .exe (empfohlen)

Jeder Push baut über GitHub Actions eine Windows-Version:
**Actions → „Tests und Windows-Build“ → letzter Lauf → Artefakt `Rampenschmiede-Windows`**.
ZIP entpacken und `Rampenschmiede.exe` starten. Benötigt eine Grafikkarte mit OpenGL 3.3
(jede GPU der letzten zehn Jahre).

### Aus dem Quellcode

Voraussetzung: Python 3.12.

```powershell
git clone https://github.com/flavyopolo-a11y/rampforger
cd rampforger
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
python -m rampenschmiede            # optional: Pfad zu einer .rsmap-Datei
```

Tests: `pytest` · eigene .exe bauen: `python packaging/build_exe.py` (Ergebnis in `dist/Rampenschmiede`).

## Bedienung

Die Steuerung folgt Hammer, damit Umsteiger sich sofort zurechtfinden. **F1** zeigt alle Tasten.

**Ansichten.** Vier Ansichten: 3D, Oben (X/Y), Vorne (Y/Z), Seite (X/Z). Jede lässt sich über
ihre Kopfzeile umstellen, die Trenner sind verschiebbar. Die 3D-Ansicht kennt die Modi
Schattiert, Flach und Drahtgitter.

| Kamera | |
| --- | --- |
| Rechte Maustaste halten (3D) | Umsehen, dazu W A S D fliegen, Q/E runter/hoch, Shift schneller |
| Z (3D) | Umsehen ein/aus |
| Mausrad | 3D: vor/zurück · 2D: zoomen zum Mauszeiger |
| Mittlere Maustaste oder Leertaste + Ziehen | Ansicht verschieben |
| Strg+E | alle Ansichten auf die Auswahl zentrieren |

**Formen bauen (Shift+B).** Form wählen (Block, Keil, Zylinder, Bogen, Treppe), in einer
2D-Ansicht einen Rahmen aufziehen, in einer zweiten Ansicht die Höhe anpassen, **Enter**.
Schneller: in der 3D-Ansicht auf eine Fläche klicken, der Rahmen sitzt dann direkt darauf.

**Auswählen und Bearbeiten (Shift+S).** Klick wählt aus, Strg+Klick ergänzt, Ziehen auf
leerer Fläche zieht einen Auswahlrahmen auf. Auswahl ziehen verschiebt am Raster, Shift+Ziehen
kopiert. Die weißen Griffe skalieren; ein zweiter Klick auf die Auswahl schaltet auf Drehgriffe
(15°-Schritte, mit Shift frei). Pfeiltasten verschieben um eine Rasterweite.
Exakte Zahlen: Panel „Auswahl“ oder **Strg+M** (Transformieren).

**Entities (Shift+E).** Spawns (CT, T, Momentum), Punkt-, Spot- und Sonnenlicht sowie Cubemaps
setzen. Eigenschaften im Panel „Auswahl“ bearbeiten.

| Weitere Tasten | |
| --- | --- |
| [ / ] | Raster feiner / gröber (1 bis 512) |
| Strg+Z / Strg+Y | Rückgängig / Wiederholen (unbegrenzt) |
| Strg+C / Strg+V / Strg+X / Entf | Kopieren / Einfügen / Ausschneiden / Löschen |
| Strg+L / Strg+I | Spiegeln horizontal / vertikal |
| H / Strg+H / U | Auswahl ausblenden / Rest ausblenden / alles einblenden |
| Strg+S | Speichern als `.rsmap` |
| Strg+Shift+E | Als `.vmf` exportieren |

**Hammer-Maps.** „Öffnen“ liest `.rsmap` und `.vmf`. Beim Import bleibt alles erhalten, auch
was Rampenschmiede noch nicht bearbeiten kann (Displacements, Gruppen, Visgroups, Kameras):
Ein Export ergibt wieder dieselbe Map.

**Kompilieren und testen (F9).** Beim ersten Start sucht Rampenschmiede CS:S und Momentum Mod
in allen Steam-Bibliotheken und legt dafür Spielprofile an (Menü *Testen → Spielprofile*, dort
lässt sich alles von Hand anpassen). F9 öffnet den Dialog: Spiel und Qualität wählen, fertig.

| Qualität | Wofür |
| --- | --- |
| Nur Geometrie | Sekunden. Kein Licht, kein VIS: zum Testen von Rampen und Sprüngen |
| Schnell | Zwischentests mit grobem Licht |
| Normal | Volle Sichtbarkeit und Licht |
| Final | Zum Veröffentlichen: LDR und HDR, weiche Schatten |

Die Map wird in einen Ordner `<Projektname>_kompilieren` neben dem Projekt geschrieben, kompiliert,
in den `maps`-Ordner des Spiels kopiert und das Spiel startet direkt in der Map.
**Strg+F9** kompiliert ohne Dialog mit den letzten Einstellungen.
Das Log unten zeigt die Ausgabe live, Fehler rot, Warnungen gelb. Ein Klick auf eine Meldung
wie „Brush 12: …“ oder ein Leck springt zum betroffenen Objekt. Bei einem Leck zeigt eine rote
Linie in allen Ansichten den Weg von der Entity ins Leere.
Im Experten-Modus (Strg+Shift+X) lassen sich die Parameter von VBSP, VVIS und VRAD frei setzen.

## Dokumentation

- [Architektur](docs/architektur.md)
- [Entscheidungslog](docs/entscheidungen.md)

## Bekannte Grenzen (Etappe 2)

- Displacements werden importiert und wieder exportiert, aber noch als flache Fläche angezeigt
  und sind nicht bearbeitbar (Etappe 7).
- Eigene Inhalte (Texturen, Modelle) werden noch nicht in die BSP gepackt (bspzip folgt mit dem
  Material-Browser in Etappe 4).
- Momentum Mod: App-ID und Ordnernamen sind aus der Doku abgeleitet, der Test auf einem echten
  System steht aus. Falls die Erkennung nichts findet, im Spielprofil die Pfade von Hand setzen.
- Keine Texturen in der Ansicht: Flächen werden je Material einfarbig dargestellt (Etappe 4).
- Entities nur aus einer festen Liste, Lichter ohne Vorschau (Etappe 5 und 6).
- Bei beliebigen Drehwinkeln liegen die Ebenenpunkte auf ganzen Units, einzelne Eckpunkte
  können aber krumm werden (siehe E11). Bei 90°-Schritten und allen Grundformen bleibt alles ganzzahlig.
- Beim Laden sehr großer Maps (10'000 Brushes) dauert der erste Aufbau etwa 3 Sekunden;
  das Feintuning dafür ist Teil von Etappe 11.
- Kopieren per Shift+Ziehen ergibt zwei Undo-Schritte (Kopieren, Verschieben).
- Getestet unter Linux mit Software-OpenGL; der Praxistest auf Windows steht noch aus.
