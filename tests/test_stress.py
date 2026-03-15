"""OMEGA Stress Test Suite — CPU/memory performance, scaling limits, contention.

All tests use skip_inference=True to avoid loading the 337MB ONNX model.
Marked @pytest.mark.slow so existing test suite runs unaffected:
    pytest tests/ -m "not slow"      # skip stress tests
    pytest tests/test_stress.py -v -s # run stress tests with output
"""

import os
import platform
import resource
import threading
import time
import tracemalloc

import pytest

from omega.sqlite_store import SQLiteStore
from omega.coordination import CoordinationManager
from omega.entity.engine import EntityManager, reset_entity_manager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class Stopwatch:
    """Context manager for wall-clock timing via time.monotonic()."""

    def __init__(self):
        self.elapsed: float = 0.0

    def __enter__(self):
        self._start = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.elapsed = time.monotonic() - self._start

    @property
    def ms(self) -> float:
        return self.elapsed * 1000


class MemoryTracker:
    """Context manager wrapping tracemalloc + resource.getrusage for RSS."""

    def __init__(self):
        self.traced_delta: int = 0  # bytes (tracemalloc current delta)
        self.peak_traced: int = 0   # bytes (tracemalloc peak)
        self.rss_before: int = 0    # bytes
        self.rss_after: int = 0     # bytes

    @staticmethod
    def _rss_bytes() -> int:
        """Current RSS in bytes (handles macOS bytes vs Linux KB)."""
        usage = resource.getrusage(resource.RUSAGE_SELF)
        ru_maxrss = usage.ru_maxrss
        if platform.system() == "Darwin":
            return ru_maxrss  # already bytes on macOS
        return ru_maxrss * 1024  # Linux reports KB

    def __enter__(self):
        tracemalloc.start()
        self.rss_before = self._rss_bytes()
        return self

    def __exit__(self, *exc):
        self.rss_after = self._rss_bytes()
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.traced_delta = current
        self.peak_traced = peak

    @property
    def rss_delta_mb(self) -> float:
        return (self.rss_after - self.rss_before) / (1024 * 1024)

    @property
    def traced_mb(self) -> float:
        return self.traced_delta / (1024 * 1024)

    @property
    def peak_mb(self) -> float:
        return self.peak_traced / (1024 * 1024)


def percentile(data: list[float], p: float) -> float:
    """Compute percentile without numpy. p in [0, 100]."""
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = f + 1
    if c >= len(s):
        return s[-1]
    return s[f] + (k - f) * (s[c] - s[f])


def print_table(title: str, headers: list[str], rows: list[list]) -> None:
    """Print a formatted ASCII table to stdout."""
    all_rows = [headers] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in all_rows) for i in range(len(headers))]
    sep = "| " + " | ".join("-" * w for w in widths) + " |"
    fmt = "| " + " | ".join(f"{{:<{w}}}" for w in widths) + " |"

    print(f"\n--- {title} ---")
    print(fmt.format(*headers))
    print(sep)
    for r in rows:
        print(fmt.format(*[str(c) for c in r]))
    print()


def run_threads(fn, count: int, *, use_barrier: bool = True) -> list:
    """Launch N threads, optionally synchronized by a barrier for max contention.

    fn(thread_index: int) -> result
    Returns list of results (one per thread).
    """
    barrier = threading.Barrier(count) if use_barrier else None
    results: list = [None] * count
    errors: list = [None] * count

    def _worker(idx):
        try:
            if barrier:
                barrier.wait(timeout=30)
            results[idx] = fn(idx)
        except Exception as exc:
            errors[idx] = exc

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    # Re-raise first error if any
    for e in errors:
        if e is not None:
            raise e

    return results


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stress_store(tmp_omega_dir):
    """Fresh SQLiteStore for stress tests."""
    db_path = tmp_omega_dir / "stress.db"
    s = SQLiteStore(db_path=db_path)
    yield s
    s.close()


@pytest.fixture
def stress_coord(tmp_omega_dir):
    """Fresh CoordinationManager for stress tests."""
    db_path = tmp_omega_dir / "stress.db"
    mgr = CoordinationManager(db_path=db_path, cloud_sync=False)
    yield mgr
    mgr.close()


