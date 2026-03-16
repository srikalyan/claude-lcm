# claude-lcm

> Lossless Context Management for Claude Code — a native skill port of the [LCM paper](https://arxiv.org/abs/2502.xxxxx) (Voltropy, Feb 2026).

Claude Code natively truncates older messages when the context window fills up. `claude-lcm` replaces that with a deterministic, lossless memory architecture: every message is persisted verbatim in SQLite, older messages are compacted into a hierarchical DAG of summaries, and the agent can always retrieve any prior state.

**No OpenClaw required. Works natively in Claude Code as a skill.**

---

## What it does

When a session grows beyond comfortable context size, `claude-lcm`:

1. **Persists every message** verbatim in SQLite — the immutable store
2. **Compacts older messages** into leaf summary nodes using depth-aware LLM prompts
3. **Condenses summaries** into higher-level DAG nodes as they accumulate
4. **Assembles active context** each turn: summaries + recent raw messages (fresh tail)
5. **Provides retrieval tools** (`lcm_grep`, `lcm_describe`, `lcm_expand_query`) so the agent can search and recall details from compacted history
6. **Processes large datasets** via `lcm_llm_map` and `lcm_agentic_map` (operator-level recursion)
7. **Writes checkpoints** for cross-session continuity

Nothing is lost. The agent that never forgets — because it doesn't.

---

## Architecture

Inspired by the [LCM paper](https://arxiv.org/abs/2502.xxxxx) and the [lossless-claw](https://github.com/Martian-Engineering/lossless-claw) OpenClaw plugin.

```
Raw messages → Leaf summaries (d0) → Condensed (d1) → Condensed (d2) → ...
                     ↑                      ↑
              summary_messages        summary_parents
```

**Dual-state memory:**
- **Immutable Store** — SQLite DB, verbatim message history, never modified
- **Active Context** — assembled from summary nodes + protected fresh tail

**Three-level summarization escalation** (guaranteed convergence):
1. Detailed narrative (LLM)
2. Bullet points, half target tokens (LLM)
3. Deterministic truncation to 512 tokens (no LLM, never fails)

See [`.claude/skills/claude-lcm/references/architecture.md`](.claude/skills/claude-lcm/references/architecture.md) for the full schema and algorithms.

---

## Installation

### Via Claude Code Plugin Marketplace (recommended)

```bash
# In Claude Code, add the marketplace
/plugin marketplace add srikalyan/claude-lcm

# Install the plugin
/plugin install claude-lcm@claude-lcm
```

### Manual installation

```bash
# Clone and run the install script
git clone https://github.com/srikalyan/claude-lcm.git
cd claude-lcm
./install.sh
```

### Prerequisites

- Claude Code (with `claude` CLI on PATH)
- `python3` (stdlib only, no pip installs needed)

---

## Usage

### Initialize a session

```bash
python3 scripts/lcm_init.py
source ~/.claude-lcm/session.env
```

### Check context health

```bash
python3 scripts/lcm_status.py
```

### Compact when context is filling up

```bash
python3 scripts/lcm_compact.py          # full pass (leaf + condensation)
python3 scripts/lcm_compact.py --mode leaf  # leaf only
python3 scripts/lcm_compact.py --dry-run   # preview without writing
```

### Search history

```bash
python3 scripts/lcm_grep.py "database migration"
python3 scripts/lcm_grep.py "API threshold" --scope summaries
python3 scripts/lcm_grep.py "config" --mode regex --limit 20
```

### Inspect a summary or file

```bash
python3 scripts/lcm_describe.py sum_abc123
python3 scripts/lcm_describe.py file_xyz789
```

### Answer a focused recall question

```bash
python3 scripts/lcm_expand_query.py \
  --prompt "What was the final decision on the compaction threshold?" \
  --query "compaction threshold"
```

### Process a dataset (LLM-Map)

```bash
python3 scripts/lcm_llm_map.py \
  --input data.jsonl \
  --output results.jsonl \
  --prompt "Extract entities from this text" \
  --schema schema.json \
  --concurrency 16
```

### Process with multi-step reasoning (Agentic-Map)

```bash
python3 scripts/lcm_agentic_map.py \
  --input tasks.jsonl \
  --output results.jsonl \
  --prompt "Analyze this repository" \
  --concurrency 4 --read-only
```

### Session handoff

```bash
# Before ending a long session
python3 scripts/lcm_checkpoint.py

# On next session start
python3 scripts/lcm_resume.py
```

---

## Configuration

Set via environment variables before running scripts (or add to your shell profile):

| Variable | Default | Description |
|----------|---------|-------------|
| `LCM_DB` | `~/.claude-lcm/lcm.db` | SQLite database path |
| `LCM_CONTEXT_THRESHOLD` | `0.75` | Fraction of window triggering compaction |
| `LCM_FRESH_TAIL_COUNT` | `32` | Messages protected from compaction |
| `LCM_LEAF_CHUNK_TOKENS` | `20000` | Max source tokens per leaf chunk |
| `LCM_LEAF_TARGET_TOKENS` | `1200` | Target tokens for leaf summaries |
| `LCM_CONDENSED_TARGET_TOKENS` | `2000` | Target tokens for condensed summaries |
| `LCM_CONDENSED_MIN_FANOUT` | `4` | Min summaries before condensation |
| `LCM_LARGE_FILE_THRESHOLD` | `25000` | Files above this stored externally |
| `LCM_SUMMARY_MODEL` | (inherit parent) | Model for summarization (empty = parent) |
| `LCM_TOKEN_BUDGET` | `200000` | Total context budget estimate |

---

## Project Structure

```
claude-lcm/
├── .claude/
│   └── skills/
│       └── claude-lcm/
│           ├── SKILL.md                   # Skill entrypoint (Claude Code)
│           └── references/
│               ├── architecture.md        # Schema, algorithms, DAG design
│               ├── tools.md               # Tool interface specs
│               └── prompts.md             # Depth-aware summarization prompts
├── scripts/
│   ├── lcm_common.py                     # Shared utilities (DB, config, claude -p)
│   ├── lcm_init.py                       # Initialize SQLite store + session
│   ├── lcm_ingest.py                     # Persist a message to immutable store
│   ├── lcm_status.py                     # Check context health
│   ├── lcm_compact.py                    # Run compaction (leaf + condensation)
│   ├── lcm_grep.py                       # Search messages + summaries
│   ├── lcm_describe.py                   # Inspect a summary or file by ID
│   ├── lcm_expand.py                     # Raw DAG expansion (sub-agent only)
│   ├── lcm_expand_query.py               # Deep recall via focused question
│   ├── lcm_llm_map.py                    # LLM-Map: parallel stateless processing
│   ├── lcm_agentic_map.py                # Agentic-Map: parallel sub-agent sessions
│   ├── lcm_checkpoint.py                 # Write session checkpoint
│   └── lcm_resume.py                     # Resume from checkpoint
├── docs/
│   └── design-notes.md                   # Extended design rationale
└── README.md
```

---

## Comparison

| Feature | Default Claude Code | claude-lcm |
|---------|-------------------|------------|
| Long session memory | Truncated | Lossless, DAG-backed |
| Context on short tasks | Native speed | Zero overhead (below threshold) |
| Recall past decisions | Lost on compaction | `lcm_grep` + `lcm_expand_query` |
| Cross-session continuity | Manual CLAUDE.md | Checkpoint + resume |
| Large file handling | Fills context | External store + Exploration Summary |
| Compaction reliability | Model-dependent | Three-level escalation (guaranteed) |
| Dataset processing | Model writes loops | LLM-Map / Agentic-Map operators |

---

## Credits

- **LCM paper**: Ehrlich & Blackman, Voltropy PBC (Feb 2026)
- **lossless-claw**: Martian Engineering — OpenClaw reference implementation
- **RLM paper**: Zhang, Kraska & Khattab (MIT CSAIL, 2026)

## License

MIT
