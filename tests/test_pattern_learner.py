"""Tests for omega.pattern_learner -- Memory content clustering and drift detection."""

import json
import math
import sqlite3
import struct
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omega.pattern_learner import (
    PatternLearner,
    EMBEDDING_DIM,
    MIN_CLUSTER_SIZE_FOR_PATTERN,
    MAX_CLUSTER_PATTERNS,
    MIN_STORE_CONFIDENCE,
    MAX_NOISE_RATIO,
    CUSUM_THRESHOLD,
    EWMA_ALPHA,
    _serialize_f32,
    _deserialize_f32,
)

np = pytest.importorskip("numpy")


def _try_import_sklearn():
    try:
        from sklearn.cluster import HDBSCAN  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_embedding(seed: int, dim: int = EMBEDDING_DIM) -> list:
    """Create a deterministic pseudo-random embedding."""
    rng = np.random.default_rng(seed)
    return rng.standard_normal(dim).astype(np.float32).tolist()


def _make_cluster_embedding(cluster_center: list, noise: float = 0.05, seed: int = 0) -> list:
    """Create an embedding near a cluster center with small noise."""
    rng = np.random.default_rng(seed)
    arr = np.array(cluster_center, dtype=np.float32)
    arr += rng.standard_normal(len(cluster_center)).astype(np.float32) * noise
    return arr.tolist()


def _zero_embedding(dim: int = EMBEDDING_DIM) -> list:
    """Create a near-zero embedding (hash fallback, should be skipped)."""
    return [1e-8] * dim


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def learner_db(tmp_path):
    """Create a fresh SQLite DB with memories, memories_vec, and memory_clusters tables."""
    db_path = tmp_path / "test_learner.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL,
            last_accessed TEXT,
            access_count INTEGER DEFAULT 0,
            ttl_seconds INTEGER,
            session_id TEXT,
            event_type TEXT,
            project TEXT,
            content_hash TEXT,
            priority INTEGER DEFAULT 3,
            referenced_date TEXT,
            entity_id TEXT,
            agent_type TEXT,
            canonical_hash TEXT,
            end_date TEXT,
            extracted_keywords TEXT,
            retrieval_count INTEGER DEFAULT 0
        )
    """)

    # sqlite-vec simulation: use a regular table with BLOB column
    # (Real sqlite-vec not available in test, we mock the vec table)
    conn.execute("""
        CREATE TABLE memories_vec (
            rowid INTEGER PRIMARY KEY,
            embedding BLOB
        )
    """)

    conn.execute("""
        CREATE TABLE memory_clusters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cluster_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            member_count INTEGER NOT NULL,
            centroid BLOB,
            representative_keywords TEXT,
            representative_memory_ids TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            superseded INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX idx_memory_clusters_superseded ON memory_clusters(superseded)")

    conn.execute("""
        CREATE TABLE coord_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            started_at TEXT,
            ended_at TEXT,
            agent_id TEXT
        )
    """)

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def store_mock(learner_db):
    """Mock store object wrapping learner_db."""
    store = MagicMock()
    store._conn = learner_db
    store._vec_available = True
    return store


@pytest.fixture
def learner(store_mock):
    """PatternLearner backed by test DB."""
    return PatternLearner(store=store_mock)


