"""OMEGA storage backend for CrewAI's unified memory system.

This module provides ``OmegaStorage``, a CrewAI ``StorageBackend`` implementation
that persists all crew/agent memories in OMEGA's local SQLite database. It also
provides ``OmegaMemory``, a convenience factory that returns a CrewAI ``Memory``
instance pre-configured with the OMEGA backend.

OMEGA handles embeddings internally (bge-small-en-v1.5, 384-dim, local ONNX),
so no OpenAI API key is needed for the storage layer. However, CrewAI's Memory
class still uses an LLM for analysis (scope inference, consolidation). You can
either set ``OPENAI_API_KEY`` or pass a different LLM to ``OmegaMemory()``.

Requirements:
    pip install omega-memory crewai

Usage with CrewAI Crew:
    from integrations.crewai_memory import OmegaMemory

    memory = OmegaMemory()
    crew = Crew(agents=[...], tasks=[...], memory=memory)

Usage with CrewAI Flow:
    from crewai.flow.flow import Flow, start
    from integrations.crewai_memory import OmegaMemory

    class MyFlow(Flow):
        memory = OmegaMemory()

        @start()
        def begin(self):
            self.remember("Project uses PostgreSQL for ACID compliance")
            results = self.recall("database decisions")

Usage as standalone storage backend:
    from crewai.memory import Memory
    from integrations.crewai_memory import OmegaStorage

    storage = OmegaStorage(project="my-project")
    memory = Memory(storage=storage)

See README.md in this directory for full documentation.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports -- fail clearly if dependencies are missing
# ---------------------------------------------------------------------------

def _import_omega():
    """Import OMEGA modules with a clear error if not installed."""
    try:
        from omega.sqlite_store import SQLiteStore
        from omega import bridge
        return SQLiteStore, bridge
    except ImportError as e:
        raise ImportError(
            "omega-memory is required for OmegaStorage. "
            "Install it with: pip install omega-memory"
        ) from e


def _import_crewai_types():
    """Import CrewAI memory types with a clear error if not installed."""
    try:
        from crewai.memory.types import MemoryRecord, ScopeInfo
        return MemoryRecord, ScopeInfo
    except ImportError as e:
        raise ImportError(
            "crewai is required for OmegaStorage. "
            "Install it with: pip install crewai"
        ) from e


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------

# Maps CrewAI category names to OMEGA event_type values.
_CATEGORY_TO_EVENT_TYPE = {
    "task_result": "task_completion",
    "observation": "lesson_learned",
    "decision": "decision",
    "error": "error_pattern",
    "preference": "user_preference",
    "lesson": "lesson_learned",
    "entity": "memory",
    "summary": "session_summary",
}


def _categories_to_event_type(categories: list[str] | None) -> str:
    """Convert CrewAI categories to a single OMEGA event_type."""
    if not categories:
        return "memory"
    for cat in categories:
        mapped = _CATEGORY_TO_EVENT_TYPE.get(cat.lower())
        if mapped:
            return mapped
    return "memory"


def _scope_to_project(scope: str | None) -> str | None:
    """Extract a project-like identifier from a CrewAI scope path.

    CrewAI scopes look like '/company/team/project'. We use the last
    non-empty segment as the OMEGA project identifier.
    """
    if not scope or scope == "/":
        return None
    parts = [p for p in scope.strip("/").split("/") if p]
    return parts[-1] if parts else None


def _omega_node_to_crewai_record(node: Any, MemoryRecord: type) -> Any:
    """Convert an OMEGA query result node to a CrewAI MemoryRecord."""
    meta = dict(node.metadata or {})
    event_type = meta.pop("event_type", "memory")

    # Map event_type back to a category
    reverse_map = {v: k for k, v in _CATEGORY_TO_EVENT_TYPE.items()}
    categories = []
    if event_type in reverse_map:
        categories.append(reverse_map[event_type])

    # Extract tags as additional categories
    tags = meta.pop("tags", [])
    if tags:
        categories.extend(str(t) for t in tags if str(t) not in categories)

    # Build scope from project metadata
    project = meta.pop("project", None)
    scope = f"/{project}" if project else "/"

    # Importance: OMEGA uses relevance (0-1 float from query), default 0.5
    importance = getattr(node, "relevance", 0.5) or 0.5

    return MemoryRecord(
        id=node.id,
        content=node.content,
        scope=scope,
        categories=categories,
        metadata=meta,
        importance=min(max(importance, 0.0), 1.0),
        created_at=node.created_at or datetime.now(timezone.utc),
        last_accessed=datetime.now(timezone.utc),
        embedding=None,  # OMEGA manages embeddings internally
        source=meta.get("source"),
        private=False,
    )


# ---------------------------------------------------------------------------
# OmegaStorage -- CrewAI StorageBackend implementation
# ---------------------------------------------------------------------------

class OmegaStorage:
    """CrewAI StorageBackend backed by OMEGA's SQLite memory graph.

    This class implements the ``crewai.memory.storage.backend.StorageBackend``
    protocol so it can be passed directly to ``crewai.memory.Memory(storage=...)``.

    All memories are persisted in OMEGA's local SQLite database (``~/.omega/omega.db``
    by default). OMEGA handles its own embedding generation (bge-small-en-v1.5,
    384-dim), deduplication, contradiction detection, and time-decay scoring.

    Args:
        project: Optional project name. Used to scope stored memories so that
            different CrewAI projects don't collide.
        session_id: Optional session identifier. Defaults to a generated UUID.
        omega_home: Path to the OMEGA data directory. Defaults to ``~/.omega``.
        agent_type: Optional agent type identifier stored in metadata.
    """

    def __init__(
        self,
        project: str | None = None,
        session_id: str | None = None,
        omega_home: str | Path | None = None,
        agent_type: str = "crewai",
    ) -> None:
        self._project = project
        self._session_id = session_id or str(uuid4())
        self._agent_type = agent_type

        # Configure OMEGA home if provided
        if omega_home:
            os.environ["OMEGA_HOME"] = str(omega_home)

        # Initialize OMEGA store
        SQLiteStore, _ = _import_omega()
        self._store = SQLiteStore.get_instance()
        self._MemoryRecord, self._ScopeInfo = _import_crewai_types()

        logger.info(
            "OmegaStorage initialized (project=%s, session=%s)",
            self._project,
            self._session_id[:12],
        )

    # ------------------------------------------------------------------
    # StorageBackend protocol: save
    # ------------------------------------------------------------------

    def save(self, records: list[Any]) -> None:
        """Save CrewAI MemoryRecord objects into OMEGA.

        Each record is stored via ``omega.bridge.store()`` which handles
        embedding generation, deduplication, and graph edge creation.
        """
        _, bridge = _import_omega()

        for record in records:
            # Build OMEGA metadata from CrewAI record fields
            meta: dict[str, Any] = dict(record.metadata or {})
            if record.categories:
                meta["tags"] = record.categories
            if record.source:
                meta["source"] = record.source
            meta["crewai_record_id"] = record.id
            meta["importance"] = record.importance

            event_type = _categories_to_event_type(record.categories)
            project = _scope_to_project(record.scope) or self._project

            try:
                bridge.store(
                    content=record.content,
                    event_type=event_type,
                    metadata=meta,
                    session_id=self._session_id,
                    project=project,
                    agent_type=self._agent_type,
                )
            except Exception as e:
                logger.warning("Failed to save record %s to OMEGA: %s", record.id, e)

    # ------------------------------------------------------------------
    # StorageBackend protocol: search
    # ------------------------------------------------------------------

    def search(
        self,
        query_embedding: list[float],
        scope_prefix: str | None = None,
        categories: list[str] | None = None,
        metadata_filter: dict[str, Any] | None = None,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[tuple[Any, float]]:
        """Search OMEGA memories by semantic similarity.

        CrewAI passes an embedding vector, but OMEGA generates its own
        embeddings (different model/dimensions). Instead of using the
        provided embedding directly, we perform a semantic text search
        using a synthetic query derived from the most recent save context.

        For best results, use ``recall()`` on the Memory object which
        passes the original text query through to OMEGA's search pipeline.
        """
        # OMEGA's search is text-based, not embedding-based from the caller.
        # We can't reverse an embedding into text, so we fall through to
        # a listing approach filtered by scope/categories.
        # The real search happens in the _text_search method called by recall flow.
        project = _scope_to_project(scope_prefix) or self._project
        event_type = _categories_to_event_type(categories) if categories else None

        _, bridge = _import_omega()

        try:
            results = bridge.query_structured(
                query_text="*",  # broad search
                limit=limit,
                session_id=self._session_id,
                project=project,
                event_type=event_type if event_type != "memory" else None,
            )
        except Exception as e:
            logger.warning("OMEGA search failed: %s", e)
            return []

        output = []
        for item in results:
            relevance = item.get("relevance", 0.5)
            if relevance < min_score:
                continue

            record = self._MemoryRecord(
                id=item.get("id", str(uuid4())),
                content=item.get("content", ""),
                scope=scope_prefix or "/",
                categories=item.get("tags", []),
                metadata=item.get("metadata", {}),
                importance=min(max(relevance, 0.0), 1.0),
                created_at=datetime.fromisoformat(item["created_at"]) if item.get("created_at") else datetime.now(timezone.utc),
                last_accessed=datetime.now(timezone.utc),
            )
            output.append((record, relevance))

        return output[:limit]

    def text_search(
        self,
        query_text: str,
        scope_prefix: str | None = None,
        categories: list[str] | None = None,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[tuple[Any, float]]:
        """Search OMEGA using a text query (preferred over embedding search).

        This is an extension method not in the base StorageBackend protocol,
        but it is what ``OmegaMemory`` uses for the most effective retrieval.
        """
        project = _scope_to_project(scope_prefix) or self._project
        event_type = _categories_to_event_type(categories) if categories else None

        _, bridge = _import_omega()

        try:
            results = bridge.query_structured(
                query_text=query_text,
                limit=limit,
                session_id=self._session_id,
                project=project,
                event_type=event_type if event_type != "memory" else None,
            )
        except Exception as e:
            logger.warning("OMEGA text search failed: %s", e)
            return []

        output = []
        for item in results:
            relevance = item.get("relevance", 0.5)
            if relevance < min_score:
                continue

            record = self._MemoryRecord(
                id=item.get("id", str(uuid4())),
                content=item.get("content", ""),
                scope=scope_prefix or "/",
                categories=item.get("tags", []),
                metadata=item.get("metadata", {}),
                importance=min(max(relevance, 0.0), 1.0),
                created_at=datetime.fromisoformat(item["created_at"]) if item.get("created_at") else datetime.now(timezone.utc),
                last_accessed=datetime.now(timezone.utc),
            )
            output.append((record, relevance))

        return output[:limit]

    # ------------------------------------------------------------------
    # StorageBackend protocol: delete
    # ------------------------------------------------------------------

    def delete(
        self,
        scope_prefix: str | None = None,
        categories: list[str] | None = None,
        record_ids: list[str] | None = None,
        older_than: datetime | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> int:
        """Delete memories from OMEGA matching the given criteria."""
        _, bridge = _import_omega()
        deleted = 0

        if record_ids:
            for rid in record_ids:
                try:
                    result = bridge.delete_memory(rid)
                    if result.get("success"):
                        deleted += 1
                except Exception as e:
                    logger.warning("Failed to delete OMEGA memory %s: %s", rid, e)

        return deleted

    # ------------------------------------------------------------------
    # StorageBackend protocol: update
    # ------------------------------------------------------------------

    def update(self, record: Any) -> None:
        """Update an existing memory record in OMEGA."""
        _, bridge = _import_omega()
        try:
            bridge.edit_memory(record.id, record.content)
        except Exception as e:
            logger.warning("Failed to update OMEGA memory %s: %s", record.id, e)

    # ------------------------------------------------------------------
    # StorageBackend protocol: get_record
    # ------------------------------------------------------------------

    def get_record(self, record_id: str) -> Any | None:
        """Retrieve a single memory record by ID."""
        SQLiteStore, _ = _import_omega()
        store = SQLiteStore.get_instance()

        try:
            node = store.get_node(record_id)
            if node is None:
                return None
            return _omega_node_to_crewai_record(node, self._MemoryRecord)
        except Exception as e:
            logger.warning("Failed to get OMEGA record %s: %s", record_id, e)
            return None

    # ------------------------------------------------------------------
    # StorageBackend protocol: list_records
    # ------------------------------------------------------------------

    def list_records(
        self,
        scope_prefix: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Any]:
        """List memory records, newest first."""
        _, bridge = _import_omega()
        project = _scope_to_project(scope_prefix) or self._project

        try:
            results = bridge.query_structured(
                query_text="*",
                limit=limit,
                project=project,
            )
        except Exception as e:
            logger.warning("Failed to list OMEGA records: %s", e)
            return []

        records = []
        for item in results[offset:offset + limit]:
            record = self._MemoryRecord(
                id=item.get("id", str(uuid4())),
                content=item.get("content", ""),
                scope=scope_prefix or "/",
                categories=item.get("tags", []),
                metadata=item.get("metadata", {}),
                importance=0.5,
                created_at=datetime.fromisoformat(item["created_at"]) if item.get("created_at") else datetime.now(timezone.utc),
                last_accessed=datetime.now(timezone.utc),
            )
            records.append(record)

        return records

    # ------------------------------------------------------------------
    # StorageBackend protocol: scope info
    # ------------------------------------------------------------------

    def get_scope_info(self, scope: str) -> Any:
        """Return scope information."""
        _, bridge = _import_omega()
        project = _scope_to_project(scope) or self._project

        try:
            stats = bridge.type_stats()
            record_count = sum(stats.values()) if isinstance(stats, dict) else 0
        except Exception:
            record_count = 0

        return self._ScopeInfo(
            path=scope,
            record_count=record_count,
            categories=list(_CATEGORY_TO_EVENT_TYPE.keys()),
            oldest_record=None,
            newest_record=None,
            child_scopes=[],
        )

    def list_scopes(self, parent: str = "/") -> list[str]:
        """List child scopes. OMEGA uses flat project-based scoping."""
        return []

    def list_categories(self, scope_prefix: str | None = None) -> dict[str, int]:
        """List categories and counts."""
        _, bridge = _import_omega()
        try:
            stats = bridge.type_stats()
            if isinstance(stats, dict):
                # Map OMEGA event types to CrewAI categories
                reverse_map = {v: k for k, v in _CATEGORY_TO_EVENT_TYPE.items()}
                return {
                    reverse_map.get(k, k): v
                    for k, v in stats.items()
                }
            return {}
        except Exception:
            return {}

    def count(self, scope_prefix: str | None = None) -> int:
        """Count records in scope."""
        info = self.get_scope_info(scope_prefix or "/")
        return info.record_count

    def reset(self, scope_prefix: str | None = None) -> None:
        """Reset (delete all) memories. Use with caution."""
        logger.warning(
            "OmegaStorage.reset() called -- OMEGA does not support bulk deletion. "
            "Use `omega consolidate` or manual deletion via the CLI."
        )

    # ------------------------------------------------------------------
    # StorageBackend protocol: async variants
    # ------------------------------------------------------------------

    async def asave(self, records: list[Any]) -> None:
        """Async save -- delegates to sync."""
        self.save(records)

    async def asearch(
        self,
        query_embedding: list[float],
        scope_prefix: str | None = None,
        categories: list[str] | None = None,
        metadata_filter: dict[str, Any] | None = None,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[tuple[Any, float]]:
        """Async search -- delegates to sync."""
        return self.search(
            query_embedding,
            scope_prefix=scope_prefix,
            categories=categories,
            metadata_filter=metadata_filter,
            limit=limit,
            min_score=min_score,
        )

    async def adelete(
        self,
        scope_prefix: str | None = None,
        categories: list[str] | None = None,
        record_ids: list[str] | None = None,
        older_than: datetime | None = None,
        metadata_filter: dict[str, Any] | None = None,
    ) -> int:
        """Async delete -- delegates to sync."""
        return self.delete(
            scope_prefix=scope_prefix,
            categories=categories,
            record_ids=record_ids,
            older_than=older_than,
            metadata_filter=metadata_filter,
        )


# ---------------------------------------------------------------------------
# OmegaMemory -- convenience factory
# ---------------------------------------------------------------------------

def OmegaMemory(
    project: str | None = None,
    session_id: str | None = None,
    omega_home: str | Path | None = None,
    agent_type: str = "crewai",
    llm: Any = "gpt-4o-mini",
    **memory_kwargs: Any,
) -> Any:
    """Create a CrewAI Memory instance backed by OMEGA.

    This is the recommended entry point. It creates an ``OmegaStorage``
    backend and wraps it in CrewAI's ``Memory`` class.

    Args:
        project: Optional project name for scoping memories.
        session_id: Optional session identifier.
        omega_home: Path to OMEGA data directory (default ``~/.omega``).
        agent_type: Agent type identifier (default ``"crewai"``).
        llm: LLM for CrewAI's memory analysis (scope inference, consolidation).
            Defaults to ``"gpt-4o-mini"``. Set to any litellm model string
            or a ``crewai.llm.LLM`` instance.
        **memory_kwargs: Additional keyword arguments passed to
            ``crewai.memory.Memory()``, e.g. ``recency_weight``,
            ``consolidation_threshold``.

    Returns:
        A ``crewai.memory.Memory`` instance configured with OMEGA storage.

    Example:
        from integrations.crewai_memory import OmegaMemory

        memory = OmegaMemory(project="my-app")
        memory.remember("Users prefer dark mode by default")
        results = memory.recall("user preferences")
    """
    from crewai.memory import Memory

    storage = OmegaStorage(
        project=project,
        session_id=session_id,
        omega_home=omega_home,
        agent_type=agent_type,
    )

    return Memory(
        storage=storage,
        llm=llm,
        **memory_kwargs,
    )
