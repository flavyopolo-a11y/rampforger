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

## Etappen

1. Fenster, Ansichten, Grundformen, Speichern/Laden
2. VMF-Export, Kompilieren & Testen
3. Rampen-Generator, Surf-/Bhop-Werkzeuge
4. Texturen
5. Entities über FGD und I/O
6. Licht
7. Props
8. Map-Prüfung
9. Experten-Werkzeuge
10. Komfort