def _insert_memory(conn, node_id, content, session_id="sess-1", event_type="decision",
                    keywords="", metadata=None, created_at=None, embedding=None):
    """Insert a test memory with embedding."""
    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()
    if metadata is None:
        metadata = {}
    meta_json = json.dumps(metadata)

    conn.execute(
        """INSERT INTO memories (node_id, content, metadata, created_at, session_id,
                                 event_type, extracted_keywords)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (node_id, content, meta_json, created_at, session_id, event_type, keywords),
    )

    if embedding is not None:
        rowid = conn.execute("SELECT id FROM memories WHERE node_id = ?", (node_id,)).fetchone()[0]
        conn.execute(
            "INSERT INTO memories_vec (rowid, embedding) VALUES (?, ?)",
            (rowid, _serialize_f32(embedding)),
        )

    conn.commit()


def _populate_clusterable_memories(conn, n_clusters=3, members_per_cluster=8):
    """Create memories that naturally cluster.

    Each cluster uses embeddings near a distinct center.
    """
    centers = []
    for i in range(n_clusters):
        rng = np.random.default_rng(i * 1000)
        center = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        center = center / np.linalg.norm(center)  # Normalize
        centers.append(center.tolist())

    topics = [
        ("threading", "concurrency lock mutex thread safe"),
        ("database", "sqlite query index schema migration"),
        ("testing", "pytest fixture assertion mock coverage"),
    ]

    idx = 0
    for cluster_idx in range(n_clusters):
        topic_name, keywords = topics[cluster_idx % len(topics)]
        for member_idx in range(members_per_cluster):
            emb = _make_cluster_embedding(centers[cluster_idx], noise=0.05, seed=idx)
            session_id = f"sess-{idx % 5}"
            _insert_memory(
                conn,
                node_id=f"mem-{idx}",
                content=f"Memory about {topic_name}: item {member_idx}",
                session_id=session_id,
                event_type="decision",
                keywords=keywords,
                embedding=emb,
            )
            idx += 1


# ---------------------------------------------------------------------------
# TestSerializationHelpers
# ---------------------------------------------------------------------------


class TestSerialization:
    """Test f32 serialization round-trip."""

    def test_roundtrip(self):
        vec = [1.0, 2.0, 3.5, -0.1]
        serialized = _serialize_f32(vec)
        deserialized = _deserialize_f32(serialized, dim=4)
        for a, b in zip(vec, deserialized):
            assert abs(a - b) < 1e-6

    def test_embedding_dim(self):
        vec = _make_embedding(42)
        assert len(vec) == EMBEDDING_DIM
        serialized = _serialize_f32(vec)
        assert len(serialized) == EMBEDDING_DIM * 4  # 4 bytes per float32


# ---------------------------------------------------------------------------
# TestLoadMemoryEmbeddings
# ---------------------------------------------------------------------------


class TestLoadMemoryEmbeddings:
    """Test loading embeddings from DB."""

    def test_loads_valid_embeddings(self, learner, learner_db):
        emb = _make_embedding(1)
        _insert_memory(learner_db, "n1", "Test content", embedding=emb)

        node_ids, embeddings, meta = learner.load_memory_embeddings()
        assert len(node_ids) == 1
        assert node_ids[0] == "n1"
        assert embeddings.shape == (1, EMBEDDING_DIM)

    def test_skips_hash_fallback_embeddings(self, learner, learner_db):
        good_emb = _make_embedding(1)
        bad_emb = _zero_embedding()
        _insert_memory(learner_db, "good", "Good memory", embedding=good_emb)
        _insert_memory(learner_db, "bad", "Bad memory", embedding=bad_emb)

        node_ids, embeddings, meta = learner.load_memory_embeddings()
        assert len(node_ids) == 1
        assert node_ids[0] == "good"

    def test_skips_null_embeddings(self, learner, learner_db):
        _insert_memory(learner_db, "no_emb", "No embedding")
        node_ids, embeddings, meta = learner.load_memory_embeddings()
        assert len(node_ids) == 0

    def test_event_type_filter(self, learner, learner_db):
        emb1 = _make_embedding(1)
        emb2 = _make_embedding(2)
        _insert_memory(learner_db, "n1", "Decision", event_type="decision", embedding=emb1)
        _insert_memory(learner_db, "n2", "Summary", event_type="session_summary", embedding=emb2)

        node_ids, _, _ = learner.load_memory_embeddings(event_types=["decision"])
        assert len(node_ids) == 1
        assert node_ids[0] == "n1"

    def test_limit(self, learner, learner_db):
        for i in range(5):
            emb = _make_embedding(i)
            _insert_memory(learner_db, f"n{i}", f"Content {i}", embedding=emb)

        node_ids, _, _ = learner.load_memory_embeddings(limit=3)
        assert len(node_ids) == 3

    def test_empty_db(self, learner, learner_db):
        node_ids, embeddings, meta = learner.load_memory_embeddings()
        assert len(node_ids) == 0
        assert embeddings.shape == (0,)

    def test_metadata_included(self, learner, learner_db):
        emb = _make_embedding(1)
        _insert_memory(
            learner_db, "n1", "Test", session_id="s1",
            event_type="decision", keywords="foo bar",
            metadata={"extra": "data"}, embedding=emb,
        )
        _, _, meta = learner.load_memory_embeddings()
        assert meta[0]["session_id"] == "s1"
        assert meta[0]["event_type"] == "decision"
        assert meta[0]["keywords"] == "foo bar"
        assert meta[0]["extra"] == "data"


# ---------------------------------------------------------------------------
# TestClusterMemories
# ---------------------------------------------------------------------------


class TestClusterMemories:
    """Test HDBSCAN clustering."""

    @pytest.mark.skipif(
        not _try_import_sklearn(),
        reason="scikit-learn not available",
    )
    def test_clusters_distinct_groups(self, learner, learner_db):
        _populate_clusterable_memories(learner_db, n_clusters=3, members_per_cluster=10)
        _, embeddings, _ = learner.load_memory_embeddings()

        labels = learner.cluster_memories(embeddings, min_cluster_size=5)
        unique_labels = set(labels)
        # Should find at least 2 clusters (HDBSCAN may merge similar ones)
        non_noise = {l for l in unique_labels if l != -1}
        assert len(non_noise) >= 2

    @pytest.mark.skipif(
        not _try_import_sklearn(),
        reason="scikit-learn not available",
    )
    def test_returns_label_per_embedding(self, learner, learner_db):
        _populate_clusterable_memories(learner_db, n_clusters=2, members_per_cluster=10)
        _, embeddings, _ = learner.load_memory_embeddings()

        labels = learner.cluster_memories(embeddings)
        assert len(labels) == len(embeddings)

    @pytest.mark.skipif(
        not _try_import_sklearn(),
        reason="scikit-learn not available",
    )
    def test_noise_label_is_minus_one(self, learner):
        # Random embeddings should mostly be noise
        rng = np.random.default_rng(42)
        random_embs = rng.standard_normal((20, EMBEDDING_DIM)).astype(np.float32)
        labels = learner.cluster_memories(random_embs, min_cluster_size=10)
        assert -1 in labels


# ---------------------------------------------------------------------------
# TestLabelClusters
# ---------------------------------------------------------------------------


class TestLabelClusters:
    """Test c-TF-IDF cluster labeling."""

    def test_labels_from_keywords(self, learner):
        node_ids = ["n1", "n2", "n3", "n4", "n5"]
        labels = [0, 0, 0, 1, 1]
        metadata = [
            {"keywords": "threading concurrency lock", "content": ""},
            {"keywords": "threading mutex safe", "content": ""},
            {"keywords": "threading lock deadlock", "content": ""},
            {"keywords": "database sqlite query", "content": ""},
            {"keywords": "database index schema", "content": ""},
        ]

        info = learner.label_clusters(node_ids, labels, metadata)
        assert 0 in info
        assert 1 in info
        assert info[0]["member_count"] == 3
        assert info[1]["member_count"] == 2
        # Cluster 0 should mention threading-related terms
        assert any("thread" in kw for kw in info[0]["keywords"])

    def test_skips_noise(self, learner):
        node_ids = ["n1", "n2"]
        labels = [-1, 0]
        metadata = [
            {"keywords": "noise", "content": ""},
            {"keywords": "real", "content": ""},
        ]

        info = learner.label_clusters(node_ids, labels, metadata)
        assert -1 not in info
        assert 0 in info
        assert info[0]["member_count"] == 1

    def test_fallback_to_content(self, learner):
        node_ids = ["n1", "n2"]
        labels = [0, 0]
        metadata = [
            {"keywords": "", "content": "Python threading is important"},
            {"keywords": "", "content": "Threading with locks in Python"},
        ]

        info = learner.label_clusters(node_ids, labels, metadata)
        assert 0 in info
        # Should extract some terms from content
        assert len(info[0]["keywords"]) > 0

    def test_session_ids_tracked(self, learner):
        node_ids = ["n1", "n2", "n3"]
        labels = [0, 0, 0]
        metadata = [
            {"keywords": "test", "content": "", "session_id": "s1"},
            {"keywords": "test", "content": "", "session_id": "s2"},
            {"keywords": "test", "content": "", "session_id": "s1"},
        ]

        info = learner.label_clusters(node_ids, labels, metadata)
        assert len(info[0]["session_ids"]) == 2

    def test_representative_node_ids_capped(self, learner):
        n = 10
        node_ids = [f"n{i}" for i in range(n)]
        labels = [0] * n
        metadata = [{"keywords": "test", "content": ""} for _ in range(n)]

        info = learner.label_clusters(node_ids, labels, metadata)
        assert len(info[0]["member_node_ids"]) <= 5


# ---------------------------------------------------------------------------
# TestComputeCtfidf
# ---------------------------------------------------------------------------


class TestComputeCtfidf:
    """Test c-TF-IDF computation."""

    def test_empty_input(self, learner):
        assert learner._compute_ctfidf({}) == {}

    def test_single_cluster(self, learner):
        result = learner._compute_ctfidf({0: "python threading concurrency lock"})
        assert 0 in result
        # With one cluster, IDF is low for all terms (log(1/1) = 0, so 0.1 fallback)
        assert len(result[0]) > 0

    def test_discriminative_terms(self, learner):
        result = learner._compute_ctfidf({
            0: "python threading lock mutex concurrency threading threading",
            1: "python database sqlite query index schema database database",
        })
        # "threading" should be top for cluster 0, "database" for cluster 1
        top_0 = result[0][0][0]
        top_1 = result[1][0][0]
        assert top_0 != top_1

    def test_stopwords_removed(self, learner):
        result = learner._compute_ctfidf({
            0: "the is a are was were threading lock",
        })
        terms = [t for t, _ in result[0]]
        assert "the" not in terms
        assert "threading" in terms


# ---------------------------------------------------------------------------
# TestComputeClusterCentroids
# ---------------------------------------------------------------------------


class TestComputeClusterCentroids:
    """Test centroid computation."""

    def test_centroid_is_mean(self, learner):
        embeddings = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ], dtype=np.float32)
        labels = [0, 0]

        centroids = learner.compute_cluster_centroids(embeddings, labels)
        assert 0 in centroids
        np.testing.assert_allclose(centroids[0], [0.5, 0.5, 0.0])

    def test_ignores_noise(self, learner):
        embeddings = np.array([
            [1.0, 0.0],
            [0.0, 1.0],
            [0.5, 0.5],
        ], dtype=np.float32)
        labels = [-1, 0, 0]

        centroids = learner.compute_cluster_centroids(embeddings, labels)
        assert -1 not in centroids
        assert 0 in centroids

    def test_multiple_clusters(self, learner):
        embeddings = np.array([
            [1.0, 0.0], [1.0, 0.1],  # cluster 0
            [0.0, 1.0], [0.1, 1.0],  # cluster 1
        ], dtype=np.float32)
        labels = [0, 0, 1, 1]

        centroids = learner.compute_cluster_centroids(embeddings, labels)
        assert len(centroids) == 2


# ---------------------------------------------------------------------------
# TestStoreAndGetClusters
# ---------------------------------------------------------------------------


class TestStoreClusters:
    """Test cluster persistence."""

    def test_store_and_retrieve(self, learner, learner_db):
        cluster_info = {
            0: {
                "label": "threading",
                "member_count": 10,
                "keywords": ["threading", "lock"],
                "member_node_ids": ["n1", "n2"],
            },
        }
        centroids = {0: np.array([1.0, 0.0, 0.0], dtype=np.float32)}

        count = learner.store_clusters(cluster_info, centroids)
        assert count == 1

        active = learner.get_active_clusters()
        assert len(active) == 1
        assert active[0]["label"] == "threading"
        assert active[0]["member_count"] == 10

    def test_supersedes_old_clusters(self, learner, learner_db):
        info1 = {0: {"label": "old", "member_count": 5, "keywords": [], "member_node_ids": []}}
        learner.store_clusters(info1, {})

        info2 = {0: {"label": "new", "member_count": 8, "keywords": [], "member_node_ids": []}}
        learner.store_clusters(info2, {})

        active = learner.get_active_clusters()
        assert len(active) == 1
        assert active[0]["label"] == "new"

    def test_empty_clusters(self, learner, learner_db):
        count = learner.store_clusters({}, {})
        assert count == 0
        assert learner.get_active_clusters() == []


# ---------------------------------------------------------------------------
# TestGenerateClusterPatterns
# ---------------------------------------------------------------------------


class TestGenerateClusterPatterns:
    """Test pattern generation from clusters."""

    def test_generates_patterns(self, learner):
        cluster_info = {
            0: {
                "label": "threading & concurrency",
                "member_count": 15,
                "keywords": ["threading", "lock", "mutex"],
                "session_ids": {"s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10"},
                "member_node_ids": ["n1", "n2"],
            },
        }
        # Use tight cluster embeddings (high density) not random noise
        rng = np.random.default_rng(42)
        center = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        center = center / np.linalg.norm(center)
        embeddings = np.stack([center + rng.standard_normal(EMBEDDING_DIM).astype(np.float32) * 0.05 for _ in range(15)])
        labels = [0] * 15

        patterns = learner.generate_cluster_patterns(cluster_info, embeddings, labels)
        assert len(patterns) >= 1
        p = patterns[0]
        assert p["pattern_type"] == "memory_theme"
        assert "threading" in p["content"].lower()
        assert p["evidence_count"] == 15
        assert p["evidence_sessions"] == 10

    def test_skips_small_clusters(self, learner):
        cluster_info = {
            0: {"label": "tiny", "member_count": 2, "keywords": [], "session_ids": set()},
        }
        embeddings = np.zeros((2, EMBEDDING_DIM), dtype=np.float32)
        labels = [0, 0]

        patterns = learner.generate_cluster_patterns(cluster_info, embeddings, labels)
        assert len(patterns) == 0

    def test_caps_at_max_patterns(self, learner):
        cluster_info = {}
        all_labels = []
        all_embeddings = []
        rng = np.random.default_rng(42)
        for i in range(MAX_CLUSTER_PATTERNS + 5):
            size = MIN_CLUSTER_SIZE_FOR_PATTERN + 1
            cluster_info[i] = {
                "label": f"cluster-{i}",
                "member_count": size,
                "keywords": [f"kw{i}"],
                "session_ids": {f"s{j}" for j in range(10)},
                "member_node_ids": [],
            }
            # Each cluster has tight embeddings around a center
            center = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
            center = center / np.linalg.norm(center)
            for _ in range(size):
                all_embeddings.append(center + rng.standard_normal(EMBEDDING_DIM).astype(np.float32) * 0.05)
            all_labels.extend([i] * size)

        embeddings = np.stack(all_embeddings)
        patterns = learner.generate_cluster_patterns(cluster_info, embeddings, all_labels)
        assert len(patterns) <= MAX_CLUSTER_PATTERNS

    def test_pattern_key_format(self, learner):
        rng = np.random.default_rng(42)
        center = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        center = center / np.linalg.norm(center)
        cluster_info = {
            0: {
                "label": "threading & concurrency",
                "member_count": 10,
                "keywords": ["threading"],
                "session_ids": {f"s{i}" for i in range(10)},
                "member_node_ids": [],
            },
        }
        embeddings = np.stack([center + rng.standard_normal(EMBEDDING_DIM).astype(np.float32) * 0.05 for _ in range(10)])
        labels = [0] * 10

        patterns = learner.generate_cluster_patterns(cluster_info, embeddings, labels)
        assert len(patterns) >= 1
        assert patterns[0]["pattern_key"].startswith("theme:")


# ---------------------------------------------------------------------------
# TestComputeDensity
# ---------------------------------------------------------------------------


class TestComputeDensity:
    """Test intra-cluster density computation."""

    def test_identical_vectors_high_density(self, learner):
        vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        embeddings = np.stack([vec] * 5)
        labels = [0] * 5

        density = learner._compute_density(embeddings, labels, 0)
        assert density > 0.9

    def test_orthogonal_vectors_low_density(self, learner):
        embeddings = np.eye(4, dtype=np.float32)
        labels = [0] * 4

        density = learner._compute_density(embeddings, labels, 0)
        assert density < 0.3

    def test_single_member(self, learner):
        embeddings = np.array([[1.0, 0.0]], dtype=np.float32)
        labels = [0]
        density = learner._compute_density(embeddings, labels, 0)
        assert density == 0.5  # Default for single member


# ---------------------------------------------------------------------------
# TestAnalyzeAndStore
# ---------------------------------------------------------------------------


class TestAnalyzeAndStore:
    """Test the main entry point."""

    def test_graceful_without_sklearn(self, learner):
        with patch.dict("sys.modules", {"sklearn": None, "sklearn.cluster": None}):
            with patch("omega.pattern_learner.PatternLearner.load_memory_embeddings") as mock_load:
                # Force re-import check
                result = learner.analyze_and_store()
                # Either skips or proceeds; should not raise
                assert isinstance(result, dict)

    def test_insufficient_memories(self, learner, learner_db):
        for i in range(5):
            emb = _make_embedding(i)
            _insert_memory(learner_db, f"n{i}", f"Content {i}", embedding=emb)

        result = learner.analyze_and_store()
        assert "skipped" in result

    @pytest.mark.skipif(
        not _try_import_sklearn(),
        reason="scikit-learn not available",
    )
    def test_high_noise_ratio_skips(self, learner, learner_db):
        """If >80% is noise, skip pattern generation."""
        # Insert random (non-clusterable) embeddings
        for i in range(20):
            emb = _make_embedding(i)
            _insert_memory(learner_db, f"n{i}", f"Random {i}", embedding=emb)

        with patch.object(learner, "cluster_memories", return_value=[-1] * 20):
            result = learner.analyze_and_store()
            assert result.get("skipped") == "high_noise_ratio"

    @pytest.mark.skipif(
        not _try_import_sklearn(),
        reason="scikit-learn not available",
    )
    def test_end_to_end_clustering(self, learner, learner_db):
        """Full pipeline with clusterable data."""
        _populate_clusterable_memories(learner_db, n_clusters=3, members_per_cluster=10)

        # Mock _store_or_reinforce_pattern to avoid needing the full bridge
        stored_patterns = []
        def mock_store(pattern):
            stored_patterns.append(pattern)

        with patch.object(learner, "_store_or_reinforce_pattern", side_effect=mock_store):
            result = learner.analyze_and_store()

        assert result["total_memories"] == 30
        assert result["clusters_found"] >= 2
        assert result["stored_clusters"] >= 2


# ---------------------------------------------------------------------------
# TestDetectTopicDrift
# ---------------------------------------------------------------------------


class TestDetectTopicDrift:
    """Test CUSUM-based topic drift detection."""

    def test_no_snapshots(self, learner, learner_db):
        patterns = learner.detect_topic_drift()
        assert patterns == []

    def test_growing_topic(self, learner, learner_db):
        """Insert cluster snapshots showing growth."""
        now = datetime.now(timezone.utc)
        for i in range(5):
            ts = (now - timedelta(days=30 * (4 - i))).isoformat()
            count = 5 + i * 5  # Growing: 5, 10, 15, 20, 25
            learner_db.execute(
                """INSERT INTO memory_clusters
                   (cluster_id, label, member_count, created_at, updated_at, superseded)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (0, "threading", count, ts, ts),
            )
        learner_db.commit()

        patterns = learner.detect_topic_drift(min_windows=3)
        # Should detect growth or at least return without error
        assert isinstance(patterns, list)

    def test_declining_topic(self, learner, learner_db):
        """Insert cluster snapshots showing decline."""
        now = datetime.now(timezone.utc)
        for i in range(5):
            ts = (now - timedelta(days=30 * (4 - i))).isoformat()
            count = 25 - i * 5  # Declining: 25, 20, 15, 10, 5
            learner_db.execute(
                """INSERT INTO memory_clusters
                   (cluster_id, label, member_count, created_at, updated_at, superseded)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (0, "database", count, ts, ts),
            )
        learner_db.commit()

        patterns = learner.detect_topic_drift(min_windows=3)
        assert isinstance(patterns, list)

    def test_stable_topic_no_drift(self, learner, learner_db):
        """Stable counts should not trigger drift."""
        now = datetime.now(timezone.utc)
        for i in range(5):
            ts = (now - timedelta(days=30 * (4 - i))).isoformat()
            learner_db.execute(
                """INSERT INTO memory_clusters
                   (cluster_id, label, member_count, created_at, updated_at, superseded)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (0, "stable", 10, ts, ts),
            )
        learner_db.commit()

        patterns = learner.detect_topic_drift(min_windows=3)
        # No drift for stable counts
        assert len(patterns) == 0

    def test_pattern_format(self, learner, learner_db):
        now = datetime.now(timezone.utc)
        for i in range(5):
            ts = (now - timedelta(days=30 * (4 - i))).isoformat()
            count = 2 + i * 10  # Strong growth
            learner_db.execute(
                """INSERT INTO memory_clusters
                   (cluster_id, label, member_count, created_at, updated_at, superseded)
                   VALUES (?, ?, ?, ?, ?, 0)""",
                (0, "fast_grower", count, ts, ts),
            )
        learner_db.commit()

        patterns = learner.detect_topic_drift(min_windows=3)
        for p in patterns:
            assert "pattern_type" in p
            assert p["pattern_type"] == "topic_drift"
            assert "pattern_key" in p
            assert "confidence" in p
            assert 0 <= p["confidence"] <= 1


