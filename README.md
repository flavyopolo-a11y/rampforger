# Rampenschmiede

Desktop-Map-Editor für Windows, spezialisiert auf Surf-, Bhop- und Trick-Maps für
Counter-Strike: Source und Momentum Mod. Ziel: Ein Anfänger baut in 30 Minuten eine
spielbare Surf-Map, ein Profi vermisst keine Funktion aus Hammer.

> **Stand: Etappe 3 von 11** – Fenster, 3D- und 2D-Ansichten, Grundformen, Auswählen,
> Verschieben, Drehen, Skalieren, Undo/Redo, Speichern als `.rsmap`, VMF-Import und -Export
> ohne Verluste, Kompilieren und Testen mit einem Tastendruck (F9) für CS:S und Momentum Mod,
> Startraum mit Dicht-Prüfung, Rampen-Bibliothek mit 20 Vorlagen, deren Regler sich jederzeit
> ändern lassen, eigene Prefabs und der Assistent „Neue Surf-Map“.

![Rampenschmiede, Etappe 3: Rampen-Bibliothek mit Reglern einer Kurve](docs/bilder/etappe3.png)

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
ihre Kopfzeile umstellen, die Trenner sind verschiebbar. Die Ansicht unter der Maus ist orange
umrandet. Die 3D-Ansicht kennt die Modi Texturiert, Schattiert, Flach und Drahtgitter.

**Werkzeuge.** Links stehen die Werkzeuge mit Symbol (Auswahl, Formen, Entity, Seiten). Das aktive
ist orange hinterlegt, oben rechts steht zusätzlich „Werkzeug: …“.

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

**Startraum.** Jede neue Map beginnt mit einem Spawn (für CS:S CT und T, für Momentum
`info_player_start`), einer Sonne und einer dichten Skybox-Hülle von 1024 × 1024 × 512 Units.
F9 kompiliert also sofort ohne Leck. Die sechs Hüllen-Brushes sind normale Brushes: verschieben,
vergrößern oder löschen. *Datei → Neu (leer)* startet ohne Inhalt, *Datei → Neue Maps mit
Startraum* schaltet den Startraum ab.

**Dicht-Prüfung.** Unten rechts steht immer, ob die Map dicht ist („✓ Map ist dicht“ oder
„⚠ Leck: info_player_start ist nicht umschlossen“). Die Prüfung läuft nach jeder Änderung im
Hintergrund, ohne zu kompilieren. Ein Klick darauf zeigt den Weg ins Freie als rote Linie und wählt
die betroffene Entity aus. *Testen → Map mit Skybox umhüllen* legt eine dichte Hülle um alles.
Vor jedem Kompilieren läuft die Prüfung ebenfalls und warnt im Log.

**Rampen-Bibliothek.** Das Panel *Bibliothek* (links) enthält alle Rampen und Spielelemente
als Vorlagen. Doppelklick oder *Einfügen* setzt eine Vorlage in die Mitte der Ansicht von oben,
Ziehen in eine Ansicht setzt sie an die Mausposition (in 3D auf die Fläche unter der Maus).

| Gruppe | Vorlagen |
| --- | --- |
| Rampen | Gerade, Halb (eine Seite), Invertiert, Trapez (flache Kante), Ski (mit Gefälle), Pyramide |
| Kurven | Kurve, Halbe Kurve, Spirale, S-Kurve, Banane (Höhe gewölbt), Welle |
| Spezial | Halfpipe, Rohr, Slide (V-Rinne), Gabelung, Transfer (zwei Rampen nebeneinander) |
| Bhop | Bhop-Blöcke (Reihe, Zickzack, Stufen), Booster (`trigger_push`), Teleporter mit Ziel |

Eine eingefügte Rampe ist ein **Baustein**: Ist sie ausgewählt, zeigt das Panel ihre Regler
(Breite, Surf-Winkel, Lippe, Radius, Bogen, Grad pro Segment, Gefälle, Querschnitt, Richtung,
Anker …). Jede Änderung baut die Rampe sofort neu; mehrere Änderungen am selben Regler sind ein
einziger Undo-Schritt. Darunter steht der tatsächliche Surf-Winkel, mit Warnung unter 45°
(man kann stehen) und über 65° (sehr steil). Ein Klick auf irgendeinen Teil wählt den ganzen
Baustein. *Baustein lösen* macht normale Brushes daraus.

