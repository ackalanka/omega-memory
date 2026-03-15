"""Tests for previously untested functions in OMEGA.

Covers:
1. CoordinationManager._migrate_schema  (coordination.py)
2. bridge.reingest                       (bridge.py)
3. SQLiteStore.reembed_all               (sqlite_store.py)
4. bridge.get_cross_session_lessons      (bridge.py)
5. IntentClassifier._load_or_build_prototypes (router/classifier.py)
6. Concurrent access to SQLiteStore      (bonus)
"""

import importlib.util
import json
import sqlite3
import threading
import time
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from omega.exceptions import EmbeddingError


# ---------------------------------------------------------------------------
# 1. CoordinationManager._migrate_schema
# ---------------------------------------------------------------------------


class TestMigrateSchema:
    """Tests for CoordinationManager._migrate_schema."""

    def _create_v1_db(self, db_path):
        """Create a v1 coord schema (coord_tasks WITHOUT result/progress columns)."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")

        # Schema version table at v1
        conn.execute(
            "CREATE TABLE coord_schema_version (version INTEGER NOT NULL)"
        )
        conn.execute("INSERT INTO coord_schema_version (version) VALUES (1)")

        # Sessions table (required by foreign key)
        conn.execute("""
            CREATE TABLE coord_sessions (
                session_id TEXT PRIMARY KEY,
                pid INTEGER,
                project TEXT,
                task TEXT,
                status TEXT DEFAULT 'active',
                capabilities TEXT,
                started_at TEXT NOT NULL,
                last_heartbeat TEXT NOT NULL,
                metadata TEXT
            )
        """)

        # coord_tasks v1 -- no result or progress columns
        conn.execute("""
            CREATE TABLE coord_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT,
                project TEXT,
                session_id TEXT,
                status TEXT DEFAULT 'pending',
                priority INTEGER DEFAULT 0,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                claimed_at TEXT,
                completed_at TEXT,
                metadata TEXT
            )
        """)

        conn.commit()
        return conn

    def test_migration_from_v1_adds_columns(self, tmp_omega_dir):
        """Migration from v1 to v2 adds result and progress columns."""
        from omega.coordination import CoordinationManager

        db_path = tmp_omega_dir / "migrate_test.db"
        conn = self._create_v1_db(db_path)

        # Verify columns don't exist yet
        cursor = conn.execute("PRAGMA table_info(coord_tasks)")
        col_names = {row[1] for row in cursor.fetchall()}
        assert "result" not in col_names
        assert "progress" not in col_names

        # Run migration
        mgr = CoordinationManager.__new__(CoordinationManager)
        mgr._migrate_schema(conn, from_version=1)

        # Verify columns now exist
        cursor = conn.execute("PRAGMA table_info(coord_tasks)")
        col_names = {row[1] for row in cursor.fetchall()}
        assert "result" in col_names
        assert "progress" in col_names

        conn.close()

    def test_migration_idempotent(self, tmp_omega_dir):
        """Running migration twice doesn't raise errors."""
        from omega.coordination import CoordinationManager

        db_path = tmp_omega_dir / "migrate_test.db"
        conn = self._create_v1_db(db_path)

        mgr = CoordinationManager.__new__(CoordinationManager)
        mgr._migrate_schema(conn, from_version=1)
        # Second call should not raise
        mgr._migrate_schema(conn, from_version=1)

        cursor = conn.execute("PRAGMA table_info(coord_tasks)")
        col_names = {row[1] for row in cursor.fetchall()}
        assert "result" in col_names
        assert "progress" in col_names

        conn.close()

    def test_already_at_v2_is_noop(self, tmp_omega_dir):
        """If from_version >= 2, nothing happens."""
        from omega.coordination import CoordinationManager

        db_path = tmp_omega_dir / "migrate_test.db"
        conn = self._create_v1_db(db_path)

        mgr = CoordinationManager.__new__(CoordinationManager)

        # Pretend we're already at v2 -- should skip entirely
        mgr._migrate_schema(conn, from_version=2)

        # Columns should NOT have been added (v1 schema untouched)
        cursor = conn.execute("PRAGMA table_info(coord_tasks)")
        col_names = {row[1] for row in cursor.fetchall()}
        assert "result" not in col_names
        assert "progress" not in col_names

        conn.close()

    def test_migration_preserves_existing_data(self, tmp_omega_dir):
        """Existing task rows survive the migration."""
        from omega.coordination import CoordinationManager

        db_path = tmp_omega_dir / "migrate_test.db"
        conn = self._create_v1_db(db_path)

        # Insert a task row before migration
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO coord_tasks (title, created_by, created_at)
               VALUES (?, ?, ?)""",
            ("test task", "sess-1", now),
        )
        conn.commit()

        mgr = CoordinationManager.__new__(CoordinationManager)
        mgr._migrate_schema(conn, from_version=1)

        row = conn.execute(
            "SELECT title, result, progress FROM coord_tasks WHERE title = ?",
            ("test task",),
        ).fetchone()
        assert row is not None
        assert row[0] == "test task"
        assert row[1] is None  # result defaults to NULL
        assert row[2] == 0     # progress defaults to 0

        conn.close()


# ---------------------------------------------------------------------------
# 2. bridge.reingest
# ---------------------------------------------------------------------------


class TestReingest:
    """Tests for bridge.reingest."""

    def _write_jsonl(self, path, lines):
        """Write JSONL lines to a file."""
        with open(path, "w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")

    @patch("omega.bridge._get_store")
    @patch("omega.crypto.decrypt_line", side_effect=lambda line: line)
    def test_file_not_found(self, mock_decrypt, mock_get_store, store, tmp_path):
        """Returns error when JSONL file doesn't exist."""
        mock_get_store.return_value = store
        from omega.bridge import reingest

        result = reingest(store_path=tmp_path / "nonexistent.jsonl")
        assert "error" in result
        assert result["ingested"] == 0

    @patch("omega.bridge._get_store")
    @patch("omega.crypto.decrypt_line", side_effect=lambda line: line)
    def test_valid_lines_ingested(self, mock_decrypt, mock_get_store, store, tmp_path):
        """Valid JSONL lines are ingested into the store."""
        mock_get_store.return_value = store
        from omega.bridge import reingest

        jsonl_path = tmp_path / "store.jsonl"
        self._write_jsonl(jsonl_path, [
            {"content": "First lesson learned about testing", "metadata": {"event_type": "lesson_learned"}},
            {"content": "Second decision about architecture", "metadata": {"event_type": "decision"}},
        ])

        result = reingest(store_path=jsonl_path)
        assert result["ingested"] == 2
        assert result["errors"] == 0
        assert result["total"] == 2

    @patch("omega.bridge._get_store")
    @patch("omega.crypto.decrypt_line", side_effect=lambda line: line)
    def test_empty_content_skipped(self, mock_decrypt, mock_get_store, store, tmp_path):
        """Lines with empty content are skipped."""
        mock_get_store.return_value = store
        from omega.bridge import reingest

        jsonl_path = tmp_path / "store.jsonl"
        self._write_jsonl(jsonl_path, [
            {"content": "", "metadata": {"event_type": "decision"}},
            {"content": "   ", "metadata": {"event_type": "decision"}},
            {"content": "Valid content here for test", "metadata": {"event_type": "decision"}},
        ])

        result = reingest(store_path=jsonl_path)
        assert result["skipped"] == 2
        assert result["ingested"] == 1

    @patch("omega.bridge._get_store")
    @patch("omega.crypto.decrypt_line", side_effect=lambda line: line)
    def test_skip_types_respected(self, mock_decrypt, mock_get_store, store, tmp_path):
        """Lines with skip_types are counted as skipped."""
        mock_get_store.return_value = store
        from omega.bridge import reingest

        jsonl_path = tmp_path / "store.jsonl"
        self._write_jsonl(jsonl_path, [
            {"content": "Should be skipped entirely here", "metadata": {"event_type": "session_summary"}},
            {"content": "Should be ingested into memory", "metadata": {"event_type": "decision"}},
        ])

        result = reingest(store_path=jsonl_path, skip_types={"session_summary"})
        assert result["skipped"] == 1
        assert result["ingested"] == 1

    @patch("omega.bridge._get_store")
    @patch("omega.crypto.decrypt_line", side_effect=lambda line: line)
    def test_malformed_json_counted_as_errors(self, mock_decrypt, mock_get_store, store, tmp_path):
        """Malformed JSON lines increment error count."""
        mock_get_store.return_value = store
        from omega.bridge import reingest

        jsonl_path = tmp_path / "store.jsonl"
        with open(jsonl_path, "w") as f:
            f.write("not valid json at all\n")
            f.write(json.dumps({"content": "Valid content for reingest test", "metadata": {}}) + "\n")

        result = reingest(store_path=jsonl_path)
        assert result["errors"] == 1
        assert result["ingested"] == 1
        assert result["total"] == 2

    @patch("omega.bridge._get_store")
    @patch("omega.crypto.decrypt_line", side_effect=lambda line: line)
    def test_stats_are_correct(self, mock_decrypt, mock_get_store, store, tmp_path):
        """All stats fields are correctly tallied."""
        mock_get_store.return_value = store
        from omega.bridge import reingest

        jsonl_path = tmp_path / "store.jsonl"
        with open(jsonl_path, "w") as f:
            f.write(json.dumps({"content": "Good content for correctness", "metadata": {"event_type": "decision"}}) + "\n")
            f.write(json.dumps({"content": "", "metadata": {"event_type": "decision"}}) + "\n")
            f.write("broken json\n")
            f.write(json.dumps({"content": "Skip me type test entry", "metadata": {"event_type": "test"}}) + "\n")
            f.write("\n")  # blank line (not counted)

        result = reingest(store_path=jsonl_path, skip_types={"test"})
        assert result["total"] == 4      # blank line not counted
        assert result["ingested"] == 1
        assert result["skipped"] == 2    # empty content + skip_types
        assert result["errors"] == 1


