# LCM Summarization Prompts

These prompts are used by `lcm_compact.sh` when generating summary nodes.
Each depth level uses a different strategy to balance detail vs. compression.

---

## Depth 0 — Leaf Summary Prompt

Used when compacting raw messages into the first level of the DAG.
Goal: preserve operational detail, timestamps, decisions, file operations.

```
You are compacting a segment of an AI coding session into a summary node.

Preserve:
- All decisions made (architectural, implementation, configuration)
- File paths read, written, or modified, and what changed
- Tool calls and their outcomes (especially errors and how they were resolved)
- Key values: config settings, version numbers, IDs, thresholds
- Timestamps and sequence of events

Format:
- Write in narrative prose, not bullet points
- Include timestamps where present
- End with: "Expand for details about: <comma-separated topics covered>"

Target length: {{TARGET_TOKENS}} tokens.
Do NOT exceed the source material length.

SOURCE MESSAGES:
{{MESSAGES}}
```

---

## Depth 1 — Condensed Summary Prompt

Used when merging multiple leaf summaries.
Goal: chronological session summary, deduplicated against previous context.

```
You are creating a higher-level summary from a set of session segment summaries.

Previous context (already summarized, do NOT repeat):
{{PREVIOUS_CONTEXT}}

Summaries to merge:
{{CHILD_SUMMARIES}}

Instructions:
- Write a chronological narrative of what happened across these segments
- Deduplicate: do not repeat anything already in previous_context
- Focus on the thread of work: what was attempted, what succeeded, what changed
- Preserve decisions, file paths, and configuration values
- End with: "Expand for details about: <comma-separated topics covered>"

Target length: {{TARGET_TOKENS}} tokens.
```

---

## Depth 2 — Arc-Focused Condensed Prompt

Used for high-level summaries spanning multiple working sessions.
Goal: self-contained, captures goals + outcomes + what carries forward.

```
You are creating an arc-level summary of a coding project or major work segment.

Child summaries:
{{CHILD_SUMMARIES}}

Instructions:
- Focus on: what was the goal, what was achieved, what was NOT achieved
- Capture: major architectural decisions, key files changed, unresolved questions
- This summary must be SELF-CONTAINED — a reader with no prior context should
  understand the work arc
- Omit operational minutiae (exact commands, transient errors already resolved)
- End with: "Expand for details about: <comma-separated major topics>"

Target length: {{TARGET_TOKENS}} tokens.
```

---

## Depth 3+ — Durable Context Prompt

Used for very high-level condensation spanning long time horizons.
Goal: only what a future agent needs to know to continue the work.

```
You are creating a durable context summary — information that must persist
across the lifetime of this project.

Child summaries:
{{CHILD_SUMMARIES}}

Include ONLY:
- Architectural decisions and their rationale
- Non-obvious relationships between components
- Gotchas, constraints, and lessons learned
- Active work items and their current state
- Key file paths and their purpose

Omit:
- Completed, closed tasks
- Resolved errors
- Anything that changes frequently

Target length: {{TARGET_TOKENS}} tokens.
This summary will be present in context for a very long time — keep it dense and high-signal.
```

---

## Exploration Summary Prompts (Large Files)

### Code files
```
Analyze this code file and produce a structural summary:
- File purpose (1-2 sentences)
- Public functions/methods with signatures and one-line descriptions
- Key classes/interfaces
- Notable constants or configuration
- Dependencies imported

File: {{FILE_PATH}}
Content: {{FILE_CONTENT}}

Limit: 200 tokens.
```

### JSON/CSV/SQL files
```
Analyze this structured data file:
- File type and purpose
- Schema: field names, types, and what they represent
- Shape: row/record count if determinable
- Sample values for key fields (2-3 examples)
- Any notable patterns or anomalies

File: {{FILE_PATH}}
Content (truncated): {{FILE_CONTENT}}

Limit: 200 tokens.
```

### Text/Markdown files
```
Summarize this document:
- Main topic (1 sentence)
- Key points (3-5 bullets)
- Any action items, decisions, or requirements mentioned

File: {{FILE_PATH}}
Content: {{FILE_CONTENT}}

Limit: 200 tokens.
```
