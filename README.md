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
6. **Writes checkpoints** for cross-session continuity

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

### As a Claude Code skill (recommended)

```bash
# Copy the skill into your global Claude Code skills directory
cp -r .claude/skills/claude-lcm ~/.claude/skills/

# Make scripts executable
chmod +x scripts/*.sh
```

Claude Code will auto-discover the skill. Invoke it with `/claude-lcm` or describe your need naturally — Claude will load the skill when context management is relevant.

### Alternatively: project-scoped

```bash
# For a specific project only
cp -r .claude/skills/claude-lcm /your/project/.claude/skills/
```

### Prerequisites

- Claude Code
- `sqlite3` CLI (`brew install sqlite3` on macOS)
- `python3` (stdlib only, no pip installs needed)
- `curl` (for LLM API calls in compaction scripts)
- `openssl` (for ID generation)

---

## Usage

### Initialize a session

```bash
bash scripts/lcm_init.sh
source ~/.claude-lcm/session.env
```

### Check context health

```bash
bash scripts/lcm_status.sh
```

### Compact when context is filling up

```bash
bash scripts/lcm_compact.sh          # full pass (leaf + condensation)
bash scripts/lcm_compact.sh --mode leaf  # leaf only
bash scripts/lcm_compact.sh --dry-run   # preview without writing
```

### Search history

```bash
bash scripts/lcm_grep.sh "database migration"
bash scripts/lcm_grep.sh "API threshold" --scope summaries
bash scripts/lcm_grep.sh "config" --mode regex --limit 20
```

### Inspect a summary or file

```bash
bash scripts/lcm_describe.sh sum_abc123
bash scripts/lcm_describe.sh file_xyz789
```

### Answer a focused recall question

```bash
bash scripts/lcm_expand_query.sh \
  --prompt "What was the final decision on the compaction threshold?" \
  --query "compaction threshold"
```

### Session handoff

```bash
# Before ending a long session
bash scripts/lcm_checkpoint.sh

# On next session start
bash scripts/lcm_resume.sh
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
| `LCM_SUMMARY_MODEL` | `claude-haiku-4-5-20251001` | Model used for summarization |
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
│   ├── lcm_init.sh                        # Initialize SQLite store + session
│   ├── lcm_ingest.sh                      # Persist a message to immutable store
│   ├── lcm_status.sh                      # Check context health
│   ├── lcm_compact.sh                     # Run compaction (leaf + condensation)
│   ├── lcm_grep.sh                        # Search messages + summaries
│   ├── lcm_describe.sh                    # Inspect a summary or file by ID
│   ├── lcm_expand_query.sh                # Deep recall via focused question
│   ├── lcm_checkpoint.sh                  # Write session checkpoint
│   └── lcm_resume.sh                      # Resume from checkpoint
├── docs/
│   └── design-notes.md                    # Extended design rationale
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

---

## Credits

- **LCM paper**: Ehrlich & Blackman, Voltropy PBC (Feb 2026)
- **lossless-claw**: Martian Engineering — OpenClaw reference implementation
- **RLM paper**: Zhang, Kraska & Khattab (MIT CSAIL, 2026)

## License

MIT