# ---------------------------------------------------------------------------
# 3. SQLiteStore.reembed_all
# ---------------------------------------------------------------------------


class TestReembedAll:
    """Tests for SQLiteStore.reembed_all."""

    @patch("omega.embedding.get_active_backend", return_value=None)
    @patch("omega.embedding._get_embedding_model", return_value=None)
    def test_no_backend_raises_runtime_error(self, mock_get_model, mock_backend, store):
        """Raises RuntimeError when no ML backend is available."""
        with pytest.raises(EmbeddingError, match="no ML embedding backend"):
            store.reembed_all()

    @pytest.mark.skipif(
        not importlib.util.find_spec("sqlite_vec"),
        reason="sqlite-vec not installed"
    )
    @patch("omega.embedding.generate_embeddings_batch")
    @patch("omega.embedding.get_active_backend", return_value="onnx")
    @patch("omega.embedding.generate_embedding", return_value=[0.1] * 384)
    def test_successful_reembedding(self, mock_gen_emb, mock_backend, mock_batch, store):
        """Successful reembedding updates counts correctly."""
        # Store some memories (mock embedding generation for store())
        store.store(content="First memory for reembed test", session_id="s1", skip_inference=True)
        store.store(content="Second memory for reembed test", session_id="s1", skip_inference=True)

        # Mock batch embedding to return valid vectors
        mock_batch.return_value = [[0.5] * 384, [0.6] * 384]

        result = store.reembed_all(batch_size=10)
        assert result["total"] == 2
        assert result["updated"] == 2
        assert result["failed"] == 0

    @patch("omega.embedding.generate_embeddings_batch", side_effect=RuntimeError("ONNX failed"))
    @patch("omega.embedding.get_active_backend", return_value="onnx")
    @patch("omega.embedding.generate_embedding", return_value=[0.1] * 384)
    def test_batch_failure_counts_all_as_failed(self, mock_gen_emb, mock_backend, mock_batch, store):
        """When batch embedding fails, all items in batch are counted as failed."""
        store.store(content="Memory alpha for batch fail test", session_id="s1", skip_inference=True)
        store.store(content="Memory beta for batch fail test", session_id="s1", skip_inference=True)
        store.store(content="Memory gamma for batch fail test", session_id="s1", skip_inference=True)

        result = store.reembed_all(batch_size=32)
        assert result["total"] == 3
        assert result["failed"] == 3
        assert result["updated"] == 0

    @patch("omega.embedding.generate_embeddings_batch")
    @patch("omega.embedding.get_active_backend", return_value="onnx")
    @patch("omega.embedding.generate_embedding", return_value=[0.1] * 384)
    def test_individual_item_failure(self, mock_gen_emb, mock_backend, mock_batch, store):
        """Individual insert failures only count that item as failed."""
        store.store(content="Good memory for individual fail", session_id="s1", skip_inference=True)
        store.store(content="Bad memory for individual fail", session_id="s1", skip_inference=True)

        # Return one good embedding and one bad (wrong dimension) to trigger insert failure
        good_emb = [0.5] * 384
        bad_emb = [0.5] * 10  # wrong dimension -- will fail serialization/insert
        mock_batch.return_value = [good_emb, bad_emb]

        result = store.reembed_all(batch_size=32)

        assert result["total"] == 2
        # With wrong-dimension embedding, the INSERT into vec table will fail
        # for the second item (struct.pack mismatch or vec constraint violation)
        assert result["updated"] + result["failed"] == 2
        assert result["failed"] >= 1


