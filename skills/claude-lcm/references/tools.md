# LCM Tool Interfaces

All tools are Python scripts in the `scripts/` directory.
Invoke them directly from Claude Code tool calls.

---

## lcm_init

Initialize the LCM store for a new session.

```bash
python3 scripts/lcm_init.py [--db PATH] [--session-id ID]
```

**Output:**
```
LCM initialized
Session ID: sess_abc123
DB: ~/.claude-lcm/lcm.db
Conversation ID: conv_def456
```

Creates `~/.claude-lcm/lcm.db` if it doesn't exist.
Creates a new conversation record and returns IDs.
Safe to run multiple times (idempotent schema creation).

---

## lcm_ingest

Persist a message into the immutable store.

```bash
python3 scripts/lcm_ingest.py --role user|assistant|tool \
                               --content "..." \
                               [--conversation-id ID] \
                               [--tokens N]
```

**Output:** `message_id: msg_xyz789`

Called automatically by the context control loop.
You rarely need to call this manually.

---

## lcm_status

Report current context health.

```bash
python3 scripts/lcm_status.py [--conversation-id ID]
```

**Output:**
```
Session:          sess_abc123
Conversation:     conv_def456
Messages:         47 total, 32 in fresh tail, 15 compactable
Summaries:        3 leaf, 1 condensed
Est. tokens:      68,420 / 200,000 (34.2%)
Threshold:        150,000 (75%)
Status:           OK — no compaction needed
```

---

## lcm_compact

Run a compaction pass.

```bash
python3 scripts/lcm_compact.py [--conversation-id ID] \
                                [--mode leaf|full] \
                                [--dry-run]
```

**Modes:**
- `leaf`: compact raw messages into leaf summaries only
- `full`: leaf pass + condensation up the DAG (default)

Uses `claude -p` for summarization (inherits parent model by default).

---

## lcm_grep

Search the immutable store.

```bash
python3 scripts/lcm_grep.py PATTERN \
                             [--scope messages|summaries|both] \
                             [--mode regex|fulltext] \
                             [--conversation-id ID] \
                             [--all-conversations] \
                             [--since ISO_DATE] \
                             [--before ISO_DATE] \
                             [--limit N]
```

Regex mode uses Python `re` module (works on all systems).
Fulltext mode uses SQLite FTS5.

---

## lcm_describe

Inspect a summary node or large file by ID.

```bash
python3 scripts/lcm_describe.py ID
```

Accepts `sum_*` (summary) or `file_*` (large file) IDs.

---

## lcm_expand

Expand a summary node back to its source messages.
**Restricted to sub-agents.** Main agent should use `lcm_expand_query` instead.

```bash
python3 scripts/lcm_expand.py SUMMARY_ID [--max-tokens N]
```

**Output:** The full source messages covered by this summary.

---

## lcm_expand_query

Deep recall via focused question. Safe for main agent use.
Internally finds relevant summaries and uses `claude -p` to answer.

```bash
python3 scripts/lcm_expand_query.py --prompt "What migration strategy was decided?" \
                                     [--query "database migration"] \
                                     [--summary-ids "sum_abc,sum_def"] \
                                     [--max-tokens 2000]
```

**Output:** A compact answer with cited summary IDs.

---

## lcm_checkpoint

Write a session checkpoint file before ending a long session.

```bash
python3 scripts/lcm_checkpoint.py [--output .lcm-checkpoint.md]
```

**Output:** Writes `.lcm-checkpoint.md` to workspace root.

---

## lcm_resume

Resume a session from a checkpoint.

```bash
python3 scripts/lcm_resume.py [--checkpoint .lcm-checkpoint.md]
```

Reads the checkpoint, validates the DB is accessible, and reconstructs
working state summary for the active context.

---

## lcm_llm_map

Process items in a JSONL file via parallel `claude -p` calls.
Implements the LLM-Map operator from the LCM paper.

```bash
python3 scripts/lcm_llm_map.py \
  --input data.jsonl \
  --output results.jsonl \
  --prompt "Extract entities from: " \
  --schema output_schema.json \
  --concurrency 16 \
  --max-retries 3
```

Each item is a single stateless LLM call. The engine handles iteration,
concurrency, schema validation, and retries.

---

## lcm_agentic_map

Process items via full claude sub-agent sessions.
Implements the Agentic-Map operator from the LCM paper.

```bash
python3 scripts/lcm_agentic_map.py \
  --input tasks.jsonl \
  --output results.jsonl \
  --prompt "Analyze this repository" \
  --concurrency 4 \
  --read-only
```

Each item gets a full sub-agent session with tool access (file I/O, code execution).
Use `--read-only` to restrict agents to read-only operations.
Lower default concurrency (4) than LLM-Map since each agent is heavier.