@pytest.fixture
def stress_entity(tmp_omega_dir):
    """Fresh EntityManager for stress tests."""
    reset_entity_manager()
    db_path = tmp_omega_dir / "stress.db"
    mgr = EntityManager(db_path=db_path)
    yield mgr
    mgr.close()
    reset_entity_manager()


# ---------------------------------------------------------------------------
# 1. Memory Store Scaling
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestMemoryStoreScaling:
    """Insert throughput, query latency, and RSS growth at scale."""

    @staticmethod
    def _bulk_insert(store: SQLiteStore, count: int, prefix: str = "") -> list[str]:
        """Insert `count` memories with skip_inference. Returns IDs."""
        ids = []
        for i in range(count):
            nid = store.store(
                content=f"{prefix}stress test memory number {i} about topic-{i % 50} with details-{i % 200}",
                session_id="stress-session",
                metadata={"event_type": "decision", "stress": True, "batch": i // 1000},
                skip_inference=True,
            )
            ids.append(nid)
        return ids

    def test_insert_throughput(self, stress_store):
        """Insert 1K / 5K / 10K — measure throughput and RSS."""
        scales = [1_000, 5_000, 10_000]
        rows = []
        cumulative = 0

        for scale in scales:
            # Unique prefix per batch to avoid content-hash dedup
            with MemoryTracker() as mem:
                with Stopwatch() as sw:
                    self._bulk_insert(stress_store, scale, prefix=f"[batch-{scale}] ")
            cumulative += scale

            ops_sec = scale / sw.elapsed if sw.elapsed > 0 else 0
            per_insert_ms = (sw.elapsed / scale) * 1000 if scale > 0 else 0
            total = stress_store.node_count()
            rows.append([
                f"{scale // 1000}K",
                f"{ops_sec:.0f}",
                f"{per_insert_ms:.2f}ms",
                f"{mem.rss_delta_mb:+.1f}MB",
                str(total),
            ])

        print_table(
            "Memory Store Insert Throughput",
            ["Scale", "Insert/s", "Per-insert", "RSS delta", "Total count"],
            rows,
        )

        # Sanity: cumulative total (each batch has unique prefix)
        assert stress_store.node_count() == cumulative

    def test_fts_query_latency(self, stress_store):
        """FTS5 query latency at 1K / 5K scale points."""
        queries = ["topic-5", "details-100", "stress test", "memory number", "batch"]
        scales = [1_000, 5_000]
        rows = []

        for scale in scales:
            self._bulk_insert(stress_store, scale)
            latencies = []
            for q in queries:
                for _ in range(5):
                    with Stopwatch() as sw:
                        stress_store.query(q, limit=10, use_cache=False)
                    latencies.append(sw.ms)

            p50 = percentile(latencies, 50)
            p99 = percentile(latencies, 99)
            total = stress_store.node_count()
            rows.append([f"{total // 1000}K", f"{p50:.1f}ms", f"{p99:.1f}ms", str(len(latencies))])

        print_table(
            "FTS5 Query Latency",
            ["DB size", "p50", "p99", "Samples"],
            rows,
        )

    def test_phrase_search_latency(self, stress_store):
        """Phrase search latency at scale."""
        self._bulk_insert(stress_store, 3_000)
        phrases = ["topic-10", "details-50", "stress test memory", "number 999", "batch"]
        latencies = []

        for phrase in phrases:
            for _ in range(5):
                with Stopwatch() as sw:
                    stress_store.phrase_search(phrase, limit=10)
                latencies.append(sw.ms)

        p50 = percentile(latencies, 50)
        p99 = percentile(latencies, 99)
        print_table(
            "Phrase Search Latency (3K memories)",
            ["Metric", "Value"],
            [["p50", f"{p50:.1f}ms"], ["p99", f"{p99:.1f}ms"], ["Samples", str(len(latencies))]],
        )

    def test_rss_growth_per_batch(self, stress_store):
        """RSS growth across 5 x 1K-memory batches."""
        rows = []
        for batch in range(5):
            rss_before = MemoryTracker._rss_bytes()
            self._bulk_insert(stress_store, 1_000, prefix=f"[rss-batch-{batch}] ")
            rss_after = MemoryTracker._rss_bytes()
            delta_mb = (rss_after - rss_before) / (1024 * 1024)
            rows.append([
                f"Batch {batch + 1}",
                f"{stress_store.node_count()}",
                f"{delta_mb:+.1f}MB",
                f"{rss_after / (1024 * 1024):.0f}MB",
            ])

        print_table(
            "RSS Growth Per 1K Batch",
            ["Batch", "Total memories", "RSS delta", "RSS total"],
            rows,
        )
        assert stress_store.node_count() == 5_000


# ---------------------------------------------------------------------------
# 2. Multi-Agent Coordination Scaling
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestCoordinationScaling:
    """Registration throughput, file claim contention, message bus latency."""

    def test_registration_throughput(self, stress_coord):
        """Register 10 / 25 / 50 / 100 agents via concurrent threads."""
        scales = [10, 25, 50, 100]
        rows = []

        for n in scales:
            # Deregister previous batch
            for i in range(n):
                stress_coord.deregister_session(f"agent-prev-{i}")

            def register(idx, _n=n):
                stress_coord.register_session(
                    f"agent-{_n}-{idx}",
                    pid=os.getpid(),
                    project="/stress/test",
                    capabilities=["stress"],
                )

            with Stopwatch() as sw:
                run_threads(register, n)

            ops_sec = n / sw.elapsed if sw.elapsed > 0 else 0
            rows.append([str(n), f"{sw.ms:.0f}ms", f"{ops_sec:.0f}"])

            # Cleanup
            for i in range(n):
                stress_coord.deregister_session(f"agent-{n}-{i}")

        print_table(
            "Registration Throughput (concurrent threads)",
            ["Agents", "Wall time", "Reg/s"],
            rows,
        )

    def test_file_claim_contention(self, stress_coord):
        """N agents compete for 20 files — measure success/conflict/error."""
        n_agents = 30
        n_files = 20
        files = [f"/stress/file-{i}.py" for i in range(n_files)]

        # Register all agents first
        for i in range(n_agents):
            stress_coord.register_session(f"claimer-{i}", pid=os.getpid(), project="/stress")

        successes = [0]
        conflicts = [0]
        errors = [0]
        lock = threading.Lock()

        def compete(idx):
            s = 0
            c = 0
            e = 0
            for f in files:
                result = stress_coord.claim_file(f"claimer-{idx}", f, task="editing")
                if result.get("success"):
                    s += 1
                elif result.get("conflict"):
                    c += 1
                else:
                    e += 1
            with lock:
                successes[0] += s
                conflicts[0] += c
                errors[0] += e

        with Stopwatch() as sw:
            run_threads(compete, n_agents)

        total_ops = n_agents * n_files
        print_table(
            f"File Claim Contention ({n_agents} agents x {n_files} files)",
            ["Metric", "Value"],
            [
                ["Total ops", str(total_ops)],
                ["Successes", str(successes[0])],
                ["Conflicts", str(conflicts[0])],
                ["Errors", str(errors[0])],
                ["Wall time", f"{sw.ms:.0f}ms"],
                ["Ops/sec", f"{total_ops / sw.elapsed:.0f}" if sw.elapsed > 0 else "N/A"],
            ],
        )

        # Every file should be claimed exactly once (success) and rest conflicts
        assert successes[0] + conflicts[0] + errors[0] == total_ops
        assert errors[0] == 0

        # Cleanup
        for i in range(n_agents):
            stress_coord.deregister_session(f"claimer-{i}")

    def test_message_bus_latency(self, stress_coord):
        """Send + inbox latency at 10 / 25 / 50 agents."""
        scales = [10, 25, 50]
        rows = []

        for n in scales:
            # Register agents
            for i in range(n):
                stress_coord.register_session(f"msg-{n}-{i}", pid=os.getpid(), project="/stress/msg")

            send_latencies = []
            inbox_latencies = []

            # Each agent sends a message to agent-0
            for i in range(1, n):
                with Stopwatch() as sw:
                    stress_coord.send_message(
                        f"msg-{n}-{i}",
                        subject=f"Test message from {i}",
                        msg_type="inform",
                        to_session=f"msg-{n}-0",
                        body=f"Stress test payload {i}",
                    )
                send_latencies.append(sw.ms)

            # Agent-0 checks inbox
            with Stopwatch() as sw:
                msgs = stress_coord.check_inbox(f"msg-{n}-0", unread_only=True)
            inbox_latencies.append(sw.ms)

            rows.append([
                str(n),
                f"{percentile(send_latencies, 50):.1f}ms",
                f"{percentile(send_latencies, 99):.1f}ms",
                f"{inbox_latencies[0]:.1f}ms",
                str(len(msgs)),
            ])

            # Cleanup
            for i in range(n):
                stress_coord.deregister_session(f"msg-{n}-{i}")

        print_table(
            "Message Bus Latency",
            ["Agents", "Send p50", "Send p99", "Inbox", "Msgs received"],
            rows,
        )

    def test_busy_timeout_breaking_point(self, stress_coord):
        """Ramp 10→200 threads, 15 ops each — find >5% error threshold."""
        ramp = [10, 25, 50, 100, 150, 200]
        rows = []

        for n in ramp:
            # Register sessions
            for i in range(n):
                stress_coord.register_session(f"busy-{n}-{i}", pid=os.getpid(), project="/stress/busy")

            ops_per_thread = 15
            error_count = [0]
            success_count = [0]
            lock = threading.Lock()

            def workload(idx, _n=n):
                s = 0
                e = 0
                sid = f"busy-{_n}-{idx}"
                for op in range(ops_per_thread):
                    try:
                        if op % 3 == 0:
                            stress_coord.heartbeat(sid)
                        elif op % 3 == 1:
                            stress_coord.claim_file(sid, f"/busy/file-{op}-{idx}.py")
                        else:
                            stress_coord.send_message(
                                sid, subject=f"op-{op}", msg_type="inform",
                                to_session=f"busy-{_n}-0",
                            )
                        s += 1
                    except Exception:
                        e += 1
                with lock:
                    success_count[0] += s
                    error_count[0] += e

            with Stopwatch() as sw:
                run_threads(workload, n)

            total = n * ops_per_thread
            error_pct = (error_count[0] / total * 100) if total > 0 else 0
            rows.append([
                str(n),
                str(total),
                str(success_count[0]),
                str(error_count[0]),
                f"{error_pct:.1f}%",
                f"{sw.ms:.0f}ms",
            ])

            # Cleanup
            for i in range(n):
                stress_coord.deregister_session(f"busy-{n}-{i}")

        print_table(
            "Busy Timeout Breaking Point (15 ops/thread)",
            ["Threads", "Total ops", "Success", "Errors", "Error %", "Wall time"],
            rows,
        )


# ---------------------------------------------------------------------------
# 3. Concurrent Read/Write
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestConcurrentReadWrite:
    """Mixed and pure-write contention on SQLiteStore."""

    def test_mixed_readers_writers(self, stress_store):
        """N writers + N readers (5→50 each), 20 ops per thread."""
        scales = [5, 10, 25, 50]
        rows = []

        for n in scales:
            write_errors = [0]
            read_errors = [0]
            lock = threading.Lock()
            # Pre-seed some data for readers
            for i in range(100):
                stress_store.store(
                    content=f"seed memory {i} for mixed test",
                    skip_inference=True,
                )

            def writer(idx):
                errs = 0
                for op in range(20):
                    try:
                        stress_store.store(
                            content=f"writer-{idx} op-{op} concurrent write test",
                            session_id=f"writer-{idx}",
                            skip_inference=True,
                        )
                    except Exception:
                        errs += 1
                with lock:
                    write_errors[0] += errs

            def reader(idx):
                errs = 0
                queries = ["seed memory", "concurrent", "writer", "mixed test"]
                for op in range(20):
                    try:
                        q = queries[op % len(queries)]
                        stress_store.query(q, limit=5, use_cache=False)
                    except Exception:
                        errs += 1
                with lock:
                    read_errors[0] += errs

            # Launch writers and readers together
            barrier = threading.Barrier(n * 2)

            def sync_writer(idx):
                barrier.wait(timeout=30)
                writer(idx)

            def sync_reader(idx):
                barrier.wait(timeout=30)
                reader(idx)

            threads = []
            for i in range(n):
                threads.append(threading.Thread(target=sync_writer, args=(i,)))
                threads.append(threading.Thread(target=sync_reader, args=(i,)))

            with Stopwatch() as sw:
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=120)

            total_ops = n * 20 * 2  # writers + readers
            rows.append([
                f"{n}W + {n}R",
                str(total_ops),
                str(write_errors[0]),
                str(read_errors[0]),
                f"{sw.ms:.0f}ms",
            ])

        print_table(
            "Mixed Readers/Writers (20 ops each)",
            ["Config", "Total ops", "Write errs", "Read errs", "Wall time"],
            rows,
        )

    def test_pure_write_contention(self, stress_store):
        """Pure write contention: 5→50 threads, 50 ops each."""
        scales = [5, 10, 25, 50]
        rows = []

        for n in scales:
            errors = [0]
            lock = threading.Lock()

            def writer(idx):
                errs = 0
                for op in range(50):
                    try:
                        stress_store.store(
                            content=f"contention-{idx}-{op} pure write stress",
                            session_id=f"writer-{idx}",
                            skip_inference=True,
                        )
                    except Exception:
                        errs += 1
                with lock:
                    errors[0] += errs

            with Stopwatch() as sw:
                run_threads(writer, n)

            total = n * 50
            rows.append([
                str(n),
                str(total),
                str(errors[0]),
                f"{sw.ms:.0f}ms",
                f"{total / sw.elapsed:.0f}" if sw.elapsed > 0 else "N/A",
            ])

        print_table(
            "Pure Write Contention (50 ops/thread)",
            ["Threads", "Total ops", "Errors", "Wall time", "Ops/sec"],
            rows,
        )