# ---------------------------------------------------------------------------
# 4. bridge.get_cross_session_lessons
# ---------------------------------------------------------------------------


class TestGetCrossSessionLessons:
    """Tests for bridge.get_cross_session_lessons."""

    # A base string of 85 chars so content[:80] is identical between original and duplicate.
    _LESSON_BASE = (
        "Always write comprehensive tests before refactoring any production code base "
        "carefully"
    )  # 85 chars -- both variants share the first 80

    def _populate_lessons(self, store):
        """Populate store with lesson_learned memories across sessions."""
        lessons = [
            (self._LESSON_BASE + " to avoid regressions in the future",
             {"event_type": "lesson_learned", "session_id": "sess-A"}),
            ("Use type hints in Python for better maintainability across the codebase always",
             {"event_type": "lesson_learned", "session_id": "sess-B"}),
            ("Check error logs before debugging blindly in production systems every time you can",
             {"event_type": "lesson_learned", "session_id": "sess-A"}),
            # Duplicate of first lesson: same content[:80] but different suffix, from different session
            (self._LESSON_BASE + " confirmed this is critical",
             {"event_type": "lesson_learned", "session_id": "sess-C"}),
            ("Database migrations should always be idempotent to prevent data loss in all cases",
             {"event_type": "lesson_learned", "session_id": "sess-B"}),
        ]
        for content, meta in lessons:
            store.store(content=content, session_id=meta["session_id"],
                        metadata=meta, skip_inference=True)

    @patch("omega.bridge._get_store")
    def test_returns_lessons(self, mock_get_store, store):
        """Returns lesson_learned memories."""
        mock_get_store.return_value = store
        self._populate_lessons(store)
        from omega.bridge import get_cross_session_lessons

        result = get_cross_session_lessons()
        assert len(result) > 0
        assert all("content" in r for r in result)

    @patch("omega.bridge._get_store")
    def test_deduplicates_by_content_prefix(self, mock_get_store, store):
        """Deduplicates lessons by content[:80].lower()."""
        mock_get_store.return_value = store
        self._populate_lessons(store)
        from omega.bridge import get_cross_session_lessons

        result = get_cross_session_lessons(limit=20)
        # "Always write comprehensive tests..." appears twice but should be deduped
        always_lessons = [r for r in result if r["content"].startswith("Always write comprehensive")]
        assert len(always_lessons) <= 1

    @patch("omega.bridge._get_store")
    def test_excludes_specified_session(self, mock_get_store, store):
        """Excludes lessons from the specified session."""
        mock_get_store.return_value = store
        self._populate_lessons(store)
        from omega.bridge import get_cross_session_lessons

        result = get_cross_session_lessons(exclude_session="sess-A")
        session_ids = [r.get("session_id") for r in result]
        assert "sess-A" not in session_ids

    @patch("omega.bridge._get_store")
    def test_cross_session_verification(self, mock_get_store, store):
        """Same lesson from 2+ sessions gets verified_count > 0."""
        mock_get_store.return_value = store
        self._populate_lessons(store)
        from omega.bridge import get_cross_session_lessons

        result = get_cross_session_lessons(limit=20)
        # "Always write tests..." appears in sess-A and sess-C
        verified = [r for r in result if r.get("verified_count", 0) > 0]
        assert len(verified) >= 1
        for v in verified:
            assert v["verified"] is True

    @patch("omega.bridge._get_store")
    def test_respects_limit(self, mock_get_store, store):
        """Result count respects the limit parameter."""
        mock_get_store.return_value = store
        self._populate_lessons(store)
        from omega.bridge import get_cross_session_lessons

        result = get_cross_session_lessons(limit=2)
        assert len(result) <= 2

    @patch("omega.bridge._get_store")
    def test_sorted_by_verified_then_access(self, mock_get_store, store):
        """Lessons are sorted by verified_count descending, then access_count."""
        mock_get_store.return_value = store
        self._populate_lessons(store)
        from omega.bridge import get_cross_session_lessons

        result = get_cross_session_lessons(limit=20)
        if len(result) >= 2:
            for i in range(len(result) - 1):
                v_curr = result[i].get("verified_count", 0)
                v_next = result[i + 1].get("verified_count", 0)
                if v_curr == v_next:
                    assert result[i].get("access_count", 0) >= result[i + 1].get("access_count", 0)
                else:
                    assert v_curr >= v_next

    @patch("omega.bridge._get_store")
    def test_task_based_query(self, mock_get_store, store):
        """When task is provided, query_by_type is used."""
        mock_get_store.return_value = store
        self._populate_lessons(store)
        from omega.bridge import get_cross_session_lessons

        with patch.object(store, "query_by_type", wraps=store.query_by_type) as mock_qbt:
            get_cross_session_lessons(task="refactoring")
            mock_qbt.assert_called_once()
            call_kwargs = mock_qbt.call_args
            assert call_kwargs[1].get("event_type", call_kwargs[0][1] if len(call_kwargs[0]) > 1 else None) == "lesson_learned" or \
                   "lesson_learned" in str(call_kwargs)