So baut die Bibliothek Rampen, damit es keine Rampbugs durch krumme Geometrie gibt:
- Alle Eckpunkte liegen auf ganzen Units, benachbarte Segmente teilen exakt dieselben Nahtpunkte.
- Kurven drehen höchstens 5° pro Segment (Standard 2,5°), jedes Segment hat eine flache Unterseite.
- Gerade Rampen sind in jeder Richtung exakte Prismen ohne geknickte Flächen.
- Kollision: Playerclip-Brushes in der Welt, sichtbar ist ein `func_brush` („nie fest“).
  Alternativ im Regler *Kollision*: nur `func_detail`.
- Unsichtbare Flächen (Nähte, Unterseite, aneinanderliegende Teile) bekommen Nodraw.

**Zeitnahme-Zonen.** In der Bibliothek unter *Zonen*: Startzone, Zielzone und Stage-Zone,
jeweils mit Größe, Bonus-Nummer bzw. Stage-Nummer. In der Map sind das `trigger_multiple` mit
Namen nach dem `mod_zone`-Standard (`mod_zone_start`, `mod_zone_end`, `mod_zone_checkpoint_2`,
`mod_zone_bonus_1_start` …). CS:S-Server mit bhoptimer erkennen sie automatisch, die Map
läuft also auf CS:S ohne Nacharbeit. Für Momentum schreibt F9 beim Momentum-Profil zusätzlich
die Zonendatei `<map>.json` neben die BSP und nach `maps/zones/local` im Spielordner. Stage 1
ist die Startzone, die erste Stage-Zone ist Stage 2. Vor dem Kompilieren meldet das Log
fehlende Start-/Zielzonen und Lücken in den Nummern.

**Eigene Prefabs.** Auswahl treffen, in der Bibliothek *Als Prefab speichern …*, Namen
eingeben. Das Prefab erscheint unter *Eigene Prefabs* und lässt sich wie jede Vorlage einfügen
oder hineinziehen; Bausteine darin behalten ihre Regler. Rechtsklick löscht ein Prefab.

**Assistent „Neue Surf-Map“ (Strg+Shift+N).** Spiel, Zahl der Stages, Rampen pro Stage,
Rampenart (Gerade, Ski, Banane, Welle, Trapez), Länge, Breite, Surf-Winkel, Lücke und
Höhenstufe wählen. Heraus kommt eine lineare Surf-Map: Startplattform mit Spawn und
Startzone, Stage-Zonen auf den Stage-Plattformen, Rampen, die
nacheinander tiefer liegen, ein Fall-Teleporter unter jeder Stage zurück zu ihrem Anfang, eine
Zielplattform mit Zielzone, Sonne und eine dichte Skybox-Hülle. F9 testet sie sofort. Ist die Strecke zu lang
für Source (über 32768 Units), sagt der Assistent das, bevor er etwas erzeugt.

**Texturen und Materialien.** Der Material-Browser (unten) liest alle Materialien des Spiels aus
dem Spielprofil, auch aus den VPKs, so wie Hammer. Suchen, Favoriten (★), „In dieser Map“ und
„Zuletzt benutzt“ helfen beim Finden. Klick wählt das aktuelle Material, Doppelklick legt es auf
die Auswahl. Neue Formen bekommen das aktuelle Material. Bei Rampen-Bausteinen lassen sich
Surf-Fläche und Seiten getrennt in den Reglern setzen (⇐ übernimmt das aktuelle Material).

**Seiten-Werkzeug (Shift+A).** Wie der Face-Editor in Hammer: in der 3D-Ansicht Seiten anklicken
(Strg+Klick ergänzt), dann rechts Skalierung, Verschiebung, Drehung und Lightmap-Skalierung
einstellen, einpassen oder ausrichten. Shift+Klick legt das aktuelle Material direkt auf eine
Seite, Alt+Klick nimmt das Material einer Seite auf.

**Rampen-Assistent (Strg+Shift+R, Menü *Texturen*).** Farbe der Rampen, der Rampenlinien und
der Wände wählen oder eine fertige Kombination anklicken. Die Rampenschmiede erzeugt daraus
passende Texturen und färbt die ganze Map oder nur die Auswahl in einem Undo-Schritt um. Neue
Rampen bekommen die Farben automatisch. Der Haken „Playerclip auf Rampen“ (auch im Menü
*Texturen*) schaltet die glatte Clip-Hülle für alle Rampen an oder aus.

