"""Tests for sleep-time consolidation: strength decay (Phase 5) and entity dedup (Phase 6)."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture
def store(tmp_omega_dir):
    """Create a fresh SQLiteStore for testing."""
    from omega.sqlite_store import SQLiteStore

    db_path = tmp_omega_dir / "test.db"
    s = SQLiteStore(db_path=db_path)
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _reset_entity_singleton():
    """Reset entity manager singleton before and after each test."""
    from omega.entity.engine import reset_entity_manager

    reset_entity_manager()
    yield
    reset_entity_manager()


def _age_memory(store, node_id: str, days: int) -> None:
    """Backdate a memory's created_at by the given number of days."""
    old_dt = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    store._conn.execute(
        "UPDATE memories SET created_at = ? WHERE node_id = ?",
        (old_dt, node_id),
    )
    store._conn.commit()


class TestApplyStrengthDecay:
    """Tests for Phase 5: strength decay."""

    def test_decay_marks_old_zero_access_low_strength(self, store):
        """Old, zero-access, low-type-weight memories get marked superseded."""
        # file_summary has type_weight 0.05 -- very low
        nid = store.store(
            content="Summary of some file",
            metadata={"event_type": "file_summary"},
        )
        _age_memory(store, nid, 60)

        stats = store.apply_strength_decay(min_strength=0.05, min_age_days=30)

        assert stats["scanned"] >= 1
        assert stats["decayed"] >= 1

        # Verify metadata updated
        node = store.get_node(nid)
        meta = node.metadata
        assert meta.get("superseded") is True
        assert meta.get("superseded_reason") == "strength_decay"
        assert "superseded_at" in meta

    def test_protected_types_not_decayed(self, store):
        """Protected types (user_preference, error_pattern, etc.) are never decayed."""
        protected = ["user_preference", "error_pattern", "behavioral_pattern",
                      "constraint", "reminder"]
        nids = []
        for ptype in protected:
            nid = store.store(
                content=f"Important {ptype} content",
                metadata={"event_type": ptype},
            )
            _age_memory(store, nid, 60)
            nids.append(nid)

        stats = store.apply_strength_decay(min_strength=999.0, min_age_days=30)

        # None of the protected types should be decayed
        assert stats["decayed"] == 0
        for nid in nids:
            node = store.get_node(nid)
            assert node.metadata.get("superseded") is not True

    def test_recent_memories_not_decayed(self, store):
        """Memories younger than min_age_days are not decayed."""
        nid = store.store(
            content="Recent file summary",
            metadata={"event_type": "file_summary"},
        )
        # Don't age it -- it's brand new

        stats = store.apply_strength_decay(min_strength=999.0, min_age_days=30)

        assert stats["decayed"] == 0
        node = store.get_node(nid)
        assert node.metadata.get("superseded") is not True

    def test_already_superseded_skipped(self, store):
        """Already-superseded memories are not processed again."""
        nid = store.store(
            content="Already superseded content",
            metadata={"event_type": "file_summary", "superseded": True,
                       "superseded_reason": "contradiction"},
        )
        _age_memory(store, nid, 60)

        stats = store.apply_strength_decay(min_strength=999.0, min_age_days=30)

        # Should be scanned but not decayed again
        assert stats["decayed"] == 0

    def test_forgetting_log_created(self, store):
        """Strength decay creates forgetting log entries with reason 'strength_decay'."""
        nid = store.store(
            content="Forgettable file summary",
            metadata={"event_type": "file_summary"},
        )
        _age_memory(store, nid, 60)

        store.apply_strength_decay(min_strength=0.05, min_age_days=30)

        log_entries = store.get_forgetting_log(limit=10, reason="strength_decay")
        assert len(log_entries) >= 1
        found = any(e["node_id"] == nid for e in log_entries)
        assert found, f"Expected forgetting log entry for {nid}"

    def test_memories_with_access_not_scanned(self, store):
        """Memories with access_count > 0 are not selected for decay."""
        nid = store.store(
            content="Accessed file summary",
            metadata={"event_type": "file_summary"},
        )
        _age_memory(store, nid, 60)
        # Simulate access
        store._conn.execute(
            "UPDATE memories SET access_count = 5 WHERE node_id = ?", (nid,)
        )
        store._conn.commit()

        stats = store.apply_strength_decay(min_strength=999.0, min_age_days=30)

        assert stats["decayed"] == 0

    def test_high_strength_memories_survive(self, store):
        """Memories with high type_weight survive even when old."""
        # constraint has type_weight 3.0 -- but it's also protected, so use decision (2.0)
        # Actually decision is not protected. Use a non-protected high-weight type.
        nid = store.store(
            content="Important decision about architecture",
            metadata={"event_type": "decision"},
        )
        _age_memory(store, nid, 35)

        # With a reasonable threshold, decision (weight=2.0) should survive
        stats = store.apply_strength_decay(min_strength=0.05, min_age_days=30)

        # Decision type_weight is 2.0, decay at 35 days with lambda ~0.02
        # should still be above 0.05
        node = store.get_node(nid)
        assert node.metadata.get("superseded") is not True


