# LCM Architecture Reference

## Overview

LCM uses a dual-state memory model:

```
┌─────────────────────────────────────────────────────┐
│                   IMMUTABLE STORE                    │
│  (SQLite: every message verbatim, never modified)    │
│                                                       │
│  messages → message_parts → summaries → context_items│
│                ↑                  ↑                  │
│           summary_messages   summary_parents         │
└─────────────────────────────────────────────────────┘
                        │
                   materialized
                        ↓
┌─────────────────────────────────────────────────────┐
│                   ACTIVE CONTEXT                     │
│  [summary_node] [summary_node] [raw_msg] [raw_msg]  │
│        ↑                              ↑             │
│   (older, compacted)           (fresh tail, raw)    │
└─────────────────────────────────────────────────────┘
```

## Database Schema

### `conversations`
```sql
CREATE TABLE conversations (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### `messages`
```sql
CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  role TEXT NOT NULL,          -- user | assistant | tool
  content TEXT NOT NULL,       -- verbatim content
  token_count INTEGER,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
CREATE INDEX idx_messages_conversation ON messages(conversation_id, created_at);
-- Full-text search
CREATE VIRTUAL TABLE messages_fts USING fts5(content, content=messages, content_rowid=rowid);
```

### `summaries`
```sql
CREATE TABLE summaries (
  id TEXT PRIMARY KEY,          -- e.g. sum_abc123
  conversation_id TEXT NOT NULL,
  kind TEXT NOT NULL,           -- leaf | condensed
  depth INTEGER NOT NULL,       -- 0 = leaf, 1+ = condensed
  content TEXT NOT NULL,
  token_count INTEGER,
  earliest_at DATETIME,
  latest_at DATETIME,
  descendant_count INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
CREATE VIRTUAL TABLE summaries_fts USING fts5(content, content=summaries, content_rowid=rowid);
```

### `summary_messages` (leaf → source messages)
```sql
CREATE TABLE summary_messages (
  summary_id TEXT NOT NULL REFERENCES summaries(id),
  message_id TEXT NOT NULL REFERENCES messages(id),
  PRIMARY KEY (summary_id, message_id)
);
```

### `summary_parents` (condensed → child summaries)
```sql
CREATE TABLE summary_parents (
  parent_id TEXT NOT NULL REFERENCES summaries(id),
  child_id TEXT NOT NULL REFERENCES summaries(id),
  PRIMARY KEY (parent_id, child_id)
);
```

### `context_items` (ordered active context)
```sql
CREATE TABLE context_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL,
  item_type TEXT NOT NULL,      -- message | summary
  item_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
```

### `large_files`
```sql
CREATE TABLE large_files (
  id TEXT PRIMARY KEY,          -- file_abc123
  conversation_id TEXT NOT NULL,
  original_path TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  mime_type TEXT,
  token_count INTEGER,
  exploration_summary TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## Context Assembly Algorithm

```
function assemble_context(conversation_id, token_budget):
  items = get_context_items(conversation_id)  # ordered list
  fresh_tail = last N items where item_type = 'message'

  protected = fresh_tail
  candidates = items - protected  # older items

  result = []
  used_tokens = sum(token_count for item in protected)

  # fill from newest-to-oldest candidate
  for item in reversed(candidates):
    if used_tokens + item.token_count <= token_budget:
      result.prepend(item)
      used_tokens += item.token_count
    else:
      break  # oldest items dropped if over budget

  return result + protected
```

## Compaction Control Loop

```
function maybe_compact(conversation_id, context_tokens, token_budget):
  soft_threshold = token_budget * LCM_CONTEXT_THRESHOLD
  hard_threshold = token_budget * 0.95

  if context_tokens < soft_threshold:
    return  # zero cost, nothing to do

  if context_tokens >= hard_threshold:
    compact_sync(conversation_id)   # blocking
  else:
    compact_async(conversation_id)  # background, non-blocking
```

## Leaf Compaction Pass

1. Get all messages outside the fresh tail, not yet in any summary
2. Chunk them into groups of ~`LCM_LEAF_CHUNK_TOKENS` tokens
3. For each chunk: run three-level summarization escalation
4. Create a `leaf` summary node linking back to source messages
5. Replace raw messages with summary in context_items

## Condensation Pass

1. Find all leaf summaries (depth=0) not yet condensed
2. If count >= `LCM_CONDENSED_MIN_FANOUT` (default 4), group them
3. Summarize the group into a depth=1 condensed node
4. Repeat upward until stable (no new condensed nodes created)

## Three-Level Escalation

```python
def escalated_summarize(messages, target_tokens):
    # Level 1: detailed narrative
    summary = llm_summarize(messages, mode="detailed", target=target_tokens)
    if token_count(summary) < token_count(messages):
        return summary

    # Level 2: bullet points, half target
    summary = llm_summarize(messages, mode="bullets", target=target_tokens // 2)
    if token_count(summary) < token_count(messages):
        return summary

    # Level 3: deterministic truncation (never fails)
    return truncate(messages, max_tokens=512)
```

## Summary XML Format (what the model sees)

```xml
<summary id="sum_abc123" kind="condensed" depth="1"
         descendant_count="8"
         earliest_at="2026-02-17T07:37:00"
         latest_at="2026-02-17T15:43:00">
  <parents>
    <summary_ref id="sum_def456" />
    <summary_ref id="sum_ghi789" />
  </parents>
  <content>
    ...summary text...
  </content>
</summary>
```

## Large File Interception

When a tool result contains a file > `LCM_LARGE_FILE_THRESHOLD` tokens:

1. Store file content to `~/.claude-lcm/files/<conversation_id>/<file_id>.<ext>`
2. Generate an Exploration Summary (type-aware):
   - JSON/CSV: schema + shape + sample rows
   - Code: function signatures, class hierarchy
   - Text: LLM-generated abstract
3. Replace file content in message with: `[FILE:file_id path=... tokens=... summary=...]`
4. Register in `large_files` table

File IDs propagate through DAG — summaries retain file references so the model can
always re-read any file encountered earlier.
