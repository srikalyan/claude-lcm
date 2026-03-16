---
name: claude-lcm
description: >
  LCM (Lossless Context Management) skill for Claude Code. Implements deterministic,
  lossless memory management for long agentic sessions using a hierarchical DAG of
  summaries backed by SQLite. Use this skill when: sessions are running long and
  context is filling up, you need to recall something from earlier in a session,
  you're starting a multi-day or complex engineering task and want memory to persist,
  the user says "remember this", "don't forget", "summarize so far", "what did we
  decide earlier", or "compact context". Also triggers automatically before context
  rot sets in. Prefer this over ad-hoc summarization — it gives you lossless
  retrieval, DAG-structured history, and zero overhead on short tasks.
---

# Claude LCM — Lossless Context Management

A Claude Code skill that ports the LCM architecture (from the Voltropy paper) natively
into Claude Code using SQLite + bash scripts. No OpenClaw required.

## Core Concepts

LCM maintains two states:

- **Immutable Store** — Every message, tool result, and assistant response, persisted
  verbatim in SQLite. Never modified. Source of truth.
- **Active Context** — What's actually sent to the model each turn: recent raw messages
  + precomputed summary nodes from the DAG.

As sessions grow, older messages are compacted into **Summary Nodes** in a hierarchical
DAG. Originals are always retained. Any summary can be expanded back to source material.

## When You Are Invoked

You are operating as the LCM skill. Your responsibilities:

1. **Initialize** the LCM store if it doesn't exist for this session
2. **Decide** whether compaction is needed (check token thresholds)
3. **Compact** older messages into summary nodes using the three-level escalation protocol
4. **Answer recall queries** using lcm_grep and lcm_expand
5. **Handoff** cleanly between sessions via checkpoint files

Read `references/architecture.md` for the full DAG and compaction design.
Read `references/tools.md` for tool interface specifications.
Read `references/prompts.md` for depth-aware summarization prompts.

## Quick Start

### Initialize for a new session

```bash
bash scripts/lcm_init.sh
```

This creates `~/.claude-lcm/lcm.db` with the full schema and prints the session ID.

### Check context health

```bash
bash scripts/lcm_status.sh
```

Prints: message count, estimated token usage, compaction threshold status, and whether
a compaction pass is recommended.

### Compact context

```bash
bash scripts/lcm_compact.sh
```

Runs a leaf compaction pass over messages outside the fresh tail. If summaries are
accumulating, also runs a condensation pass.

### Search history

```bash
bash scripts/lcm_grep.sh "database migration"
bash scripts/lcm_grep.sh "config threshold" --scope summaries
```

### Expand a summary

```bash
bash scripts/lcm_expand.sh sum_abc123
```

Returns the source messages behind a summary node.

## Compaction Protocol

Always follow the **Three-Level Escalation** when compacting:

| Level | Strategy | Fallback condition |
|-------|----------|-------------------|
| 1 | LLM summarize, preserve details | Output longer than input |
| 2 | LLM summarize, bullet points only, half target tokens | Still longer than input |
| 3 | Deterministic truncation to 512 tokens | Never fails |

Escalate automatically. Never leave a compaction pass in a failed state.

## Fresh Tail Protection

The **last 32 messages** (configurable via `LCM_FRESH_TAIL_COUNT`) are never compacted.
This ensures the model always has enough recent context for continuity.

## Token Thresholds

| Variable | Default | Meaning |
|----------|---------|---------|
| `LCM_CONTEXT_THRESHOLD` | 0.75 | Fraction of window that triggers compaction |
| `LCM_FRESH_TAIL_COUNT` | 32 | Messages protected from compaction |
| `LCM_LEAF_CHUNK_TOKENS` | 20000 | Max source tokens per leaf chunk |
| `LCM_LEAF_TARGET_TOKENS` | 1200 | Target tokens for leaf summaries |
| `LCM_CONDENSED_TARGET_TOKENS` | 2000 | Target tokens for condensed summaries |
| `LCM_LARGE_FILE_THRESHOLD` | 25000 | Files above this stored externally |

## DAG Structure

```
Raw messages → Leaf summaries (depth 0) → Condensed (depth 1) → Condensed (depth 2) → ...
```

Each level uses a different summarization prompt strategy (see `references/prompts.md`):
- **Depth 0**: Narrative with timestamps, file ops, decisions preserved
- **Depth 1**: Chronological session summary, deduplicated
- **Depth 2**: Arc-focused — goals, outcomes, what carries forward
- **Depth 3+**: Durable context only — key decisions, relationships, lessons

## Session Handoff

Before ending a long session, always write a checkpoint:

```bash
bash scripts/lcm_checkpoint.sh
```

This writes `.lcm-checkpoint.md` to the workspace root. On resume:

```bash
bash scripts/lcm_resume.sh
```

Reads the checkpoint and reconstructs working state from the immutable store.

## Large File Handling

Files over `LCM_LARGE_FILE_THRESHOLD` tokens are stored externally and replaced in
context with a compact Exploration Summary. The agent retains awareness of the file
without loading it. Use `lcm_describe` to inspect stored files.

## Sub-agent Scope Guard

When spawning sub-agents for expansion tasks, each must declare:
- `delegated_scope`: what slice of work it's handling
- `kept_work`: what the caller retains

If a sub-agent cannot articulate `kept_work`, it must do the work directly.
This prevents infinite delegation chains.
