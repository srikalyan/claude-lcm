# LCM Tool Interfaces

All tools are bash scripts in the `scripts/` directory.
Invoke them directly from Claude Code tool calls.

---

## lcm_init

Initialize the LCM store for a new session.

```bash
bash scripts/lcm_init.sh [--db PATH] [--session-id ID]
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
Safe to run multiple times (idempotent).

---

## lcm_ingest

Persist a message into the immutable store.

```bash
bash scripts/lcm_ingest.sh --role user|assistant|tool \
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
bash scripts/lcm_status.sh [--conversation-id ID]
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
bash scripts/lcm_compact.sh [--conversation-id ID] \
                             [--mode leaf|full] \
                             [--dry-run]
```

**Modes:**
- `leaf`: compact raw messages into leaf summaries only
- `full`: leaf pass + condensation up the DAG (default)

**Output:**
```
Compaction complete
Leaf summaries created: 2
Condensed summaries created: 1
Tokens saved: ~14,200
```

---

## lcm_grep

Search the immutable store.

```bash
bash scripts/lcm_grep.sh PATTERN \
                          [--scope messages|summaries|both] \
                          [--mode regex|fulltext] \
                          [--conversation-id ID] \
                          [--all-conversations] \
                          [--since ISO_DATE] \
                          [--before ISO_DATE] \
                          [--limit N]
```

**Output:**
```
Found 3 matches:

[msg_abc / 2026-02-17 09:12:03 / user]
"...the database migration threshold was set to 25000..."

[sum_def / depth=0 / 2026-02-17 10:00:00–11:30:00]
"...configuration: LCM_LEAF_CHUNK_TOKENS=25000..."
```

Results are paginated (default limit 50).
Grouped by the summary node that currently covers each match.

---

## lcm_describe

Inspect a summary node or large file by ID.

```bash
bash scripts/lcm_describe.sh ID
```

**Output for a summary:**
```
ID:          sum_abc123
Kind:        condensed
Depth:       1
Tokens:      1,847
Descendants: 8 messages
Time range:  2026-02-17 07:37 → 15:43
Parents:     sum_def456, sum_ghi789

Content:
[full summary text]

Expand for details about: database migration, config tuning, API auth
```

**Output for a file:**
```
ID:          file_xyz789
Path:        /Users/user/project/data.csv
Stored:      ~/.claude-lcm/files/conv_abc/file_xyz789.csv
MIME:        text/csv
Tokens:      ~84,000 (too large for context)

Exploration Summary:
CSV with 12 columns, 15,000 rows. Schema: id (int), name (str),
created_at (datetime), status (enum: active|inactive|pending)...
```

---

## lcm_expand

Expand a summary node back to its source messages.
**Restricted to sub-agents.** Main agent should use `lcm_expand_query` instead.

```bash
bash scripts/lcm_expand.sh SUMMARY_ID [--max-tokens N]
```

**Output:** The full source messages covered by this summary.

---

## lcm_expand_query

Deep recall via focused question. Safe for main agent use.
Internally delegates expansion to a sub-agent to avoid context flooding.

```bash
bash scripts/lcm_expand_query.sh --prompt "What migration strategy was decided?" \
                                  [--query "database migration"] \
                                  [--summary-ids "sum_abc,sum_def"] \
                                  [--max-tokens 2000]
```

**Output:** A compact answer with cited summary IDs.

---

## lcm_checkpoint

Write a session checkpoint file before ending a long session.

```bash
bash scripts/lcm_checkpoint.sh [--output .lcm-checkpoint.md]
```

**Output:** Writes `.lcm-checkpoint.md` to workspace root.

Checkpoint format:
```markdown
# LCM Session Checkpoint
Generated: 2026-02-17T16:42:00

## Session Info
- Session ID: sess_abc123
- Conversation ID: conv_def456
- DB: ~/.claude-lcm/lcm.db

## Context State
- Total messages: 47
- Summaries: 3 leaf, 1 condensed
- Active context: ~68k tokens

## Active Work
[description of what was in progress]

## Key Decisions
[bullet list of architectural decisions made]

## Resume Instructions
Run: bash scripts/lcm_resume.sh
```

---

## lcm_resume

Resume a session from a checkpoint.

```bash
bash scripts/lcm_resume.sh [--checkpoint .lcm-checkpoint.md]
```

Reads the checkpoint, validates the DB is accessible, and reconstructs
working state summary for the active context.
