#!/usr/bin/env python3
"""End-to-end smoke test for the LCM pipeline.

Runs: init → ingest messages → status → grep → describe → compact --dry-run
Uses a temporary DB so it doesn't affect real sessions.
Does NOT test LLM calls (compact without --dry-run, expand_query) since those
require claude CLI. See tests/test_with_llm.py for those.
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# Add scripts dir to path
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import lcm_common


class SmokeTest:
    def __init__(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="lcm_test_")
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        self.env_file = os.path.join(self.tmp_dir, "session.env")
        self.passed = 0
        self.failed = 0

    def setup_env(self):
        os.environ["LCM_DB"] = self.db_path
        os.environ["LCM_ENV_FILE"] = self.env_file
        os.environ["LCM_FILES_DIR"] = os.path.join(self.tmp_dir, "files")

    def assert_true(self, condition, message):
        if condition:
            self.passed += 1
            print(f"  PASS: {message}")
        else:
            self.failed += 1
            print(f"  FAIL: {message}")

    def assert_equal(self, actual, expected, message):
        if actual == expected:
            self.passed += 1
            print(f"  PASS: {message}")
        else:
            self.failed += 1
            print(f"  FAIL: {message} (expected {expected}, got {actual})")

    def test_init(self):
        print("\n── Test: lcm_init ──")
        import lcm_init

        sys.argv = ["lcm_init", "--db", self.db_path, "--session-id", "test_sess"]
        lcm_init.main()

        self.assert_true(os.path.isfile(self.db_path), "DB file created")
        self.assert_true(os.path.isfile(self.env_file), "Env file created")

        # Verify schema
        con = sqlite3.connect(self.db_path)
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]

        self.assert_true("messages" in tables, "messages table exists")
        self.assert_true("summaries" in tables, "summaries table exists")
        self.assert_true("summary_messages" in tables, "summary_messages table exists")
        self.assert_true("summary_parents" in tables, "summary_parents table exists")
        self.assert_true("context_items" in tables, "context_items table exists")
        self.assert_true("large_files" in tables, "large_files table exists")
        self.assert_true("conversations" in tables, "conversations table exists")

        # Check FTS tables
        vtables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_fts%'"
        ).fetchall()]
        self.assert_true("messages_fts" in vtables, "messages_fts virtual table exists")
        self.assert_true("summaries_fts" in vtables, "summaries_fts virtual table exists")

        # Check triggers (including DELETE triggers — bug fix verification)
        triggers = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()]
        self.assert_true("messages_fts_insert" in triggers, "messages FTS INSERT trigger exists")
        self.assert_true("messages_fts_delete" in triggers, "messages FTS DELETE trigger exists")
        self.assert_true("summaries_fts_insert" in triggers, "summaries FTS INSERT trigger exists")
        self.assert_true("summaries_fts_delete" in triggers, "summaries FTS DELETE trigger exists")

        # Check conversation was created
        convs = con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        self.assert_equal(convs, 1, "One conversation created")

        con.close()

    def test_ingest(self):
        print("\n── Test: lcm_ingest ──")
        lcm_common.load_session_env()
        import lcm_ingest

        test_messages = [
            ("user", "What is the database migration strategy?"),
            ("assistant", "I recommend using a blue-green deployment approach with rollback capability."),
            ("user", "Let's set the compaction threshold to 25000 tokens."),
            ("assistant", "Updated LCM_LEAF_CHUNK_TOKENS to 25000."),
            ("tool", "File written: config.json with threshold=25000"),
        ]

        for role, content in test_messages:
            sys.argv = ["lcm_ingest", "--role", role, "--content", content]
            lcm_ingest.main()

        con = lcm_common.get_connection()
        conv_id = lcm_common.get_conversation_id()

        msg_count = con.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv_id,)
        ).fetchone()[0]
        self.assert_equal(msg_count, 5, "5 messages ingested")

        # Check context_items
        ci_count = con.execute(
            "SELECT COUNT(*) FROM context_items WHERE conversation_id = ?", (conv_id,)
        ).fetchone()[0]
        self.assert_equal(ci_count, 5, "5 context items created")

        # Verify token estimation
        row = con.execute(
            "SELECT token_count FROM messages WHERE conversation_id = ? LIMIT 1",
            (conv_id,),
        ).fetchone()
        self.assert_true(row[0] > 0, "Token count estimated > 0")

        # Verify FTS indexing
        fts_results = con.execute(
            "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'migration'"
        ).fetchone()[0]
        self.assert_true(fts_results > 0, "FTS indexed message content")

        con.close()

    def test_status(self):
        print("\n── Test: lcm_status ──")
        import lcm_status

        sys.argv = ["lcm_status"]
        lcm_status.main()
        # If it runs without error, the test passes
        self.assert_true(True, "lcm_status ran without error")

    def test_grep_fulltext(self):
        print("\n── Test: lcm_grep (fulltext) ──")
        import lcm_grep

        sys.argv = ["lcm_grep", "migration", "--scope", "messages"]
        lcm_grep.main()
        self.assert_true(True, "lcm_grep fulltext ran without error")

    def test_grep_regex(self):
        print("\n── Test: lcm_grep (regex) ──")
        import lcm_grep

        sys.argv = ["lcm_grep", "threshold.*25000", "--mode", "regex", "--scope", "messages"]
        lcm_grep.main()
        self.assert_true(True, "lcm_grep regex ran without error")

    def test_compact_dry_run(self):
        print("\n── Test: lcm_compact --dry-run ──")

        # First add enough messages to have something compactable
        import lcm_ingest
        for i in range(35):  # More than fresh tail (32)
            sys.argv = ["lcm_ingest", "--role", "user", "--content", f"Test message {i} for compaction testing."]
            lcm_ingest.main()

        import lcm_compact
        sys.argv = ["lcm_compact", "--dry-run"]
        lcm_compact.main()
        self.assert_true(True, "lcm_compact --dry-run ran without error")

        # Verify no summaries were actually created (dry run)
        con = lcm_common.get_connection()
        conv_id = lcm_common.get_conversation_id()
        sum_count = con.execute(
            "SELECT COUNT(*) FROM summaries WHERE conversation_id = ?", (conv_id,)
        ).fetchone()[0]
        self.assert_equal(sum_count, 0, "No summaries created in dry run")
        con.close()

    def test_describe_nonexistent(self):
        print("\n── Test: lcm_describe (nonexistent) ──")
        import lcm_describe

        sys.argv = ["lcm_describe", "sum_nonexistent"]
        lcm_describe.main()
        self.assert_true(True, "lcm_describe handles nonexistent ID gracefully")

    def test_checkpoint(self):
        print("\n── Test: lcm_checkpoint ──")
        import lcm_checkpoint

        checkpoint_path = os.path.join(self.tmp_dir, "test-checkpoint.md")
        sys.argv = ["lcm_checkpoint", "--output", checkpoint_path]
        lcm_checkpoint.main()

        self.assert_true(os.path.isfile(checkpoint_path), "Checkpoint file created")

        content = Path(checkpoint_path).read_text()
        self.assert_true("Session ID" in content, "Checkpoint contains session ID")
        self.assert_true("Conversation ID" in content, "Checkpoint contains conversation ID")
        self.assert_true("Resume Instructions" in content, "Checkpoint contains resume instructions")

    def test_schema_integrity(self):
        print("\n── Test: Schema integrity ──")
        con = lcm_common.get_connection()

        # Test foreign key enforcement
        try:
            con.execute(
                "INSERT INTO messages (id, conversation_id, role, content) "
                "VALUES ('test', 'nonexistent_conv', 'user', 'test')"
            )
            con.commit()
            self.assert_true(False, "Foreign key constraint should have failed")
        except sqlite3.IntegrityError:
            self.assert_true(True, "Foreign key constraints enforced")

        con.close()

    def run_all(self):
        print("=" * 60)
        print("LCM Smoke Test")
        print("=" * 60)

        self.setup_env()

        self.test_init()
        self.test_ingest()
        self.test_status()
        self.test_grep_fulltext()
        self.test_grep_regex()
        self.test_compact_dry_run()
        self.test_describe_nonexistent()
        self.test_checkpoint()
        self.test_schema_integrity()

        print("\n" + "=" * 60)
        print(f"Results: {self.passed} passed, {self.failed} failed")
        print(f"Temp dir: {self.tmp_dir}")
        print("=" * 60)

        return self.failed == 0


if __name__ == "__main__":
    test = SmokeTest()
    success = test.run_all()
    sys.exit(0 if success else 1)