**Welt-Stile (Menü *Texturen*).** Sonniger Tag, Sonnenuntergang, Nacht, Wüste, Industrie oder
Neon: Ein Klick setzt Himmel, Sonne, Nebel, Wand-Texturen und Rampenfarben der ganzen Map. Hat
das Spiel passende CS:S- oder HL2-Texturen, werden die genommen, sonst erzeugt die Rampenschmiede
sie. **Umfärben per Klick:** Im Seiten-Werkzeug färbt Strg+Shift+Klick das Material dieser Seite
in der ganzen Map in das aktuelle Material um.

**Eigene Texturen.** *Texturen → Bild als Textur importieren* macht aus PNG, JPG, TGA oder BMP
ein Source-Material (VTF und VMT). *Texturen → Texturpakete* bindet eigene Ordner ein, die wie
ein Spielordner einen Unterordner `materials` haben. Eigene Texturen werden beim Kompilieren
mit bspzip in die Map gepackt, sie läuft also auch bei anderen Spielern ohne Zusatz-Download.

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

## Bekannte Grenzen (Etappe 4)

- Bausteine bleiben nur im Projektformat `.rsmap` über Regler änderbar. Im VMF-Export sind es
  normale Brushes.
- Verschieben und Drehen um die Hochachse behalten den Baustein (er wird neu gebaut). Spiegeln,
  Skalieren und Kippen machen normale Brushes daraus.
- Kurven, Spiralen und Wellen mit Gefälle haben fast ebene Flächen, die beim Runden in zwei
  Dreiecke mit winzigem Knick geteilt werden. Das lässt sich mit ganzen Zahlen nicht vermeiden.
- Bei der Gabelung überlappen sich die beiden Äste am Anfang.
- Die Playerclip-Brushes werden in den Ansichten nicht gezeichnet, weil sie genau auf den
  sichtbaren Teilen liegen.
- Texturen werden in der 3D-Ansicht mit höchstens 256×256 Pixeln gezeigt; im Spiel gilt die volle
  Auflösung. Animierte Texturen zeigen das erste Bild.
- Ohne Spielprofil gibt es nur eigene Texturen im Browser.
- Zonen: Den Namen der Momentum-Zonendatei (`maps/zones/local/<map>.json`) sagt die
  Momentum-Doku nicht ausdrücklich, er ist angenommen. Das Format selbst folgt dem Prüfcode von
  Momentum. CS:S-Timer, die Zonen nur aus ihrer Datenbank lesen (nicht bhoptimer), müssen die
  Zonen weiter im Spiel setzen. Checkpoints innerhalb einer Stage gibt es noch nicht.
- Der Assistent baut nur gerade Strecken; Kurven und Sprünge zwischen Stages kommen von Hand
  aus der Bibliothek dazu.

- Die Dicht-Prüfung arbeitet mit einem Raster (8 Units, bei großen Maps gröber). Spalte, die
  schmaler als eine Rasterzelle sind, findet nur vbsp.

- Displacements werden importiert und wieder exportiert, aber noch als flache Fläche angezeigt
  und sind nicht bearbeitbar (Etappe 7).
- Eigene Inhalte (Texturen, Modelle) werden noch nicht in die BSP gepackt (bspzip folgt mit dem
  Material-Browser in Etappe 4).
- Momentum Mod: Kompilieren und Starten ist auf einem echten System getestet. Falls die
  Erkennung nichts findet, im Spielprofil die Pfade von Hand setzen.
- Keine Texturen in der Ansicht: Flächen werden je Material einfarbig dargestellt (Etappe 4).
- Entities nur aus einer festen Liste, Lichter ohne Vorschau (Etappe 5 und 6).
- Bei beliebigen Drehwinkeln liegen die Ebenenpunkte auf ganzen Units, einzelne Eckpunkte
  können aber krumm werden (siehe E11). Bei 90°-Schritten und allen Grundformen bleibt alles ganzzahlig.
- Beim Laden sehr großer Maps (10'000 Brushes) dauert der erste Aufbau etwa 3 Sekunden;
  das Feintuning dafür ist Teil von Etappe 11.
- Kopieren per Shift+Ziehen ergibt zwei Undo-Schritte (Kopieren, Verschieben).
- Getestet unter Linux mit Software-OpenGL; der Praxistest auf Windows steht noch aus.
