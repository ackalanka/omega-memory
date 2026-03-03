# OMEGA

**Memória persistente para agentes de codificação com IA.** Seu agente lembra decisões, aprende com erros e retoma de onde parou.

[![PyPI version](https://img.shields.io/pypi/v/omega-memory.svg)](https://pypi.org/project/omega-memory/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![#1 on LongMemEval](https://img.shields.io/badge/LongMemEval-95.4%25_%231_Overall-gold.svg)](https://omegamax.co/benchmarks)

[🇺🇸 English](../README.md) | [🇨🇳 中文](README_zh-CN.md) | [🇯🇵 日本語](README_ja.md) | [🇰🇷 한국어](README_ko.md) | [🇧🇷 Português](README_pt-BR.md) | [🇪🇸 Español](README_es.md) | [🇫🇷 Français](README_fr.md) | [🇩🇪 Deutsch](README_de.md) | [🇷🇺 Русский](README_ru.md)

## Início Rápido

```bash
pip3 install omega-memory[server]
omega setup
```

Funciona com **Claude Code** | **Cursor** | **Windsurf** | **Zed** | qualquer cliente MCP

---

## Por que não usar apenas o CLAUDE.md?

O `CLAUDE.md` integrado ao Claude Code é um arquivo de texto puro. Funciona para algumas anotações, mas colapsa quando:

- **Não dá pra buscar.** Acima de 200 linhas, você fica dependendo de grep. O OMEGA usa busca semântica (embeddings bge-small-en-v1.5 + sqlite-vec) para encontrar memórias relevantes mesmo quando a redação é diferente.
- **Não captura automaticamente.** Cada lição precisa ser escrita manualmente. O OMEGA detecta decisões e resultados de debugging automaticamente.
- **Cresce infinitamente.** Sem dedup, sem decaimento, sem detecção de contradições. O OMEGA resolve conflitos automaticamente, deduplica entradas semanticamente similares e decai memórias obsoletas.
- **Um arquivo por projeto.** Sem aprendizado entre projetos. O grafo de memória do OMEGA abrange todo o seu histórico de desenvolvimento.
- **Não tem checkpoint.** Parou no meio de um refactoring? Sem como retomar. O OMEGA salva o estado da tarefa e continua exatamente de onde você parou.

CLAUDE.md serve pra anotar "sempre usar tabs." OMEGA é para quando seu agente precisa realmente aprender.

## Benchmark

**1º lugar no [LongMemEval](https://github.com/xiaowu0162/LongMemEval)** (ICLR 2025) — benchmark acadêmico para sistemas de memória de longo prazo. 500 questões avaliando extração, raciocínio, compreensão temporal e rastreamento de preferências.

| Sistema | Pontuação | Observação |
|---------|----------:|------------|
| **OMEGA** | **95.4%** | **1º lugar** |
| Mastra | 94.87% | 2º lugar |
| Zep/Graphiti | 71.2% | -- |

## Principais Funcionalidades

- **12 Ferramentas MCP** — Armazenar, consultar, buscar, checkpoint, retomar e mais.
- **Busca Semântica** — bge-small-en-v1.5 + sqlite-vec para recuperação rápida e precisa.
- **Captura e Surfacing Automáticos** — Hooks detectam decisões e exibem memórias relevantes durante o trabalho.
- **Checkpoint e Retomada** — Pare uma tarefa no meio, continue na próxima sessão.
- **Esquecimento Inteligente** — Decaimento temporal, resolução de conflitos, deduplicação.
- **100% Local, sem API Keys** — Todos os dados e processamento ficam na sua máquina.

## Instalação

```bash
pip3 install omega-memory[server]   # instalar do PyPI (inclui servidor MCP)
omega setup                         # configura o editor automaticamente
omega doctor                        # verifica se tudo está funcionando
```

Usando Cursor, Windsurf ou Zed?

```bash
omega setup --client cursor
omega setup --client windsurf
omega setup --client zed
```

## Comparação

| Funcionalidade | OMEGA | CLAUDE.md | Mem0 |
|----------------|:-----:|:---------:|:----:|
| Persistente entre sessões | ✅ | ✅ | ✅ |
| Busca semântica | ✅ | ❌ | ✅ |
| Captura automática | ✅ | ❌ | ✅ |
| Detecção de contradições | ✅ | ❌ | ❌ |
| 100% local (sem API keys) | ✅ | ✅ | ❌ |

---

Para a documentação completa, consulte o [README em inglês](../README.md).

Website: [omegamax.co](https://omegamax.co) | Docs: [omegamax.co/docs](https://omegamax.co/docs) | Benchmarks: [omegamax.co/benchmarks](https://omegamax.co/benchmarks)

## Licença

Apache-2.0
