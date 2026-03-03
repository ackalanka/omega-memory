# OMEGA

**Memoria persistente para agentes de codificación con IA.** Tu agente recuerda decisiones, aprende de errores y retoma donde lo dejó.

[![PyPI version](https://img.shields.io/pypi/v/omega-memory.svg)](https://pypi.org/project/omega-memory/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![#1 on LongMemEval](https://img.shields.io/badge/LongMemEval-95.4%25_%231_Overall-gold.svg)](https://omegamax.co/benchmarks)

[🇺🇸 English](../README.md) | [🇨🇳 中文](README_zh-CN.md) | [🇯🇵 日本語](README_ja.md) | [🇰🇷 한국어](README_ko.md) | [🇧🇷 Português](README_pt-BR.md) | [🇪🇸 Español](README_es.md) | [🇫🇷 Français](README_fr.md) | [🇩🇪 Deutsch](README_de.md) | [🇷🇺 Русский](README_ru.md)

## Inicio Rápido

```bash
pip3 install omega-memory[server]
omega setup
```

Compatible con **Claude Code** | **Cursor** | **Windsurf** | **Zed** | cualquier cliente MCP

---

## ¿Por qué no usar simplemente CLAUDE.md?

El `CLAUDE.md` integrado en Claude Code es un archivo de texto plano. Funciona para unas pocas notas, pero se queda corto cuando:

- **No se puede buscar.** Pasadas las 200 líneas, dependes de grep. OMEGA usa búsqueda semántica (embeddings bge-small-en-v1.5 + sqlite-vec) para encontrar memorias relevantes aunque la redacción sea diferente.
- **No captura automáticamente.** Cada lección hay que escribirla a mano. OMEGA detecta decisiones y resultados de depuración automáticamente.
- **Crece sin control.** Sin deduplicación, sin decaimiento, sin detección de contradicciones. OMEGA resuelve conflictos automáticamente, deduplica entradas semánticamente similares y decae memorias obsoletas.
- **Un archivo por proyecto.** Sin aprendizaje entre proyectos. El grafo de memoria de OMEGA abarca todo tu historial de desarrollo.
- **No tiene checkpoint.** Si paras a mitad de un refactoring, no hay forma de retomar. OMEGA guarda el estado de la tarea y continúa exactamente donde lo dejaste.

CLAUDE.md está bien para anotar "siempre usar tabs." OMEGA es para cuando tu agente necesita aprender de verdad.

## Benchmark

**1º en [LongMemEval](https://github.com/xiaowu0162/LongMemEval)** (ICLR 2025) — el benchmark académico para sistemas de memoria a largo plazo. 500 preguntas evaluando extracción, razonamiento, comprensión temporal y seguimiento de preferencias.

| Sistema | Puntuación | Nota |
|---------|----------:|------|
| **OMEGA** | **95.4%** | **1º** |
| Mastra | 94.87% | 2º |
| Zep/Graphiti | 71.2% | -- |

## Características Principales

- **12 Herramientas MCP** — Almacenar, consultar, buscar, checkpoint, reanudar y más.
- **Búsqueda Semántica** — bge-small-en-v1.5 + sqlite-vec para recuperación rápida y precisa.
- **Captura y Surfacing Automáticos** — Los hooks detectan decisiones y muestran memorias relevantes durante el trabajo.
- **Checkpoint y Reanudación** — Detén una tarea a la mitad, continúa en la siguiente sesión.
- **Olvido Inteligente** — Decaimiento temporal, resolución de conflictos, deduplicación.
- **100% Local, sin API Keys** — Todos los datos y el procesamiento quedan en tu máquina.

## Instalación

```bash
pip3 install omega-memory[server]   # instalar desde PyPI (incluye servidor MCP)
omega setup                         # configura el editor automáticamente
omega doctor                        # verifica que todo funciona
```

¿Usas Cursor, Windsurf o Zed?

```bash
omega setup --client cursor
omega setup --client windsurf
omega setup --client zed
```

## Comparación

| Característica | OMEGA | CLAUDE.md | Mem0 |
|----------------|:-----:|:---------:|:----:|
| Persistente entre sesiones | ✅ | ✅ | ✅ |
| Búsqueda semántica | ✅ | ❌ | ✅ |
| Captura automática | ✅ | ❌ | ✅ |
| Detección de contradicciones | ✅ | ❌ | ❌ |
| 100% local (sin API keys) | ✅ | ✅ | ❌ |

---

Para la documentación completa, consulta el [README en inglés](../README.md).

Sitio web: [omegamax.co](https://omegamax.co) | Docs: [omegamax.co/docs](https://omegamax.co/docs) | Benchmarks: [omegamax.co/benchmarks](https://omegamax.co/benchmarks)

## Licencia

Apache-2.0
