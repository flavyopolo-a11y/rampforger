# Entscheidungslog

Kleine Designentscheidungen, fortlaufend nummeriert. Grundlegende Entscheidungen
werden vorher mit Flavio abgestimmt und hier mit „abgestimmt“ markiert.

| Nr. | Datum | Entscheidung | Begründung |
| --- | --- | --- | --- |
| E1 | 2026-10-27 | `core/` importiert weder PySide6 noch moderngl (per Test geprüft) | Kern ohne GUI testbar |
| E2 | 2026-10-27 | Jede Änderung ist ein Command; UI ändert nie direkt | Unbegrenztes Undo/Redo, Autosave, Recovery aus einer Quelle |
| E3 | 2026-10-27 | Brush = Faces mit Ebene aus drei Integer-Punkten (wie VMF) + gecachte Vertices | Verlustfreier Roundtrip, Konvexität per Definition |
| E4 | 2026-10-27 | Unbekannte VMF-Daten bleiben als rohe KeyValues am Objekt erhalten | Roundtrip ohne Verluste |
| E5 | 2026-10-27 | Bausteine (Rampe, Bhop, Zone) parametrisch (Empfehlung A, von Flavio bestätigt) | Vorlagen mit Reglern bleiben nachträglich änderbar |
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
| E18 | 2026-10-27 | VMF-Import übernimmt alles Verstandene ins Modell; Unbekanntes (dispinfo, Gruppen, Visgroups, Kameras, Cordons, unbekannte Keys) bleibt als roher Baum an Ort und Stelle | Export liefert denselben KeyValues-Baum zurück (per Test geprüft), auch über `.rsmap` hinweg |
| E19 | 2026-10-27 | VMF-IDs: importierte Objekte behalten ihre ID, Kopien und neue Objekte bekommen freie Nummern aus einem gemeinsamen Zähler | Wie Hammer; Compiler-Meldungen mit „Brush N“ zeigen auf das richtige Objekt |
| E20 | 2026-10-27 | I/O-Trennzeichen (Komma oder ESC) bleiben je Output wie importiert; neue Outputs mit Komma im Parameter bekommen ESC | Alte Maps bleiben unverändert, neue Outputs sind eindeutig |
| E21 | 2026-10-27 | Beim Kompilieren wird ausgeblendetes mitgebaut | Ausblenden ist eine Ansichtssache: gespielt wird, was gebaut wurde |
| E22 | 2026-10-27 | Kompiliert wird in einem eigenen Ordner neben dem Projekt (`<name>_kompilieren`), nie neben einer importierten VMF | Eine Original-VMF kann so nie überschrieben werden |
| E23 | 2026-10-27 | Voreinstellungen „Nur Geometrie“, „Schnell“, „Normal“, „Final“; eigene Parameter im Experten-Modus | „Nur Geometrie“ baut in Sekunden, ideal zum Testen von Rampen |
| E24 | 2026-10-27 | Bei einem Leck bricht das Kompilieren standardmäßig nach VBSP ab und zeigt die Leck-Spur | Ohne VIS läuft die Map langsam; das Leck zu beheben ist fast immer der richtige nächste Schritt |
| E25 | 2026-10-27 | Spiel standardmäßig über `steam -applaunch <AppID>` starten, alternativ direkt über die Exe | Funktioniert für CS:S und Momentum ohne Wissen über 32/64-Bit-Exes |
| E26 | 2026-10-27 | Spielerkennung über Registry/Standardpfade, `libraryfolders.vdf` und `steamapps/common/<Ordner>/<Mod>/gameinfo.txt`; Compiler in `bin/x64`, `bin/win64` oder `bin` | Deckt alle Steam-Bibliotheken ab; Momentum-App-ID 1802710 und Ordnernamen sind angenommen und im Profil änderbar |
| E27 | 2026-10-27 | Neue Maps beginnen mit Startraum: Spawn je Spiel, Sonne, dichte Skybox-Hülle (abschaltbar) | Wunsch von Flavio: sofort ohne Leck kompilieren können, Hülle danach frei umbauen |
| E28 | 2026-10-27 | Dicht-Prüfung per Raster-Flutung von außen (Zellen ab 8 Units, Brush belegt jede berührte Zelle), live im Hintergrund und vor jedem Kompilieren | Rückmeldung ohne Kompilieren; meldet echte Lecks zuverlässig, übersieht höchstens sehr schmale Spalte |
| E29 | 2026-10-27 | Nur Welt-Brushes dichten ab; Clip-, Trigger-, Hint-, Skip- und Wasser-Brushes sowie alle Brush-Entities nicht | Entspricht dem Verhalten von vbsp |
| E30 | 2026-10-27 | Rampen entstehen als Querschnitt entlang eines Weges. Jedes Segment ist die exakte, ganzzahlig gerechnete konvexe Hülle zweier gerundeter Querschnitte | Alle Ecken ganzzahlig, Nachbarsegmente teilen exakt dieselben Nahtpunkte: die wichtigste Regel gegen Rampbugs |
| E31 | 2026-10-27 | Gerade Wege nutzen eine ganzzahlige Querachse (höchstens 0,25° Abweichung von der gewünschten Richtung) | Gerade Rampen sind in jeder Richtung exakte Prismen ohne Knicke. Bei Kurven mit Gefälle sind leicht verdrehte Flächen unvermeidlich |
| E32 | 2026-10-27 | Ecken von Brushes, deren Ecken genau ihre ganzzahligen Ebenenpunkte sind, werden in ganzen Zahlen berechnet (mit Prüfung auf geschlossenen Körper); sonst Gleitkomma mit Toleranz 0,0001 statt 0,01 | Fast parallele Flächen (Kurvensegmente) ergaben vorher um bis zu 17 Units falsche Ecken oder verschwundene Flächen |
| E33 | 2026-10-27 | Kollision standardmäßig über deckungsgleiche Playerclip-Brushes in der Welt, sichtbar ist ein `func_brush` mit Solidity „nie“; wahlweise nur `func_detail` | Regel aus dem Plan: einfache Welt-Kollision, Optik getrennt |
| E34 | 2026-10-27 | Baustein = Wurzel-Entity mit Vorlage, Reglern und Platzierung in `extra["block"]`; Kollisions-Brushes gehören über `extra["block_of"]` dazu. Ändern tauscht alle Teile in einem Undo-Schritt, die Wurzel behält ihre ID | Auswahl und Verweise bleiben erhalten; Regler-Ziehen verschmilzt zu einem Schritt |
| E35 | 2026-10-27 | Verschieben behält den Baustein, Drehen um Z baut ihn aus den Reglern neu; Spiegeln, Skalieren und Kippen machen normale Brushes daraus | Freies Drehen Punkt für Punkt würde Nähte und ganze Zahlen zerstören |
| E36 | 2026-10-27 | Surf-Winkel-Warnung unter 45° (begehbar) und über 65° (sehr steil), bei Halfpipe und Rohr aus | Unter 45° steht der Spieler; der flache Boden einer Rinne ist gewollt |
| E37 | 2026-10-27 | Beim Drehen wird `angles` nur bei Punkt-Entities (mit `origin`) angepasst | Bei Brush-Entities würde `angles` das Modell im Spiel ein zweites Mal drehen |