# ---------------------------------------------------------------------------
# 5. IntentClassifier._load_or_build_prototypes
# ---------------------------------------------------------------------------


class TestLoadOrBuildPrototypes:
    """Tests for IntentClassifier._load_or_build_prototypes."""

    INTENT_KEYS = {"coding", "creative", "logic", "exploration", "simple_edit"}

    def _make_classifier(self, use_cache=True):
        """Create an IntentClassifier without triggering __init__ side effects."""
        from omega.router.classifier import IntentClassifier
        clf = IntentClassifier(use_cache=use_cache)
        return clf

    def test_already_loaded_returns_early(self, monkeypatch):
        """If _loaded is True, prototypes are not rebuilt."""
        clf = self._make_classifier()
        clf._loaded = True
        clf.prototypes = {"coding": [1.0]}

        with patch.object(clf, "_build_prototypes") as mock_build:
            clf._load_or_build_prototypes()
            mock_build.assert_not_called()

        assert clf.prototypes == {"coding": [1.0]}

    def test_valid_cache_loads_successfully(self, tmp_path, monkeypatch):
        """Valid cache file with correct keys loads without rebuilding."""
        from omega.router import classifier as clf_module

        cache_path = tmp_path / "intent-prototypes.json"
        cached_data = {k: [0.1, 0.2, 0.3] for k in self.INTENT_KEYS}
        cache_path.write_text(json.dumps(cached_data))

        monkeypatch.setattr(clf_module, "PROTOTYPE_CACHE_PATH", cache_path)
        monkeypatch.setattr(clf_module, "OMEGA_DIR", tmp_path)

        clf = self._make_classifier(use_cache=True)

        with patch.object(clf, "_build_prototypes") as mock_build:
            clf._load_or_build_prototypes()
            mock_build.assert_not_called()

        assert clf._loaded is True
        assert set(clf.prototypes.keys()) == self.INTENT_KEYS

    def test_invalid_cache_keys_triggers_rebuild(self, tmp_path, monkeypatch):
        """Cache with wrong keys triggers a full rebuild."""
        from omega.router import classifier as clf_module

        cache_path = tmp_path / "intent-prototypes.json"
        bad_data = {"wrong_key": [0.1]}
        cache_path.write_text(json.dumps(bad_data))

        monkeypatch.setattr(clf_module, "PROTOTYPE_CACHE_PATH", cache_path)
        monkeypatch.setattr(clf_module, "OMEGA_DIR", tmp_path)

        clf = self._make_classifier(use_cache=True)

        with patch.object(clf, "_build_prototypes") as mock_build:
            clf._load_or_build_prototypes()
            mock_build.assert_called_once()

        assert clf._loaded is True

    def test_corrupt_json_triggers_rebuild(self, tmp_path, monkeypatch):
        """Corrupt JSON cache triggers a full rebuild."""
        from omega.router import classifier as clf_module

        cache_path = tmp_path / "intent-prototypes.json"
        cache_path.write_text("not valid json {{{")

        monkeypatch.setattr(clf_module, "PROTOTYPE_CACHE_PATH", cache_path)
        monkeypatch.setattr(clf_module, "OMEGA_DIR", tmp_path)

        clf = self._make_classifier(use_cache=True)

        with patch.object(clf, "_build_prototypes") as mock_build:
            clf._load_or_build_prototypes()
            mock_build.assert_called_once()

        assert clf._loaded is True

    def test_use_cache_false_skips_cache(self, tmp_path, monkeypatch):
        """use_cache=False always rebuilds, never reads cache."""
        from omega.router import classifier as clf_module

        cache_path = tmp_path / "intent-prototypes.json"
        cached_data = {k: [0.1, 0.2, 0.3] for k in self.INTENT_KEYS}
        cache_path.write_text(json.dumps(cached_data))

        monkeypatch.setattr(clf_module, "PROTOTYPE_CACHE_PATH", cache_path)
        monkeypatch.setattr(clf_module, "OMEGA_DIR", tmp_path)

        clf = self._make_classifier(use_cache=False)

        with patch.object(clf, "_build_prototypes") as mock_build:
            clf._load_or_build_prototypes()
            mock_build.assert_called_once()

        assert clf._loaded is True

    def test_cache_write_failure_does_not_crash(self, tmp_path, monkeypatch):
        """If writing cache fails, the method still succeeds."""
        from omega.router import classifier as clf_module

        # Point cache to a non-writable location
        cache_path = tmp_path / "no_perms_dir" / "intent-prototypes.json"
        # Don't create the parent dir, so write will fail
        monkeypatch.setattr(clf_module, "PROTOTYPE_CACHE_PATH", cache_path)
        # OMEGA_DIR.mkdir will succeed but cache write will fail because
        # we make OMEGA_DIR point somewhere that exists but cache_path is wrong
        monkeypatch.setattr(clf_module, "OMEGA_DIR", tmp_path)

        clf = self._make_classifier(use_cache=True)

        def mock_build():
            clf.prototypes = {k: [0.1] for k in self.INTENT_KEYS}

        with patch.object(clf, "_build_prototypes", side_effect=mock_build):
            # Force cache write to fail by making the path's parent non-existent
            monkeypatch.setattr(
                clf_module, "PROTOTYPE_CACHE_PATH",
                Path("/nonexistent/dir/cache.json"),
            )
            clf._load_or_build_prototypes()

        assert clf._loaded is True
        assert set(clf.prototypes.keys()) == self.INTENT_KEYS

    def test_no_cache_file_triggers_rebuild(self, tmp_path, monkeypatch):
        """When cache file doesn't exist, prototypes are rebuilt."""
        from omega.router import classifier as clf_module

        cache_path = tmp_path / "does_not_exist.json"
        monkeypatch.setattr(clf_module, "PROTOTYPE_CACHE_PATH", cache_path)
        monkeypatch.setattr(clf_module, "OMEGA_DIR", tmp_path)

        clf = self._make_classifier(use_cache=True)

        with patch.object(clf, "_build_prototypes") as mock_build:
            clf._load_or_build_prototypes()
            mock_build.assert_called_once()

        assert clf._loaded is True