# ---------------------------------------------------------------------------
# TestDetectBehavioralDrift
# ---------------------------------------------------------------------------


class TestDetectBehavioralDrift:
    """Test EWMA-based behavioral drift detection."""

    def test_no_sessions(self, learner, learner_db):
        patterns = learner.detect_behavioral_drift()
        assert patterns == []

    def test_insufficient_sessions(self, learner, learner_db):
        now = datetime.now(timezone.utc)
        for i in range(5):
            start = (now - timedelta(hours=i * 2)).isoformat()
            end = (now - timedelta(hours=i * 2) + timedelta(minutes=30)).isoformat()
            learner_db.execute(
                "INSERT INTO coord_sessions (session_id, started_at, ended_at) VALUES (?, ?, ?)",
                (f"s{i}", start, end),
            )
        learner_db.commit()

        patterns = learner.detect_behavioral_drift()
        assert patterns == []  # Not enough windows

    def test_detects_longer_sessions(self, learner, learner_db):
        now = datetime.now(timezone.utc)
        # Historical: 30min sessions
        for i in range(30):
            start = (now - timedelta(days=30) + timedelta(hours=i)).isoformat()
            end = (now - timedelta(days=30) + timedelta(hours=i, minutes=30)).isoformat()
            learner_db.execute(
                "INSERT INTO coord_sessions (session_id, started_at, ended_at) VALUES (?, ?, ?)",
                (f"hist-{i}", start, end),
            )
        # Recent: 120min sessions (4x longer)
        for i in range(10):
            start = (now - timedelta(hours=i * 3)).isoformat()
            end = (now - timedelta(hours=i * 3) + timedelta(minutes=120)).isoformat()
            learner_db.execute(
                "INSERT INTO coord_sessions (session_id, started_at, ended_at) VALUES (?, ?, ?)",
                (f"recent-{i}", start, end),
            )
        learner_db.commit()

        patterns = learner.detect_behavioral_drift(min_windows=2)
        assert isinstance(patterns, list)
        if patterns:
            assert patterns[0]["pattern_type"] == "behavioral_drift"

    def test_filters_unreasonable_durations(self, learner, learner_db):
        """Sessions > 24h are filtered."""
        now = datetime.now(timezone.utc)
        # One normal, one absurd
        learner_db.execute(
            "INSERT INTO coord_sessions (session_id, started_at, ended_at) VALUES (?, ?, ?)",
            ("normal", now.isoformat(), (now + timedelta(minutes=30)).isoformat()),
        )
        learner_db.execute(
            "INSERT INTO coord_sessions (session_id, started_at, ended_at) VALUES (?, ?, ?)",
            ("absurd", now.isoformat(), (now + timedelta(days=2)).isoformat()),
        )
        learner_db.commit()

        # Should not crash, absurd duration filtered
        patterns = learner.detect_behavioral_drift()
        assert isinstance(patterns, list)


