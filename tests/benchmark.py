#!/usr/bin/env python3
"""Benchmark tests for LCM — measures performance characteristics.

Benchmarks (all use synthetic data, no LLM calls):
1. Compaction efficiency — token savings at different message volumes
2. DAG depth scaling — condensation levels vs message count
3. Search latency — FTS/regex over growing stores
4. Compaction speed — wall-clock time for leaf pass
5. Context assembly — time to query active context at various depths
6. Memory overhead — DB file size vs raw message size
7. Ingest throughput — messages/second ingestion rate

Note: LLM-Map throughput is excluded since it requires the claude CLI.
Run tests/benchmark_llm.py for that (requires API access).
"""

import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import lcm_common


def generate_message(i: int, size: int = 200) -> str:
    """Generate a synthetic message of approximately `size` chars."""
    topics = [
        "database migration strategy using blue-green deployment",
        "API rate limiting configuration with token buckets",
        "authentication middleware refactoring for OAuth2",
        "CI/CD pipeline optimization with parallel test stages",
        "memory leak investigation in the event processing loop",
        "configuration management with environment-specific overrides",
        "error handling improvement in the data ingestion pipeline",
        "performance profiling of the query optimizer module",
    ]
    topic = topics[i % len(topics)]
    padding = f" Discussion point {i}: {topic}. " * (size // 60 + 1)
    return padding[:size]


def setup_test_env():
    """Create a temporary test environment."""
    tmp_dir = tempfile.mkdtemp(prefix="lcm_bench_")
    db_path = os.path.join(tmp_dir, "bench.db")
    env_file = os.path.join(tmp_dir, "session.env")

    os.environ["LCM_DB"] = db_path
    os.environ["LCM_ENV_FILE"] = env_file
    os.environ["LCM_FILES_DIR"] = os.path.join(tmp_dir, "files")

    return tmp_dir, db_path


def init_session(db_path):
    """Initialize a test session and return conversation ID."""
    import lcm_init
    sys.argv = ["lcm_init", "--db", db_path, "--session-id", "bench_sess"]
    lcm_init.main()
    lcm_common.load_session_env()
    return lcm_common.get_conversation_id()


def ingest_messages(n: int, msg_size: int = 200):
    """Ingest n messages, return elapsed time."""
    import lcm_ingest

    start = time.perf_counter()
    for i in range(n):
        content = generate_message(i, msg_size)
        sys.argv = ["lcm_ingest", "--role", ["user", "assistant", "tool"][i % 3],
                     "--content", content]
        lcm_ingest.main()
    elapsed = time.perf_counter() - start
    return elapsed


def create_leaf_summaries(con, conv_id, n_summaries):
    """Create synthetic leaf summaries for benchmarking condensation/search."""
    for i in range(n_summaries):
        sum_id = lcm_common.generate_id("sum")
        content = f"Summary {i}: " + generate_message(i, 400)
        token_count = lcm_common.estimate_tokens(content)

        con.execute(
            """
            INSERT INTO summaries (id, conversation_id, kind, depth, content,
                                   token_count, earliest_at, latest_at, descendant_count)
            VALUES (?, ?, 'leaf', 0, ?, ?, datetime('now', ?), datetime('now'), ?)
            """,
            (sum_id, conv_id, content, token_count, f"-{n_summaries - i} minutes", 5),
        )
        con.execute(
            "INSERT INTO context_items (conversation_id, item_type, item_id, position) "
            "VALUES (?, 'summary', ?, ?)",
            (conv_id, sum_id, i),
        )
    con.commit()


def bench_ingest_throughput():
    """Benchmark 1: Ingest throughput at different volumes."""
    print("\n═══ Benchmark 1: Ingest Throughput ═══")
    print(f"{'Messages':>10} │ {'Time (s)':>10} │ {'Msgs/sec':>10}")
    print("───────────┼────────────┼────────────")

    for n in [50, 100, 500, 1000]:
        tmp_dir, db_path = setup_test_env()
        init_session(db_path)

        elapsed = ingest_messages(n)
        rate = n / elapsed if elapsed > 0 else 0

        print(f"{n:>10} │ {elapsed:>10.3f} │ {rate:>10.1f}")

        # Cleanup
        os.remove(db_path)


def bench_compaction_efficiency():
    """Benchmark 2: Token savings from compaction (simulated, no LLM)."""
    print("\n═══ Benchmark 2: Compaction Efficiency (Simulated) ═══")
    print(f"{'Messages':>10} │ {'Raw tokens':>12} │ {'After compact':>14} │ {'Savings':>8}")
    print("───────────┼──────────────┼────────────────┼──────────")

    for n in [50, 100, 500, 1000]:
        tmp_dir, db_path = setup_test_env()
        conv_id = init_session(db_path)
        ingest_messages(n, msg_size=300)

        con = lcm_common.get_connection()

        # Raw token total
        raw_tokens = con.execute(
            "SELECT COALESCE(SUM(token_count), 0) FROM messages WHERE conversation_id = ?",
            (conv_id,),
        ).fetchone()[0]

        # Simulate compaction: group into chunks, estimate summary size
        fresh_tail = lcm_common.get_config_int("LCM_FRESH_TAIL_COUNT")
        compactable = max(0, n - fresh_tail)
        target = lcm_common.get_config_int("LCM_LEAF_TARGET_TOKENS")
        chunk_size = lcm_common.get_config_int("LCM_LEAF_CHUNK_TOKENS")

        # Estimate: each chunk of ~chunk_size tokens → ~target tokens
        compactable_tokens = int(raw_tokens * compactable / n) if n > 0 else 0
        n_chunks = max(1, compactable_tokens // chunk_size) if compactable_tokens > 0 else 0
        summary_tokens = n_chunks * target
        fresh_tail_tokens = raw_tokens - compactable_tokens
        after_tokens = fresh_tail_tokens + summary_tokens

        savings = ((raw_tokens - after_tokens) / raw_tokens * 100) if raw_tokens > 0 else 0

        print(f"{n:>10} │ {raw_tokens:>12} │ {after_tokens:>14} │ {savings:>7.1f}%")

        con.close()
        os.remove(db_path)


def bench_dag_depth_scaling():
    """Benchmark 3: DAG depth at various message volumes."""
    print("\n═══ Benchmark 3: DAG Depth Scaling (Simulated) ═══")
    print(f"{'Messages':>10} │ {'Leaf sums':>10} │ {'Min fanout':>10} │ {'Max depth':>10}")
    print("───────────┼────────────┼────────────┼────────────")

    min_fanout = lcm_common.get_config_int("LCM_CONDENSED_MIN_FANOUT")
    chunk_tokens = lcm_common.get_config_int("LCM_LEAF_CHUNK_TOKENS")
    fresh_tail = lcm_common.get_config_int("LCM_FRESH_TAIL_COUNT")

    for n in [50, 100, 500, 1000, 5000]:
        compactable = max(0, n - fresh_tail)
        avg_msg_tokens = 75  # ~300 chars
        compactable_tokens = compactable * avg_msg_tokens
        n_leaves = max(1, compactable_tokens // chunk_tokens) if compactable_tokens > 0 else 0

        # Calculate depth: how many times can we condense by min_fanout?
        depth = 0
        nodes_at_level = n_leaves
        while nodes_at_level >= min_fanout:
            nodes_at_level = nodes_at_level // min_fanout
            depth += 1

        print(f"{n:>10} │ {n_leaves:>10} │ {min_fanout:>10} │ {depth:>10}")


def bench_search_latency():
    """Benchmark 4: Search latency over growing stores."""
    print("\n═══ Benchmark 4: Search Latency ═══")
    print(f"{'Messages':>10} │ {'FTS (ms)':>10} │ {'Regex (ms)':>10} │ {'FTS hits':>10}")
    print("───────────┼────────────┼────────────┼────────────")

    for n in [100, 500, 1000]:
        tmp_dir, db_path = setup_test_env()
        conv_id = init_session(db_path)
        ingest_messages(n)

        con = lcm_common.get_connection()

        # FTS search
        start = time.perf_counter()
        for _ in range(10):
            results = con.execute(
                "SELECT COUNT(*) FROM messages m "
                "JOIN messages_fts f ON f.rowid = m.rowid "
                "WHERE messages_fts MATCH 'migration'",
            ).fetchone()[0]
        fts_ms = (time.perf_counter() - start) / 10 * 1000

        # Regex search (Python-side)
        import re
        pattern = re.compile(r"migration.*deployment", re.IGNORECASE)
        start = time.perf_counter()
        for _ in range(10):
            rows = con.execute(
                "SELECT content FROM messages WHERE conversation_id = ?",
                (conv_id,),
            ).fetchall()
            hits = sum(1 for r in rows if pattern.search(r[0]))
        regex_ms = (time.perf_counter() - start) / 10 * 1000

        print(f"{n:>10} │ {fts_ms:>10.2f} │ {regex_ms:>10.2f} │ {results:>10}")

        con.close()
        os.remove(db_path)


def bench_compaction_speed():
    """Benchmark 5: Compaction speed (dry-run, measures query overhead)."""
    print("\n═══ Benchmark 5: Compaction Query Speed ═══")
    print(f"{'Messages':>10} │ {'Find eligible (ms)':>18} │ {'Chunk (ms)':>12}")
    print("───────────┼────────────────────┼──────────────")

    for n in [100, 500, 1000]:
        tmp_dir, db_path = setup_test_env()
        conv_id = init_session(db_path)
        ingest_messages(n)

        con = lcm_common.get_connection()
        fresh_tail = lcm_common.get_config_int("LCM_FRESH_TAIL_COUNT")
        chunk_tokens = lcm_common.get_config_int("LCM_LEAF_CHUNK_TOKENS")

        # Time: find compactable messages
        start = time.perf_counter()
        for _ in range(10):
            import lcm_compact
            msgs = lcm_compact.get_compactable_messages(con, conv_id, fresh_tail)
        find_ms = (time.perf_counter() - start) / 10 * 1000

        # Time: chunk them
        start = time.perf_counter()
        for _ in range(10):
            chunks = lcm_compact.chunk_messages(msgs, chunk_tokens)
        chunk_ms = (time.perf_counter() - start) / 10 * 1000

        print(f"{n:>10} │ {find_ms:>18.2f} │ {chunk_ms:>12.2f}")

        con.close()
        os.remove(db_path)


def bench_context_assembly():
    """Benchmark 6: Context assembly time from DAG."""
    print("\n═══ Benchmark 6: Context Assembly Speed ═══")
    print(f"{'Summaries':>10} │ {'Messages':>10} │ {'Assembly (ms)':>14}")
    print("───────────┼────────────┼────────────────")

    for n_sums in [10, 50, 100, 200]:
        tmp_dir, db_path = setup_test_env()
        conv_id = init_session(db_path)
        ingest_messages(32)  # Fresh tail

        con = lcm_common.get_connection()
        create_leaf_summaries(con, conv_id, n_sums)

        # Time: query context_items with join
        start = time.perf_counter()
        for _ in range(100):
            con.execute(
                """
                SELECT ci.item_type, ci.item_id, ci.position,
                       CASE ci.item_type
                           WHEN 'message' THEN m.token_count
                           WHEN 'summary' THEN s.token_count
                       END as tokens
                FROM context_items ci
                LEFT JOIN messages m ON ci.item_type = 'message' AND ci.item_id = m.id
                LEFT JOIN summaries s ON ci.item_type = 'summary' AND ci.item_id = s.id
                WHERE ci.conversation_id = ?
                ORDER BY ci.position
                """,
                (conv_id,),
            ).fetchall()
        assembly_ms = (time.perf_counter() - start) / 100 * 1000

        total_items = 32 + n_sums
        print(f"{n_sums:>10} │ {32:>10} │ {assembly_ms:>14.2f}")

        con.close()
        os.remove(db_path)


def bench_memory_overhead():
    """Benchmark 7: DB file size vs raw message size."""
    print("\n═══ Benchmark 7: Memory Overhead ═══")
    print(f"{'Messages':>10} │ {'Raw (KB)':>10} │ {'DB (KB)':>10} │ {'Overhead':>10}")
    print("───────────┼────────────┼────────────┼────────────")

    for n in [100, 500, 1000]:
        tmp_dir, db_path = setup_test_env()
        init_session(db_path)

        # Calculate raw size
        raw_bytes = sum(len(generate_message(i, 300).encode()) for i in range(n))
        ingest_messages(n, msg_size=300)

        # Force WAL checkpoint to get accurate file size
        con = lcm_common.get_connection()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.close()

        db_bytes = os.path.getsize(db_path)
        overhead = (db_bytes / raw_bytes - 1) * 100 if raw_bytes > 0 else 0

        print(f"{n:>10} │ {raw_bytes/1024:>10.1f} │ {db_bytes/1024:>10.1f} │ {overhead:>9.1f}%")

        os.remove(db_path)


def main():
    print("=" * 60)
    print("LCM Benchmark Suite")
    print("=" * 60)

    bench_ingest_throughput()
    bench_compaction_efficiency()
    bench_dag_depth_scaling()
    bench_search_latency()
    bench_compaction_speed()
    bench_context_assembly()
    bench_memory_overhead()

    print("\n" + "=" * 60)
    print("All benchmarks complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