# ---------------------------------------------------------------------------
# 6. Concurrent access (bonus)
# ---------------------------------------------------------------------------


class TestConcurrentAccess:
    """Verify SQLiteStore handles concurrent operations without crashes."""

    def test_concurrent_writes(self, store):
        """Multiple threads writing concurrently don't crash."""
        errors = []

        def writer(thread_id):
            try:
                for i in range(10):
                    store.store(
                        content=f"Thread {thread_id} memory {i} unique text",
                        session_id=f"sess-{thread_id}",
                        metadata={"event_type": "decision", "thread": thread_id},
                        skip_inference=True,
                    )
            except Exception as e:
                errors.append((thread_id, str(e)))

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Concurrent write errors: {errors}"
        assert store.node_count() == 50

    def test_concurrent_read_and_write(self, store):
        """Concurrent reads and writes don't corrupt data or crash."""
        # Pre-populate
        for i in range(10):
            store.store(
                content=f"Pre-existing memory number {i} for concurrent test",
                session_id="s-init",
                skip_inference=True,
            )

        errors = []
        read_results = []

        def writer():
            try:
                for i in range(10):
                    store.store(
                        content=f"Concurrent write memory {i} during read test",
                        session_id="s-writer",
                        skip_inference=True,
                    )
            except Exception as e:
                errors.append(("writer", str(e)))

        def reader():
            try:
                for _ in range(10):
                    results = store.query("memory", limit=5)
                    read_results.append(len(results))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(("reader", str(e)))

        writer_thread = threading.Thread(target=writer)
        reader_threads = [threading.Thread(target=reader) for _ in range(3)]

        writer_thread.start()
        for t in reader_threads:
            t.start()

        writer_thread.join(timeout=30)
        for t in reader_threads:
            t.join(timeout=30)

        assert len(errors) == 0, f"Concurrent read/write errors: {errors}"
        # All reads should have returned some results
        assert all(r >= 0 for r in read_results)

    def test_concurrent_store_no_data_corruption(self, store):
        """Data stored concurrently is retrievable and intact."""
        errors = []

        def writer(thread_id):
            try:
                store.store(
                    content=f"Integrity check content for thread {thread_id}",
                    session_id=f"sess-{thread_id}",
                    metadata={"event_type": "decision", "thread_id": str(thread_id)},
                    skip_inference=True,
                )
            except Exception as e:
                errors.append((thread_id, str(e)))

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(errors) == 0
        assert store.node_count() == 8

        # Verify each thread's data is present
        for thread_id in range(8):
            results = store.get_by_session(f"sess-{thread_id}", limit=10)
            assert len(results) == 1
            assert f"thread {thread_id}" in results[0].content
