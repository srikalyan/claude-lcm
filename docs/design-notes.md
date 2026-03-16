# Design Notes

## Why a skill, not a plugin?

Claude Code skills are the right abstraction here for several reasons:

1. **No daemon required** — lossless-claw runs as an OpenClaw plugin with a persistent process.
   A skill runs scripts on-demand. For most coding sessions, on-demand is sufficient.
2. **Zero setup friction** — drop in `~/.claude/skills/`, done. No npm install, no plugin manifest.
3. **Inspectable** — all state is in a SQLite file you can inspect with any SQLite browser.
4. **Portable** — the same scripts work from any shell, not just inside the agent.

The tradeoff: we don't get proactive interception of every message (lossless-claw hooks into
the OpenClaw context pipeline). Instead, the agent must invoke compaction explicitly. In practice
this is fine — Claude Code can be instructed to compact proactively as part of the skill's
trigger conditions.

## SQLite as the immutable store

The paper uses PostgreSQL for production deployments. SQLite is the right choice for a
skill-based implementation:

- Embedded, zero-setup
- WAL mode gives sufficient concurrency for single-agent sessions
- FTS5 gives us full-text search over messages and summaries (`lcm_grep`)
- The schema is forward-compatible — new columns added with defaults

If you want PostgreSQL: change the `sqlite3` calls in scripts to `psql` and adjust the
connection strings. The schema translates directly.

## Token counting

We estimate tokens as `len(content) / 4` (chars per token approximation). This is deliberately
rough — the goal is to trigger compaction conservatively, not precisely. If you want exact counts:

- Use the `anthropic` Python SDK's `client.messages.count_tokens()` method
- Or use `tiktoken` for OpenAI-compatible counting

A future version of the scripts could optionally call the count_tokens API before ingesting.

## The fresh tail

Protecting the last 32 messages from compaction is the single most important tuning parameter.
Too small: the model loses recent context and produces incoherent continuations.
Too large: compaction doesn't help much.

32 is the lossless-claw default and works well for coding sessions. Adjust via
`LCM_FRESH_TAIL_COUNT`.

## Depth-aware prompts

The key insight from the paper is that different summary depths need different prompt strategies:

- **Depth 0 (leaf)**: Preserve operational detail. A developer should be able to resume from
  a leaf summary alone for tasks up to a few hours.
- **Depth 1 (condensed)**: Remove duplication across leaves. Chronological narrative.
- **Depth 2**: Arc-level. Self-contained enough that a new agent with no prior context
  could understand the work.
- **Depth 3+**: Durable facts only. These survive indefinitely.

This is why we don't just use one summarization prompt — the compression ratio and
information strategy should change as you go up the hierarchy.

## lcm_expand_query vs lcm_expand

The paper restricts `lcm_expand` (raw DAG expansion) to sub-agents to prevent context flooding.
We implement this distinction:

- `lcm_expand_query.sh` — safe for main agent. Takes a question, finds relevant summaries,
  expands them internally, and returns a compact answer. Bounded output.
- `lcm_expand.sh` — raw expansion. Use sparingly, only when you need the verbatim source.
  The output can be large.

## Multi-session continuity

The checkpoint/resume pattern is intentionally simple — a markdown file that survives
context compaction and is readable by both humans and Claude. The most important invariant:
the checkpoint file must point to the same `lcm.db` database.

If you move or rename the database, update the checkpoint file manually.

## Future work

- **Proactive interception**: A Claude Code MCP server could hook into message flow to
  auto-ingest and auto-compact without explicit skill invocation.
- **Embedding index**: An optional vector index over summary nodes for semantic search,
  complementing the FTS5 grep.
- **`llm_map` equivalent**: A parallel processing primitive for large datasets, as described
  in the LCM paper. Could be implemented as a bash script that spawns parallel `claude -p`
  subprocesses with schema-validated outputs.
- **TUI**: A terminal UI (like lossless-claw's Go TUI) for inspecting the DAG, dissolving
  summaries, and running maintenance operations.