# ---------------------------------------------------------------------------
# 4. Resource Profiling
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestResourceProfiling:
    """tracemalloc traced allocation + RSS profiling."""

    def test_traced_allocation_per_batch(self, stress_store):
        """tracemalloc traced delta per 1K insert batch."""
        rows = []

        for batch in range(5):
            with MemoryTracker() as mem:
                for i in range(1_000):
                    stress_store.store(
                        content=f"profiling batch-{batch} item-{i} allocation test",
                        skip_inference=True,
                    )

            rows.append([
                f"Batch {batch + 1}",
                f"{mem.traced_mb:.2f}MB",
                f"{mem.peak_mb:.2f}MB",
                f"{mem.rss_delta_mb:+.1f}MB",
                str(stress_store.node_count()),
            ])

        print_table(
            "Traced Allocation Per 1K Batch",
            ["Batch", "Traced delta", "Traced peak", "RSS delta", "Total memories"],
            rows,
        )

    def test_peak_rss_profiling(self, stress_store):
        """Peak RSS before and after 5K inserts + queries."""
        rss_start = MemoryTracker._rss_bytes()

        # Insert 5K
        for i in range(5_000):
            stress_store.store(
                content=f"rss profiling memory {i} with assorted content topic-{i % 100}",
                skip_inference=True,
            )

        rss_after_insert = MemoryTracker._rss_bytes()

        # Run 100 queries
        for i in range(100):
            stress_store.query(f"topic-{i}", limit=10, use_cache=False)

        rss_after_query = MemoryTracker._rss_bytes()

        print_table(
            "Peak RSS Profiling",
            ["Phase", "RSS (MB)", "Delta (MB)"],
            [
                ["Start", f"{rss_start / (1024 * 1024):.0f}", "-"],
                ["After 5K inserts", f"{rss_after_insert / (1024 * 1024):.0f}",
                 f"{(rss_after_insert - rss_start) / (1024 * 1024):+.1f}"],
                ["After 100 queries", f"{rss_after_query / (1024 * 1024):.0f}",
                 f"{(rss_after_query - rss_after_insert) / (1024 * 1024):+.1f}"],
            ],
        )

    def test_query_memory_overhead_by_limit(self, stress_store):
        """Per-query memory overhead at result limits 5→100."""
        # Seed data
        for i in range(2_000):
            stress_store.store(
                content=f"overhead test memory {i} topic-{i % 20}",
                skip_inference=True,
            )

        limits = [5, 10, 25, 50, 100]
        rows = []

        for limit in limits:
            latencies = []
            traced_deltas = []

            for _ in range(10):
                with MemoryTracker() as mem:
                    with Stopwatch() as sw:
                        stress_store.query("overhead test", limit=limit, use_cache=False)
                latencies.append(sw.ms)
                traced_deltas.append(mem.traced_mb)

            rows.append([
                str(limit),
                f"{percentile(latencies, 50):.1f}ms",
                f"{percentile(latencies, 99):.1f}ms",
                f"{percentile(traced_deltas, 50):.3f}MB",
            ])

        print_table(
            "Query Memory Overhead by Limit (2K memories)",
            ["Limit", "Latency p50", "Latency p99", "Traced p50"],
            rows,
        )


