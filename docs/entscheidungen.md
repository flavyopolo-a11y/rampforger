# Entscheidungslog

Kleine Designentscheidungen, fortlaufend nummeriert. Grundlegende Entscheidungen
werden vorher mit Flavio abgestimmt und hier mit „abgestimmt“ markiert.

| Nr. | Datum | Entscheidung | Begründung |
| --- | --- | --- | --- |
| E1 | 2026-10-27 | `core/` importiert weder PySide6 noch moderngl (per Test geprüft) | Kern ohne GUI testbar |
| E2 | 2026-10-27 | Jede Änderung ist ein Command; UI ändert nie direkt | Unbegrenztes Undo/Redo, Autosave, Recovery aus einer Quelle |
| E3 | 2026-10-27 | Brush = Faces mit Ebene aus drei Integer-Punkten (wie VMF) + gecachte Vertices | Verlustfreier Roundtrip, Konvexität per Definition |
| E4 | 2026-10-27 | Unbekannte VMF-Daten bleiben als rohe KeyValues am Objekt erhalten | Roundtrip ohne Verluste |
| E5 | 2026-10-27 | Bausteine (Rampe, Bhop, Zone) parametrisch (Empfehlung A, Flavios Bestätigung steht aus) | Vorlagen mit Reglern bleiben nachträglich änderbar |
| E6 | 2026-10-27 | Eigenes Projektformat `.rsmap` (JSON, versioniert); VMF als Import/Export | Bausteine, Lesezeichen, Regeln brauchen Platz |
| E7 | 2026-10-27 | srctools für KeyValues/FGD/VPK/VTF/VMT/BSP; eigener VVD/VTX-Leser für Modellvorschau | srctools liefert keine MDL-Meshes |
| E8 | 2026-10-27 | UI-Texte direkt auf Deutsch, aber durchgehend über Qt `tr()` (geändert in Etappe 1) | Deutsch ist die Hauptsprache; weitere Sprachen brauchen nur eine `.ts`-Datei, kein Übersetzungsschritt für Deutsch |
| E9 | 2026-10-27 | Tastenkürzel und Maussteuerung standardmäßig wie Hammer | Profis finden sich sofort zurecht |
| E10 | 2026-10-27 | Paketname `rampenschmiede`, Repository `rampforger` | Produktname bleibt deutsch |
| E11 | 2026-10-27 | Integer-Garantie: Ebenenpunkte immer ganzzahlig; Eckpunkte ganzzahlig bei Grundformen, Verschieben und 90°-Drehungen. Bei freien Winkeln werden drei weit auseinanderliegende Punkte je Fläche gerundet | Beliebige Drehungen haben im Allgemeinen keine ganzzahlige Lösung; so bleibt der Brush konvex und der Winkelfehler minimal |
| E12 | 2026-10-27 | Objekte sind unveränderlich (Copy-on-Write), Commands tauschen alte gegen neue Versionen | Undo ist trivial und fehlerfrei, abgeleitete Geometrie kann am Objekt gecacht werden |
| E13 | 2026-10-27 | Auswahl ist kein Undo-Schritt | Wie in den meisten Editoren; Undo soll Änderungen an der Map zurücknehmen, nicht Klicks |
| E14 | 2026-10-27 | Jede Ansicht hat eigene GPU-Puffer, die Vertex-Daten werden einmal auf der CPU gebaut und geteilt | Robuster als geteilte GL-Objekte zwischen Qt-Kontexten; Zell-Batching folgt in Etappe 11 |
| E15 | 2026-10-27 | 2D-Overlays (Griffe, Maße, Rahmen) mit QPainter über dem OpenGL-Bild | Text und Griffe in Pixelgröße, ohne eigenen Text-Renderer |
| E16 | 2026-10-27 | Brushes neuer Formen bekommen wie in Hammer eine Zufallsfarbe für die 2D-Ansichten; in 3D färbt das Material | Einzelne Brushes sind in 2D leicht zu unterscheiden |
| E17 | 2026-10-27 | Dunkles Fusion-Farbschema mit Orange als Akzentfarbe | Moderner Look, gut lesbar neben den schwarzen 2D-Ansichten |
