# Entscheidungslog

Kleine Designentscheidungen, fortlaufend nummeriert. Grundlegende Entscheidungen
werden vorher mit Flavio abgestimmt und hier mit „abgestimmt“ markiert.

| Nr. | Datum | Entscheidung | Begründung |
| --- | --- | --- | --- |
| E1 | 2026-10-27 | `core/` importiert weder PySide6 noch moderngl (per Test geprüft) | Kern ohne GUI testbar |
| E2 | 2026-10-27 | Jede Änderung ist ein Command; UI ändert nie direkt | Unbegrenztes Undo/Redo, Autosave, Recovery aus einer Quelle |
| E3 | 2026-10-27 | Brush = Faces mit Ebene aus drei Integer-Punkten (wie VMF) + gecachte Vertices | Verlustfreier Roundtrip, Konvexität per Definition |
| E4 | 2026-10-27 | Unbekannte VMF-Daten bleiben als rohe KeyValues am Objekt erhalten | Roundtrip ohne Verluste |
| E5 | 2026-10-27 | Bausteine (Rampe, Bhop, Zone) parametrisch – **offen, wartet auf Flavio** | Nachträglich änderbar im Einfach-Modus |
| E6 | 2026-10-27 | Eigenes Projektformat `.rsmap` (JSON, versioniert); VMF als Import/Export | Bausteine, Lesezeichen, Regeln brauchen Platz |
| E7 | 2026-10-27 | srctools für KeyValues/FGD/VPK/VTF/VMT/BSP; eigener VVD/VTX-Leser für Modellvorschau | srctools liefert keine MDL-Meshes |
| E8 | 2026-10-27 | UI-Quelltexte englisch über Qt `tr()`, Deutsch als Standardübersetzung | Übliche Qt-Praxis |
| E9 | 2026-10-27 | Tastenkürzel und Maussteuerung standardmäßig wie Hammer | Profis finden sich sofort zurecht |
| E10 | 2026-10-27 | Paketname `rampenschmiede`, Repository `rampforger` | Produktname bleibt deutsch |