# ---------------------------------------------------------------------------
# 5. Entity Module Scaling
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestEntityScaling:
    """Entity creation, relationships, tree traversal at scale."""

    def test_entity_creation_throughput(self, stress_entity):
        """Create 100 entities — measure throughput."""
        with Stopwatch() as sw:
            for i in range(100):
                stress_entity.create_entity(
                    entity_id=f"ent-{i}",
                    name=f"Entity {i}",
                    entity_type="company",
                    jurisdiction="US-DE",
                    metadata={"stress": True, "index": i},
                )

        ops_sec = 100 / sw.elapsed if sw.elapsed > 0 else 0
        print_table(
            "Entity Creation Throughput",
            ["Metric", "Value"],
            [
                ["Entities created", "100"],
                ["Wall time", f"{sw.ms:.0f}ms"],
                ["Ops/sec", f"{ops_sec:.0f}"],
            ],
        )

    def test_relationship_creation_throughput(self, stress_entity):
        """Create 200 relationships — measure throughput."""
        # Create 50 entities first
        for i in range(50):
            stress_entity.create_entity(
                entity_id=f"rel-{i}",
                name=f"RelEntity {i}",
                entity_type="llc",
            )

        rel_types = list(["parent_of", "subsidiary_of", "owned_by", "partner_of"])
        created = 0
        with Stopwatch() as sw:
            for i in range(50):
                for j in range(1, 5):
                    target = (i + j) % 50
                    if target != i:
                        result = stress_entity.add_relationship(
                            source_entity_id=f"rel-{i}",
                            target_entity_id=f"rel-{target}",
                            relationship_type=rel_types[j - 1],
                        )
                        if not result.startswith("Error"):
                            created += 1

        ops_sec = created / sw.elapsed if sw.elapsed > 0 else 0
        print_table(
            "Relationship Creation Throughput",
            ["Metric", "Value"],
            [
                ["Relationships created", str(created)],
                ["Wall time", f"{sw.ms:.0f}ms"],
                ["Ops/sec", f"{ops_sec:.0f}"],
            ],
        )

    def test_tree_traversal_depth(self, stress_entity):
        """4-level tree: root → 5 → 25 → 75 (106 entities total)."""
        # Create root
        stress_entity.create_entity(entity_id="root", name="Root Corp", entity_type="c_corp")

        # Level 1: 5 children
        for i in range(5):
            eid = f"l1-{i}"
            stress_entity.create_entity(entity_id=eid, name=f"Level1-{i}", entity_type="llc")
            stress_entity.add_relationship("root", eid, "parent_of")

        # Level 2: 5 children per L1 = 25
        for i in range(5):
            for j in range(5):
                eid = f"l2-{i}-{j}"
                stress_entity.create_entity(entity_id=eid, name=f"Level2-{i}-{j}", entity_type="startup")
                stress_entity.add_relationship(f"l1-{i}", eid, "parent_of")

        # Level 3: 3 children per L2 = 75
        for i in range(5):
            for j in range(5):
                for k in range(3):
                    eid = f"l3-{i}-{j}-{k}"
                    stress_entity.create_entity(entity_id=eid, name=f"Level3-{i}-{j}-{k}", entity_type="company")
                    stress_entity.add_relationship(f"l2-{i}-{j}", eid, "parent_of")

        # Traverse from root
        with Stopwatch() as sw:
            tree = stress_entity.get_entity_tree("root")

        # Verify it produced output (markdown string)
        assert len(tree) > 100, "Tree output too small"
        print_table(
            "Entity Tree Traversal (106 entities, 4 levels)",
            ["Metric", "Value"],
            [
                ["Total entities", "106"],
                ["Tree output length", f"{len(tree)} chars"],
                ["Traversal time", f"{sw.ms:.1f}ms"],
            ],
        )

    def test_entity_scoped_query(self, stress_store, stress_entity):
        """2000 memories across 20 entities — scoped vs global query."""
        # Create entities
        for i in range(20):
            stress_entity.create_entity(
                entity_id=f"scope-{i}",
                name=f"ScopeEntity {i}",
                entity_type="company",
            )

        # Store 100 memories per entity
        for i in range(20):
            for j in range(100):
                stress_store.store(
                    content=f"entity scope-{i} memory {j} about finance topic-{j % 10}",
                    metadata={"event_type": "decision", "entity_id": f"scope-{i}"},
                    skip_inference=True,
                    entity_id=f"scope-{i}",
                )

        assert stress_store.node_count() == 2_000

        # Scoped query (single entity)
        scoped_latencies = []
        for _ in range(10):
            with Stopwatch() as sw:
                stress_store.query("finance topic", limit=10, use_cache=False, entity_id="scope-5")
            scoped_latencies.append(sw.ms)

        # Global query (all entities)
        global_latencies = []
        for _ in range(10):
            with Stopwatch() as sw:
                stress_store.query("finance topic", limit=10, use_cache=False)
            global_latencies.append(sw.ms)

        print_table(
            "Entity-Scoped vs Global Query (2K memories, 20 entities)",
            ["Query type", "p50", "p99"],
            [
                ["Scoped (1 entity)", f"{percentile(scoped_latencies, 50):.1f}ms",
                 f"{percentile(scoped_latencies, 99):.1f}ms"],
                ["Global (all)", f"{percentile(global_latencies, 50):.1f}ms",
                 f"{percentile(global_latencies, 99):.1f}ms"],
            ],
        )