class TestConsolidateIncludesNewPhases:
    """Tests that consolidate() returns Phase 5 and Phase 6 stats."""

    def test_consolidate_returns_decayed_memories_stat(self, store):
        """consolidate() stats dict includes 'decayed_memories' key."""
        stats = store.consolidate()
        assert "decayed_memories" in stats
        assert isinstance(stats["decayed_memories"], int)

    def test_consolidate_returns_merged_entities_stat(self, store):
        """consolidate() stats dict includes 'merged_entities' key."""
        stats = store.consolidate()
        assert "merged_entities" in stats
        assert isinstance(stats["merged_entities"], int)


class TestMergeDuplicateEntities:
    """Tests for Phase 6: entity deduplication."""

    def test_no_entities_returns_zero(self, store):
        """merge_duplicate_entities returns 0 when no entities exist."""
        stats = store.merge_duplicate_entities()
        assert stats["merged"] == 0

    def test_single_entity_returns_zero(self, store):
        """merge_duplicate_entities returns 0 with only one entity."""
        from omega.entity.engine import get_entity_manager

        em = get_entity_manager(Path(store.db_path))
        em.create_entity("acme", "ACME Corp", "company")

        stats = store.merge_duplicate_entities()
        assert stats["merged"] == 0

    def test_merges_case_variant_names(self, store):
        """merge_duplicate_entities merges entities with case-variant names."""
        from omega.entity.engine import get_entity_manager

        em = get_entity_manager(Path(store.db_path))
        em.create_entity("acme-lower", "acme corp", "company")
        em.create_entity("acme-upper", "ACME Corp", "company")
        em.create_entity("acme-mixed", "Acme Corp", "company")

        # Store memories referencing the duplicate entities
        store.store(content="Memory for acme-upper", entity_id="acme-upper")
        store.store(content="Memory for acme-mixed", entity_id="acme-mixed")

        stats = store.merge_duplicate_entities()

        # Two duplicates should be merged into the first-seen (by name sort order)
        assert stats["merged"] == 2

        # Verify all memories now point to the same (primary) entity_id
        entity_ids = store._conn.execute(
            "SELECT DISTINCT entity_id FROM memories WHERE entity_id IS NOT NULL"
        ).fetchall()
        unique_ids = {r[0] for r in entity_ids}
        # Should have at most 1 unique entity_id (the primary)
        assert len(unique_ids) == 1

    def test_distinct_names_not_merged(self, store):
        """Entities with different names are not merged."""
        from omega.entity.engine import get_entity_manager

        em = get_entity_manager(Path(store.db_path))
        em.create_entity("alpha", "Alpha Inc", "company")
        em.create_entity("beta", "Beta LLC", "company")

        stats = store.merge_duplicate_entities()
        assert stats["merged"] == 0


class TestEntityManagerListEntityIds:
    """Tests for EntityManager.list_entity_ids()."""

    def test_list_entity_ids_empty(self, tmp_omega_dir):
        """list_entity_ids returns empty list when no entities exist."""
        from omega.entity.engine import get_entity_manager

        em = get_entity_manager(tmp_omega_dir / "test.db")
        result = em.list_entity_ids()
        assert result == []

    def test_list_entity_ids_returns_tuples(self, tmp_omega_dir):
        """list_entity_ids returns (entity_id, name) tuples."""
        from omega.entity.engine import get_entity_manager

        em = get_entity_manager(tmp_omega_dir / "test.db")
        em.create_entity("alpha-co", "Alpha Corp", "company")
        em.create_entity("beta-co", "Beta Corp", "company")

        result = em.list_entity_ids()
        assert len(result) == 2
        # Sorted by name
        ids = [r[0] for r in result]
        names = [r[1] for r in result]
        assert "alpha-co" in ids
        assert "beta-co" in ids
        assert "Alpha Corp" in names
        assert "Beta Corp" in names

    def test_list_entity_ids_excludes_dissolved(self, tmp_omega_dir):
        """list_entity_ids only returns active entities."""
        from omega.entity.engine import get_entity_manager

        em = get_entity_manager(tmp_omega_dir / "test.db")
        em.create_entity("alive", "Alive Corp", "company")
        em.create_entity("dead", "Dead Corp", "company")
        em.delete_entity("dead")  # Soft-deletes (sets status to 'dissolved')

        result = em.list_entity_ids()
        assert len(result) == 1
        assert result[0][0] == "alive"
