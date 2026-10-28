# Architektur

Ausführliche Fassung mit Diagramm: [Architekturplan (Claude Doc)](https://claude.ai/artifact/JYrNDBXP6pdBDbwTKrvpDD).
Diese Datei ist die Kurzfassung im Repository und wird mit jeder Etappe fortgeschrieben.

## Schichten

```
UI (PySide6) ──erzeugt Command──▶ CommandStack ──do/undo──▶ MapDocument (core)
     ▲                                                          │
     └──────────────── ChangeSet ◀──────────────────────────────┤
Render (moderngl) ◀──── ChangeSet ──────────────────────────────┘
core/ ──▶ srctools, Spielordner/VPKs, Compile-Tools (vbsp, vvis, vrad, bspzip)
```

- `core/` kennt weder Qt noch OpenGL.
- UI und Renderer lesen das Dokument und schreiben ausschließlich über Commands.
- Nach jedem Command meldet das Dokument ein `ChangeSet` (hinzugefügt, geändert, entfernt).

## Datenmodell

- `MapDocument`: World, Solids, Entities, Groups, Visgroups, Bausteine, EditorState
- `Solid`: Faces mit Ebene (drei Integer-Punkte), Material, U/V-Achsen, Lightmap-Scale, optional Displacement
- `Entity`: Klasse, Keyvalues, Outputs, eigene Brushes
- Stabile interne IDs; VMF-IDs werden beim Import übernommen

## Commands

`Command` (`do`, `undo`, `merge_with`, Beschreibung), `MacroCommand`, unbegrenzter `CommandStack`.
Zieh-Operationen werden zu einem Undo-Schritt verschmolzen.

## Geometrie-Garantien

Brush = Schnitt von Halbräumen, damit immer konvex. Nach jeder Operation werden Ebenenpunkte
und Vertices auf ganze Units gerundet; leere oder entartete Ergebnisse werden verworfen.

## Rendering

Geteilter moderngl-Kontext für 3D- und drei 2D-Ansichten. Räumliche Zellen × Material als
Vertex-Puffer, nur betroffene Zellen werden neu gebaut. Picking per Strahl gegen BVH auf der CPU.

## VMF und Kompilieren

- `core/io/vmf.py`: Import nach `MapDocument`, Export zurück. Unbekannte Blöcke hängen als roher
  Baum am Objekt (`extra["raw"]`) bzw. am Dokument (`extra["vmf_layout"]`) und kommen beim
  Export an dieselbe Stelle. `ExportResult` merkt sich VMF-ID → Objekt für Compiler-Meldungen.
- `core/profiles/`: Spielprofile (`GameProfile`), Steam- und Spielerkennung, Speichern als JSON.
- `core/compile/`: `build_plan` macht aus Profil und Einstellungen eine Schrittliste (VBSP, VVIS,
  VRAD, Kopieren, Starten); `CompileRunner` führt sie blockierend aus und meldet jede Zeile;
  `classify` ordnet Zeilen ein und liest Brush-ID, Entity-Nummer und Position heraus;
  `resolve` macht daraus ein Objekt im Dokument.
- `ui/compile_controller.py` startet den Runner in einem Thread und reicht alles per Qt-Signal
  an Log-Panel und Fenster weiter.

## Gelände und Detailing

- `core/geometry/displacement.py`: `dispinfo` lesen und schreiben, Punkte wie vbsp ausrechnen,
  Pinsel-Schritte, Nähte schließen, Strahl-Treffer. Alles mit numpy, ohne Qt.
- `core/terrain.py`: Brushes umwandeln, Striche über mehrere Brushes, Nähte samt Nachbarn.
- `core/surf/terrain_templates.py`: Gelände-Vorlagen (Welt-Brushes in Kacheln).
- `core/models/scatter.py`: Detail-Kits als Namensmuster, Boden suchen, Props streuen.
- `ui/tools/terrain_tool.py`, `ui/tools/scatter_tool.py`: die Werkzeuge, Optionen in
  `ui/panels/tool_options.py`.

## Ordnen und Ecken

- `core/geometry/vertex_edit.py`: Ecken und Kanten, Ecken verschieben (Hülle neu, Texturen erben).
- `core/organize.py`: Gruppen, An Entity binden, Zur Welt, Mehrfach kopieren, Auswahl ans Raster.
- `core/commands/base.py` `Deferred`: Undo-Schritt aus Teilen, die erst beim Ausführen gebaut werden.
- `ui/tools/vertex_tool.py` (Shift+V), Dialoge in `ui/dialogs/organize_dialogs.py`.

## Prüfen und Suchen

- `core/validation/problems.py`: alle Prüfungen von „Probleme suchen“, je mit Objekten und Reparatur.
- `core/search.py`: Suchen und Ersetzen, Gehe zu ID.
- `ui/dialogs/problems_dialog.py`, `ui/dialogs/find_dialog.py`, `ui/tools/measure_tool.py`.

## Komfort

- `core/attach.py`: Zonen auf ihrem Block (anpassen, folgen).
- `core/pillars.py`: Stützen unter Rampen.
- `core/geometry/walls.py` und `ui/tools/wall_tool.py`: Wände malen.
- Nach jedem Befehl hängt `EditorContext.run` Folgeänderungen an denselben Undo-Schritt:
  Stützen, Zonen, dann die Hülle des Startraums.

## Vorlagen-Bibliothek

Alle gängigen Rampenarten als parametrische Vorlagen (gerade, Trapez, Pyramide, Kurve,
Banane, S-Kurve, Spirale, Welle, Halfpipe/Rohr, Ski, Gabelung, Transfer, Slide), dazu
Stage-Vorlagen, Terrain-Vorlagen, Detail-Kits und Welt-Stile mit Texturvorschlägen.
Details im Claude Doc, Abschnitt „Vorlagen-Bibliothek“.

## Etappen

1. Fenster, Ansichten, Grundformen, Speichern/Laden
2. VMF-Export, Kompilieren & Testen
3. Rampen-Bibliothek, Surf-/Bhop-Werkzeuge
4. Texturen und Welt-Stile
5. Entities über FGD und I/O
6. Licht
7. Props
8. Displacements und Detailing
9. Map-Prüfung
10. Experten-Werkzeuge
11. Komfort