# ---------------------------------------------------------------------------
# 6. Graph Traversal Scaling
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestGraphTraversalScaling:
    """200 nodes + 600 edges — traversal at 1→5 hops."""

    def _build_graph(self, store: SQLiteStore, n_nodes: int = 200, edges_per_node: int = 3) -> list[str]:
        """Build a graph of n_nodes with ~edges_per_node outgoing edges each."""
        ids = []
        for i in range(n_nodes):
            nid = store.store(
                content=f"graph node {i} in cluster-{i % 10} with data-{i % 50}",
                skip_inference=True,
            )
            ids.append(nid)

        # Add edges (connect to next nodes in a wrap-around pattern)
        edge_count = 0
        for i in range(n_nodes):
            for offset in range(1, edges_per_node + 1):
                target = (i + offset * 7) % n_nodes  # spread connections
                if target != i:
                    store.add_edge(ids[i], ids[target], edge_type="related", weight=0.8)
                    edge_count += 1

        return ids

    def test_traversal_by_hops(self, stress_store):
        """Traversal at 1→5 hops — p50/p99 latency and result sizes."""
        ids = self._build_graph(stress_store)
        hops_range = [1, 2, 3, 4, 5]
        rows = []

        # Pick a few start nodes spread across the graph
        start_nodes = [ids[0], ids[50], ids[100], ids[150], ids[199]]

        for max_hops in hops_range:
            latencies = []
            result_sizes = []

            for start_id in start_nodes:
                for _ in range(3):
                    with Stopwatch() as sw:
                        results = stress_store.get_related_chain(
                            start_id, max_hops=max_hops, min_weight=0.0
                        )
                    latencies.append(sw.ms)
                    result_sizes.append(len(results))

            rows.append([
                str(max_hops),
                f"{percentile(latencies, 50):.1f}ms",
                f"{percentile(latencies, 99):.1f}ms",
                f"{percentile(result_sizes, 50):.0f}",
                str(max(result_sizes)),
            ])

        print_table(
            "Graph Traversal (200 nodes, ~600 edges)",
            ["Max hops", "Latency p50", "Latency p99", "Results p50", "Results max"],
            rows,
        )
        assert stress_store.node_count() == 200
