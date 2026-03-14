# OMEGA Integrations

Third-party framework integrations for OMEGA memory.

## CrewAI

**File:** `crewai_memory.py`

Use OMEGA as the persistent memory backend for [CrewAI](https://github.com/crewAIInc/crewAI) agents, crews, and flows. All agent memories persist locally in OMEGA's SQLite database across sessions -- no cloud API keys needed for storage.

### Requirements

```bash
pip install omega-memory crewai
omega setup  # downloads embedding model, creates ~/.omega/
```

### Quick Start

```python
from crewai import Agent, Task, Crew
from integrations.crewai_memory import OmegaMemory

# Create OMEGA-backed memory
memory = OmegaMemory(project="my-research-crew")

# Use it with a Crew
researcher = Agent(
    role="Senior Researcher",
    goal="Find cutting-edge AI developments",
    backstory="You are an expert AI researcher.",
    memory=memory,  # Agent uses OMEGA for memory
)

task = Task(
    description="Research the latest advances in multi-agent systems.",
    expected_output="A summary of key developments.",
    agent=researcher,
)

crew = Crew(
    agents=[researcher],
    tasks=[task],
    memory=memory,  # Crew-level shared memory
)

result = crew.kickoff()
# Memories from this run persist in OMEGA for future sessions
```

### Usage with Flows

```python
from crewai.flow.flow import Flow, start
from integrations.crewai_memory import OmegaMemory

class ResearchFlow(Flow):
    memory = OmegaMemory(project="research-flow")

    @start()
    def begin(self):
        # Store knowledge
        self.remember("Always cite primary sources, not secondary reviews")

        # Recall relevant memories from any previous session
        results = self.recall("citation preferences")
        for match in results:
            print(f"[{match.score:.2f}] {match.record.content}")
```

### Advanced Configuration

```python
from integrations.crewai_memory import OmegaMemory, OmegaStorage

# Custom OMEGA storage with project scoping
storage = OmegaStorage(
    project="finance-agents",
    agent_type="crewai",
    omega_home="~/.omega",  # custom data directory
)

# Full control over Memory parameters
from crewai.memory import Memory

memory = Memory(
    storage=storage,
    llm="anthropic/claude-3-haiku-20240307",  # any litellm model
    recency_weight=0.2,       # less weight on recency
    semantic_weight=0.6,      # more weight on semantic match
    importance_weight=0.2,
    consolidation_threshold=0.9,  # higher = less aggressive merging
)
```

### How It Works

| CrewAI Operation | OMEGA Backend |
|------------------|---------------|
| `memory.remember(text)` | `omega.bridge.store(text, event_type)` |
| `memory.recall(query)` | `omega.bridge.query_structured(query)` |
| `memory.forget(...)` | `omega.bridge.delete_memory(id)` |
| `memory.update(id, ...)` | `omega.bridge.edit_memory(id, content)` |

**Category mapping:** CrewAI categories are mapped to OMEGA event types:

| CrewAI Category | OMEGA Event Type |
|----------------|-----------------|
| `task_result` | `task_completion` |
| `observation` | `lesson_learned` |
| `decision` | `decision` |
| `error` | `error_pattern` |
| `preference` | `user_preference` |
| `lesson` | `lesson_learned` |
| `summary` | `session_summary` |

### What You Get from OMEGA

By using OMEGA instead of CrewAI's default LanceDB storage, your crew gets:

- **Semantic deduplication** -- similar memories are automatically merged
- **Contradiction detection** -- conflicting memories are flagged and resolved
- **Time decay** -- old unused memories naturally lose ranking weight
- **Graph relationships** -- memories are linked with typed edges (related, supersedes, contradicts)
- **Cross-session persistence** -- memories survive across crew runs, sessions, and projects
- **Local-first** -- no cloud, no API keys for storage. All data stays in `~/.omega/omega.db`
- **384-dim local embeddings** -- OMEGA uses bge-small-en-v1.5 (ONNX, runs on CPU)

### Limitations

- OMEGA generates its own embeddings (384-dim bge-small-en-v1.5). CrewAI's default OpenAI embeddings (1536-dim) are not used for storage. When CrewAI calls `search()` with a pre-computed embedding vector, the integration falls back to listing recent records. For best results, use `recall()` on the Memory object which routes through text-based search.
- `reset()` is a no-op. OMEGA does not support bulk deletion. Use `omega consolidate` from the CLI.
- Scope hierarchy is simplified. OMEGA uses flat project-based scoping rather than CrewAI's hierarchical `/company/team/project` paths.

### Components

| Component | Description |
|-----------|-------------|
| `OmegaStorage` | Implements `crewai.memory.storage.backend.StorageBackend` protocol |
| `OmegaMemory()` | Factory function returning `crewai.memory.Memory` with OMEGA backend |