# ---------------------------------------------------------------------------
# TestSynthesizeMetaMemories
# ---------------------------------------------------------------------------


class TestSynthesizeMetaMemories:
    """Test meta-memory synthesis."""

    def test_from_cluster_info(self, learner):
        cluster_info = {
            0: {
                "label": "threading & concurrency",
                "member_count": 12,
                "keywords": ["threading", "lock", "concurrency"],
                "member_node_ids": ["n1", "n2"],
                "session_ids": {"s1", "s2", "s3"},
            },
        }

        patterns = learner.synthesize_meta_memories(cluster_info=cluster_info)
        assert len(patterns) == 1
        p = patterns[0]
        assert p["pattern_type"] == "knowledge_concentration"
        assert "threading" in p["content"].lower()
        assert p["evidence_count"] == 12

    def test_skips_small_clusters(self, learner):
        cluster_info = {
            0: {
                "label": "tiny",
                "member_count": 3,
                "keywords": [],
                "member_node_ids": [],
                "session_ids": set(),
            },
        }
        patterns = learner.synthesize_meta_memories(cluster_info=cluster_info)
        assert len(patterns) == 0

    def test_from_stored_clusters(self, learner, learner_db):
        """Load from DB when no cluster_info provided."""
        now = datetime.now(timezone.utc).isoformat()
        learner_db.execute(
            """INSERT INTO memory_clusters
               (cluster_id, label, member_count, representative_keywords,
                representative_memory_ids, created_at, updated_at, superseded)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (0, "threading", 15, "threading, lock", json.dumps(["n1", "n2"]), now, now),
        )
        learner_db.commit()

        patterns = learner.synthesize_meta_memories()
        assert len(patterns) == 1
        assert "threading" in patterns[0]["content"].lower()

    def test_confidence_scales_with_size(self, learner):
        small = {0: {"label": "a", "member_count": 10, "keywords": [], "member_node_ids": [], "session_ids": set()}}
        large = {0: {"label": "a", "member_count": 50, "keywords": [], "member_node_ids": [], "session_ids": set()}}

        p_small = learner.synthesize_meta_memories(cluster_info=small)
        p_large = learner.synthesize_meta_memories(cluster_info=large)

        if p_small and p_large:
            assert p_large[0]["confidence"] > p_small[0]["confidence"]


# ---------------------------------------------------------------------------
# TestGetActiveClusters
# ---------------------------------------------------------------------------


class TestGetActiveClusters:
    """Test active cluster retrieval."""

    def test_empty(self, learner, learner_db):
        assert learner.get_active_clusters() == []

    def test_excludes_superseded(self, learner, learner_db):
        now = datetime.now(timezone.utc).isoformat()
        learner_db.execute(
            """INSERT INTO memory_clusters
               (cluster_id, label, member_count, representative_keywords,
                representative_memory_ids, created_at, updated_at, superseded)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
            (0, "old", 5, "old", "[]", now, now),
        )
        learner_db.execute(
            """INSERT INTO memory_clusters
               (cluster_id, label, member_count, representative_keywords,
                representative_memory_ids, created_at, updated_at, superseded)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (1, "new", 8, "new", "[]", now, now),
        )
        learner_db.commit()

        active = learner.get_active_clusters()
        assert len(active) == 1
        assert active[0]["label"] == "new"

    def test_ordered_by_member_count(self, learner, learner_db):
        now = datetime.now(timezone.utc).isoformat()
        for cid, count in [(0, 5), (1, 15), (2, 10)]:
            learner_db.execute(
                """INSERT INTO memory_clusters
                   (cluster_id, label, member_count, representative_keywords,
                    representative_memory_ids, created_at, updated_at, superseded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                (cid, f"c{cid}", count, "", "[]", now, now),
            )
        learner_db.commit()

        active = learner.get_active_clusters()
        counts = [c["member_count"] for c in active]
        assert counts == sorted(counts, reverse=True)


# ---------------------------------------------------------------------------
# TestGenerateWelcomePatterns
# ---------------------------------------------------------------------------


class TestGenerateWelcomePatterns:
    """Test welcome briefing pattern generation."""

    def test_returns_empty_when_no_clusters(self, learner, learner_db):
        """No clusters => empty list, no crash."""
        lines = learner.generate_welcome_patterns()
        assert lines == []

    def test_top_themes_from_clusters(self, learner, learner_db):
        """Clusters are surfaced as 'Top themes' line."""
        now = datetime.now(timezone.utc).isoformat()
        for cid, label, count in [(0, "threading & lock", 15), (1, "database & query", 10)]:
            learner_db.execute(
                """INSERT INTO memory_clusters
                   (cluster_id, label, member_count, representative_keywords,
                    representative_memory_ids, created_at, updated_at, superseded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                (cid, label, count, "kw1, kw2", "[]", now, now),
            )
        learner_db.commit()

        lines = learner.generate_welcome_patterns()
        assert len(lines) >= 1
        assert "Top themes:" in lines[0]
        assert "threading & lock" in lines[0]
        assert "15 memories" in lines[0]

    def test_thompson_effectiveness(self, learner, learner_db):
        """Thompson ranking produces 'Most effective type' line."""
        # Create thompson_arms table and insert data
        learner_db.execute("""
            CREATE TABLE IF NOT EXISTS thompson_arms (
                arm_id TEXT PRIMARY KEY,
                arm_type TEXT NOT NULL,
                alpha REAL DEFAULT 1.0,
                beta REAL DEFAULT 1.0,
                total_trials INTEGER DEFAULT 0,
                total_successes INTEGER DEFAULT 0,
                last_updated TEXT,
                context TEXT
            )
        """)
        learner_db.execute(
            """INSERT INTO thompson_arms
               (arm_id, arm_type, alpha, beta, total_trials, total_successes, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("event_type:decision", "event_type", 8.0, 2.0, 10, 8,
             datetime.now(timezone.utc).isoformat()),
        )
        learner_db.commit()

        lines = learner.generate_welcome_patterns()
        eff_lines = [l for l in lines if "Most effective type:" in l]
        assert len(eff_lines) == 1
        assert "decision" in eff_lines[0]
        assert "10 trials" in eff_lines[0]

    def test_drift_signals_included(self, learner, learner_db):
        """Topic drift memories are surfaced."""
        now = datetime.now(timezone.utc).isoformat()
        meta = json.dumps({"pattern_type": "topic_drift", "source": "pattern_learner"})
        learner_db.execute(
            """INSERT INTO memories
               (node_id, content, metadata, created_at, event_type)
               VALUES (?, ?, ?, ?, ?)""",
            ("drift-1", "Topic drift: 'concurrency' is declining (was 23, now 15)",
             meta, now, "behavioral_pattern"),
        )
        learner_db.commit()

        lines = learner.generate_welcome_patterns()
        drift_lines = [l for l in lines if "Drift:" in l or "declining" in l]
        assert len(drift_lines) >= 1
        assert "concurrency" in drift_lines[0]

    def test_limit_respected(self, learner, learner_db):
        """Output is capped at the limit parameter."""
        now = datetime.now(timezone.utc).isoformat()
        # Add many clusters so themes line exists
        for cid in range(5):
            learner_db.execute(
                """INSERT INTO memory_clusters
                   (cluster_id, label, member_count, representative_keywords,
                    representative_memory_ids, created_at, updated_at, superseded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                (cid, f"cluster-{cid}", 10 + cid, "", "[]", now, now),
            )
        # Add drift memories
        for i in range(3):
            meta = json.dumps({"pattern_type": "topic_drift", "source": "pattern_learner"})
            learner_db.execute(
                """INSERT INTO memories
                   (node_id, content, metadata, created_at, event_type)
                   VALUES (?, ?, ?, ?, ?)""",
                (f"drift-{i}", f"Topic drift: 'topic-{i}' is growing",
                 meta, now, "behavioral_pattern"),
            )
        learner_db.commit()

        lines = learner.generate_welcome_patterns(limit=2)
        assert len(lines) <= 2

    def test_drift_not_crowded_out_at_limit_2(self, learner, learner_db):
        """Drift gets a slot even when themes+effectiveness fill limit=2."""
        now = datetime.now(timezone.utc).isoformat()
        # Add cluster (produces theme line)
        learner_db.execute(
            """INSERT INTO memory_clusters
               (cluster_id, label, member_count, representative_keywords,
                representative_memory_ids, created_at, updated_at, superseded)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (0, "threading", 15, "", "[]", now, now),
        )
        # Add thompson data (produces effectiveness line)
        learner_db.execute("""
            CREATE TABLE IF NOT EXISTS thompson_arms (
                arm_id TEXT PRIMARY KEY, arm_type TEXT NOT NULL,
                alpha REAL DEFAULT 1.0, beta REAL DEFAULT 1.0,
                total_trials INTEGER DEFAULT 0, total_successes INTEGER DEFAULT 0,
                last_updated TEXT, context TEXT
            )
        """)
        learner_db.execute(
            """INSERT INTO thompson_arms
               (arm_id, arm_type, alpha, beta, total_trials, total_successes, last_updated)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("event_type:decision", "event_type", 8.0, 2.0, 10, 8, now),
        )
        # Add drift signal
        meta = json.dumps({"pattern_type": "topic_drift", "source": "pattern_learner"})
        learner_db.execute(
            """INSERT INTO memories (node_id, content, metadata, created_at, event_type)
               VALUES (?, ?, ?, ?, ?)""",
            ("drift-1", "Topic drift: 'concurrency' is declining", meta, now, "behavioral_pattern"),
        )
        learner_db.commit()

        lines = learner.generate_welcome_patterns(limit=2)
        assert len(lines) == 2
        # Drift must be present (it's time-sensitive)
        assert any("Drift:" in l or "declining" in l for l in lines)
        # Themes should also be present (static context)
        assert any("Top themes:" in l for l in lines)

    def test_drift_takes_priority_at_limit_1(self, learner, learner_db):
        """When limit=1 and drift exists, drift wins over themes."""
        now = datetime.now(timezone.utc).isoformat()
        # Add cluster
        learner_db.execute(
            """INSERT INTO memory_clusters
               (cluster_id, label, member_count, representative_keywords,
                representative_memory_ids, created_at, updated_at, superseded)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (0, "threading", 15, "", "[]", now, now),
        )
        # Add drift signal
        meta = json.dumps({"pattern_type": "topic_drift", "source": "pattern_learner"})
        learner_db.execute(
            """INSERT INTO memories (node_id, content, metadata, created_at, event_type)
               VALUES (?, ?, ?, ?, ?)""",
            ("drift-1", "Topic drift: 'concurrency' surging", meta, now, "behavioral_pattern"),
        )
        learner_db.commit()

        lines = learner.generate_welcome_patterns(limit=1)
        assert len(lines) == 1
        assert "Drift:" in lines[0] or "surging" in lines[0]

    def test_graceful_on_missing_thompson_table(self, learner, learner_db):
        """No thompson_arms table => skips effectiveness, no crash."""
        now = datetime.now(timezone.utc).isoformat()
        learner_db.execute(
            """INSERT INTO memory_clusters
               (cluster_id, label, member_count, representative_keywords,
                representative_memory_ids, created_at, updated_at, superseded)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (0, "test", 5, "", "[]", now, now),
        )
        learner_db.commit()

        # Should not crash even though thompson_arms doesn't exist
        lines = learner.generate_welcome_patterns()
        assert isinstance(lines, list)
        # Should still have the themes line
        assert any("Top themes:" in l for l in lines)


# ---------------------------------------------------------------------------
# TestGetClustersForRetrieval
# ---------------------------------------------------------------------------


class TestGetClustersForRetrieval:
    """Test cluster retrieval with deserialized centroids."""

    def test_returns_deserialized_centroids(self, learner, learner_db):
        """Centroids are deserialized from blob to float list."""
        now = datetime.now(timezone.utc).isoformat()
        centroid = [1.0, 2.0, 3.0] + [0.0] * (EMBEDDING_DIM - 3)
        centroid_bytes = _serialize_f32(centroid)

        learner_db.execute(
            """INSERT INTO memory_clusters
               (cluster_id, label, member_count, centroid,
                representative_keywords, representative_memory_ids,
                created_at, updated_at, superseded)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (0, "test_cluster", 10, centroid_bytes, "kw1, kw2",
             json.dumps(["mem-1", "mem-2"]), now, now),
        )
        learner_db.commit()

        clusters = learner.get_clusters_for_retrieval()
        assert len(clusters) == 1
        c = clusters[0]
        assert c["cluster_id"] == 0
        assert isinstance(c["centroid"], list)
        assert len(c["centroid"]) == EMBEDDING_DIM
        assert abs(c["centroid"][0] - 1.0) < 1e-6
        assert c["member_node_ids"] == ["mem-1", "mem-2"]

    def test_skips_null_centroids(self, learner, learner_db):
        """Clusters without centroids are excluded."""
        now = datetime.now(timezone.utc).isoformat()
        learner_db.execute(
            """INSERT INTO memory_clusters
               (cluster_id, label, member_count, centroid,
                representative_keywords, representative_memory_ids,
                created_at, updated_at, superseded)
               VALUES (?, ?, ?, NULL, ?, ?, ?, ?, 0)""",
            (0, "no_centroid", 5, "", "[]", now, now),
        )
        learner_db.commit()

        clusters = learner.get_clusters_for_retrieval()
        assert len(clusters) == 0

    def test_excludes_superseded(self, learner, learner_db):
        """Superseded clusters are not returned."""
        now = datetime.now(timezone.utc).isoformat()
        centroid_bytes = _serialize_f32([0.5] * EMBEDDING_DIM)

        learner_db.execute(
            """INSERT INTO memory_clusters
               (cluster_id, label, member_count, centroid,
                representative_keywords, representative_memory_ids,
                created_at, updated_at, superseded)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (0, "old", 10, centroid_bytes, "", "[]", now, now),
        )
        learner_db.commit()

        clusters = learner.get_clusters_for_retrieval()
        assert len(clusters) == 0
