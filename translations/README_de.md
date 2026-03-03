# OMEGA

**Persistenter Speicher für KI-Codierungsagenten.** Dein Agent merkt sich Entscheidungen, lernt aus Fehlern und macht dort weiter, wo er aufgehört hat.

[![PyPI version](https://img.shields.io/pypi/v/omega-memory.svg)](https://pypi.org/project/omega-memory/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![#1 on LongMemEval](https://img.shields.io/badge/LongMemEval-95.4%25_%231_Overall-gold.svg)](https://omegamax.co/benchmarks)

[🇺🇸 English](../README.md) | [🇨🇳 中文](README_zh-CN.md) | [🇯🇵 日本語](README_ja.md) | [🇰🇷 한국어](README_ko.md) | [🇧🇷 Português](README_pt-BR.md) | [🇪🇸 Español](README_es.md) | [🇫🇷 Français](README_fr.md) | [🇩🇪 Deutsch](README_de.md) | [🇷🇺 Русский](README_ru.md)

## Schnellstart

```bash
pip3 install omega-memory[server]
omega setup
```

Kompatibel mit **Claude Code** | **Cursor** | **Windsurf** | **Zed** | jedem MCP-Client

---

## Warum reicht CLAUDE.md nicht aus?

Die eingebaute `CLAUDE.md` von Claude Code ist eine einfache Textdatei. Für ein paar Notizen reicht sie, aber sie stößt an ihre Grenzen, wenn:

- **Keine Suche möglich.** Ab 200 Zeilen bist du auf grep angewiesen. OMEGA nutzt semantische Suche (bge-small-en-v1.5 Embeddings + sqlite-vec), um relevante Erinnerungen zu finden, auch wenn die Formulierung anders ist.
- **Kein automatisches Erfassen.** Jede Lektion muss manuell eingetragen werden. OMEGA erkennt Entscheidungen und Debugging-Ergebnisse automatisch.
- **Wächst endlos.** Keine Deduplizierung, kein Verfall, keine Widerspruchserkennung. OMEGA löst Konflikte automatisch, dedupliziert semantisch ähnliche Einträge und lässt veraltete Erinnerungen verfallen.
- **Eine Datei pro Projekt.** Kein projektübergreifendes Lernen. OMEGAs Gedächtnisgraph umfasst deine gesamte Entwicklungshistorie.
- **Kein Checkpoint.** Mitten im Refactoring aufgehört? Kein Weg, weiterzumachen. OMEGA speichert den Aufgabenstatus und setzt exakt an der Unterbrechungsstelle fort.

CLAUDE.md taugt für „immer Tabs verwenden." OMEGA ist für den Fall, dass dein Agent wirklich lernen soll.

## Benchmark

**Platz 1 bei [LongMemEval](https://github.com/xiaowu0162/LongMemEval)** (ICLR 2025) — der akademische Benchmark für Langzeitgedächtnissysteme. 500 Fragen zu Extraktion, Schlussfolgerung, Zeitverständnis und Präferenzverfolgung.

| System | Ergebnis | Anmerkung |
|--------|--------:|----------|
| **OMEGA** | **95.4%** | **Platz 1** |
| Mastra | 94.87% | Platz 2 |
| Zep/Graphiti | 71.2% | -- |

## Hauptfunktionen

- **12 MCP-Tools** — Speichern, Abfragen, Suchen, Checkpoint, Fortsetzen und mehr.
- **Semantische Suche** — bge-small-en-v1.5 + sqlite-vec für schnelles, präzises Retrieval.
- **Automatisches Erfassen & Einblenden** — Hooks erkennen Entscheidungen und zeigen relevante Erinnerungen während der Arbeit.
- **Checkpoint & Fortsetzen** — Aufgabe mittendrin unterbrechen, in der nächsten Sitzung weitermachen.
- **Intelligentes Vergessen** — Zeitverfall, Konfliktlösung, Deduplizierung.
- **100% Lokal, keine API-Keys** — Alle Daten und Verarbeitung bleiben auf deinem Rechner.

## Installation

```bash
pip3 install omega-memory[server]   # von PyPI installieren (inkl. MCP-Server)
omega setup                         # Editor automatisch konfigurieren
omega doctor                        # prüfen, ob alles funktioniert
```

Du nutzt Cursor, Windsurf oder Zed?

```bash
omega setup --client cursor
omega setup --client windsurf
omega setup --client zed
```

## Vergleich

| Funktion | OMEGA | CLAUDE.md | Mem0 |
|----------|:-----:|:---------:|:----:|
| Persistent über Sitzungen | ✅ | ✅ | ✅ |
| Semantische Suche | ✅ | ❌ | ✅ |
| Automatisches Erfassen | ✅ | ❌ | ✅ |
| Widerspruchserkennung | ✅ | ❌ | ❌ |
| 100% lokal (keine API-Keys) | ✅ | ✅ | ❌ |

---

Die vollständige Dokumentation findest du im [englischen README](../README.md).

Website: [omegamax.co](https://omegamax.co) | Docs: [omegamax.co/docs](https://omegamax.co/docs) | Benchmarks: [omegamax.co/benchmarks](https://omegamax.co/benchmarks)

## Lizenz

Apache-2.0
