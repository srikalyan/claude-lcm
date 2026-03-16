#!/usr/bin/env bash
# lcm_compact.sh — Run a compaction pass (leaf + optional condensation)
set -euo pipefail

ENV_FILE="${LCM_ENV_FILE:-$HOME/.claude-lcm/session.env}"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

LCM_DB="${LCM_DB:-$HOME/.claude-lcm/lcm.db}"
CONV_ID="${LCM_CONVERSATION_ID:-}"
MODE="${MODE:-full}"   # leaf | full
DRY_RUN=0

LCM_FRESH_TAIL_COUNT="${LCM_FRESH_TAIL_COUNT:-32}"
LCM_LEAF_CHUNK_TOKENS="${LCM_LEAF_CHUNK_TOKENS:-20000}"
LCM_LEAF_TARGET_TOKENS="${LCM_LEAF_TARGET_TOKENS:-1200}"
LCM_CONDENSED_TARGET_TOKENS="${LCM_CONDENSED_TARGET_TOKENS:-2000}"
LCM_CONDENSED_MIN_FANOUT="${LCM_CONDENSED_MIN_FANOUT:-4}"
LCM_SUMMARY_MODEL="${LCM_SUMMARY_MODEL:-claude-haiku-4-5-20251001}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --conversation-id) CONV_ID="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$CONV_ID" ]; then
  echo "ERROR: No conversation ID. Run lcm_init.sh first." >&2; exit 1
fi

log() { echo "[lcm_compact] $*"; }

# ── Leaf compaction ──────────────────────────────────────────────────────────

# Get messages outside fresh tail, not yet covered by a leaf summary
COMPACTABLE_MSGS=$(sqlite3 "$LCM_DB" "
  SELECT m.id, m.content, m.token_count, m.created_at, m.role
  FROM messages m
  WHERE m.conversation_id = '$CONV_ID'
    AND m.id NOT IN (
      SELECT sm.message_id FROM summary_messages sm
      JOIN summaries s ON s.id = sm.summary_id
      WHERE s.conversation_id = '$CONV_ID'
    )
  ORDER BY m.created_at ASC
  LIMIT (
    SELECT MAX(0, COUNT(*) - $LCM_FRESH_TAIL_COUNT)
    FROM messages WHERE conversation_id='$CONV_ID'
  );
" 2>/dev/null)

if [ -z "$COMPACTABLE_MSGS" ]; then
  log "No messages to compact."
  exit 0
fi

MSG_COUNT=$(sqlite3 "$LCM_DB" "
  SELECT COUNT(*) FROM messages
  WHERE conversation_id='$CONV_ID'
    AND id NOT IN (
      SELECT sm.message_id FROM summary_messages sm
      JOIN summaries s ON s.id = sm.summary_id
      WHERE s.conversation_id='$CONV_ID'
    )
  LIMIT (SELECT MAX(0, COUNT(*) - $LCM_FRESH_TAIL_COUNT) FROM messages WHERE conversation_id='$CONV_ID');
")

log "Found $MSG_COUNT messages eligible for compaction."

if [ "$DRY_RUN" -eq 1 ]; then
  log "[DRY RUN] Would compact $MSG_COUNT messages into leaf summaries."
  exit 0
fi

# Chunk messages and summarize each chunk
# We use a Python helper for the LLM call since bash can't do HTTP easily
CHUNKS_DIR=$(mktemp -d)
trap "rm -rf $CHUNKS_DIR" EXIT

# Export compactable messages to a temp file for Python to process
sqlite3 -separator $'\t' "$LCM_DB" "
  SELECT m.id, m.role, m.content, m.token_count, m.created_at
  FROM messages m
  WHERE m.conversation_id = '$CONV_ID'
    AND m.id NOT IN (
      SELECT sm.message_id FROM summary_messages sm
      JOIN summaries s ON s.id = sm.summary_id
      WHERE s.conversation_id = '$CONV_ID'
    )
  ORDER BY m.created_at ASC
  LIMIT (SELECT MAX(0, COUNT(*) - $LCM_FRESH_TAIL_COUNT) FROM messages WHERE conversation_id='$CONV_ID');
" > "$CHUNKS_DIR/messages.tsv"

LEAF_COUNT=0

# Python script handles chunking + LLM summarization with three-level escalation
python3 - <<PYEOF
import os, sys, json, subprocess, sqlite3, hashlib

db_path = "$LCM_DB"
conv_id = "$CONV_ID"
chunks_dir = "$CHUNKS_DIR"
leaf_chunk_tokens = int("$LCM_LEAF_CHUNK_TOKENS")
leaf_target_tokens = int("$LCM_LEAF_TARGET_TOKENS")
model = "$LCM_SUMMARY_MODEL"

con = sqlite3.connect(db_path)

# Load messages
msgs = []
with open(f"{chunks_dir}/messages.tsv") as f:
    for line in f:
        parts = line.rstrip('\n').split('\t')
        if len(parts) >= 5:
            msgs.append({
                'id': parts[0], 'role': parts[1],
                'content': parts[2],
                'tokens': int(parts[3]) if parts[3].isdigit() else len(parts[2]) // 4,
                'created_at': parts[4]
            })

if not msgs:
    print("No messages to process.")
    sys.exit(0)

# Split into chunks
chunks = []
current_chunk = []
current_tokens = 0
for msg in msgs:
    if current_tokens + msg['tokens'] > leaf_chunk_tokens and current_chunk:
        chunks.append(current_chunk)
        current_chunk = [msg]
        current_tokens = msg['tokens']
    else:
        current_chunk.append(msg)
        current_tokens += msg['tokens']
if current_chunk:
    chunks.append(current_chunk)

print(f"Chunked {len(msgs)} messages into {len(chunks)} leaf chunks.")

def estimate_tokens(text):
    return len(text) // 4

def llm_summarize(content, mode, target_tokens):
    """Call Claude API for summarization."""
    if mode == "detailed":
        instruction = f"""You are compacting a coding session segment. Preserve all decisions, file paths, tool outcomes, config values, and timestamps. Write narrative prose. End with "Expand for details about: <topics>". Target: {target_tokens} tokens."""
    elif mode == "bullets":
        instruction = f"""Compress this session into bullet points only. Key decisions, file changes, outcomes. Target: {target_tokens // 2} tokens max."""
    else:
        return content[:512*4]  # deterministic truncation

    payload = json.dumps({
        "model": model,
        "max_tokens": target_tokens + 200,
        "messages": [
            {"role": "user", "content": f"{instruction}\n\nSOURCE:\n{content}"}
        ]
    })

    result = subprocess.run(
        ["curl", "-s", "-X", "POST", "https://api.anthropic.com/v1/messages",
         "-H", "Content-Type: application/json",
         "-H", f"anthropic-version: 2023-06-01",
         "--data", payload],
        capture_output=True, text=True, timeout=60
    )

    try:
        resp = json.loads(result.stdout)
        return resp['content'][0]['text']
    except Exception:
        return None

def escalated_summarize(messages, target_tokens):
    """Three-level escalation as per LCM paper."""
    source_text = "\n\n".join(
        f"[{m['created_at']} / {m['role']}]\n{m['content']}" for m in messages
    )
    source_tokens = estimate_tokens(source_text)

    for level, mode in enumerate(["detailed", "bullets", "truncate"], 1):
        summary = llm_summarize(source_text, mode, target_tokens)
        if summary and estimate_tokens(summary) < source_tokens:
            print(f"  Summarized at level {level} ({mode}): {estimate_tokens(summary)} tokens")
            return summary
        print(f"  Level {level} ({mode}) failed to reduce, escalating...")

    # Should never reach here (truncate always reduces)
    return source_text[:512*4]

leaf_ids = []
for i, chunk in enumerate(chunks):
    print(f"Processing chunk {i+1}/{len(chunks)} ({len(chunk)} messages)...")
    summary_text = escalated_summarize(chunk, leaf_target_tokens)

    sum_id = f"sum_{hashlib.sha256(f'{conv_id}{i}'.encode()).hexdigest()[:16]}"
    earliest = chunk[0]['created_at']
    latest = chunk[-1]['created_at']
    token_count = estimate_tokens(summary_text)

    con.execute("""
        INSERT OR REPLACE INTO summaries
        (id, conversation_id, kind, depth, content, token_count, earliest_at, latest_at, descendant_count)
        VALUES (?, ?, 'leaf', 0, ?, ?, ?, ?, ?)
    """, (sum_id, conv_id, summary_text, token_count, earliest, latest, len(chunk)))

    for msg in chunk:
        con.execute("""
            INSERT OR IGNORE INTO summary_messages (summary_id, message_id)
            VALUES (?, ?)
        """, (sum_id, msg['id']))

    # Update context_items: replace message items with this summary
    max_pos = con.execute(
        "SELECT MAX(position) FROM context_items WHERE conversation_id=?", (conv_id,)
    ).fetchone()[0] or 0

    con.execute("""
        DELETE FROM context_items
        WHERE conversation_id=? AND item_type='message'
        AND item_id IN ({})
    """.format(','.join(['?']*len(chunk))), [conv_id] + [m['id'] for m in chunk])

    con.execute("""
        INSERT INTO context_items (conversation_id, item_type, item_id, position)
        VALUES (?, 'summary', ?, ?)
    """, (conv_id, sum_id, max_pos + 1))

    leaf_ids.append(sum_id)
    print(f"  Created leaf summary: {sum_id}")

con.commit()
con.close()
print(f"\nLeaf compaction complete. Created {len(leaf_ids)} leaf summaries.")
PYEOF

log "Leaf compaction done."
LEAF_COUNT=$(sqlite3 "$LCM_DB" "SELECT COUNT(*) FROM summaries WHERE conversation_id='$CONV_ID' AND kind='leaf';")

# ── Condensation pass ────────────────────────────────────────────────────────

if [ "$MODE" = "full" ]; then
  log "Running condensation pass..."

  python3 - <<PYEOF2
import os, sys, json, subprocess, sqlite3, hashlib

db_path = "$LCM_DB"
conv_id = "$CONV_ID"
min_fanout = int("$LCM_CONDENSED_MIN_FANOUT")
target_tokens = int("$LCM_CONDENSED_TARGET_TOKENS")
model = "$LCM_SUMMARY_MODEL"

con = sqlite3.connect(db_path)

def estimate_tokens(text):
    return len(text) // 4

def condense_summaries(summaries, depth, target_tokens):
    source = "\n\n".join(
        f"[depth={s['depth']} / {s['earliest_at']}–{s['latest_at']}]\n{s['content']}"
        for s in summaries
    )

    if depth == 1:
        instruction = f"Merge these session summaries chronologically. Deduplicate repeated info. Preserve decisions and key values. Target: {target_tokens} tokens."
    elif depth == 2:
        instruction = f"Create an arc-level summary: goal, what was achieved, what carries forward. Self-contained. Target: {target_tokens} tokens."
    else:
        instruction = f"Durable context only: key decisions, constraints, lessons learned, active work. Omit completed tasks. Target: {target_tokens} tokens."

    payload = json.dumps({
        "model": model,
        "max_tokens": target_tokens + 200,
        "messages": [{"role": "user", "content": f"{instruction}\n\nSOURCE:\n{source}"}]
    })

    result = subprocess.run(
        ["curl", "-s", "-X", "POST", "https://api.anthropic.com/v1/messages",
         "-H", "Content-Type: application/json",
         "-H", "anthropic-version: 2023-06-01",
         "--data", payload],
        capture_output=True, text=True, timeout=60
    )

    try:
        resp = json.loads(result.stdout)
        return resp['content'][0]['text']
    except Exception:
        return source[:target_tokens*4]

depth = 0
condensed_total = 0
while True:
    # Find summaries at this depth not yet condensed
    uncondensed = con.execute("""
        SELECT s.id, s.content, s.depth, s.token_count, s.earliest_at, s.latest_at
        FROM summaries s
        WHERE s.conversation_id=? AND s.depth=?
          AND s.id NOT IN (
            SELECT child_id FROM summary_parents
          )
        ORDER BY s.earliest_at ASC
    """, (conv_id, depth)).fetchall()

    if len(uncondensed) < min_fanout:
        if depth > 0 or len(uncondensed) == 0:
            break  # stable
        depth += 1
        continue

    print(f"Condensing {len(uncondensed)} summaries at depth {depth} → depth {depth+1}...")

    # Group into batches
    batch_size = max(min_fanout, len(uncondensed))
    for i in range(0, len(uncondensed), batch_size):
        batch = uncondensed[i:i+batch_size]
        sums = [{'id': r[0], 'content': r[1], 'depth': r[2],
                 'token_count': r[3], 'earliest_at': r[4], 'latest_at': r[5]}
                for r in batch]

        content = condense_summaries(sums, depth+1, target_tokens)
        new_id = f"sum_{hashlib.sha256(f'{conv_id}d{depth+1}{i}'.encode()).hexdigest()[:16]}"

        con.execute("""
            INSERT OR REPLACE INTO summaries
            (id, conversation_id, kind, depth, content, token_count, earliest_at, latest_at, descendant_count)
            VALUES (?, ?, 'condensed', ?, ?, ?, ?, ?, ?)
        """, (new_id, conv_id, depth+1, content, estimate_tokens(content),
              sums[0]['earliest_at'], sums[-1]['latest_at'], len(batch)))

        for s in sums:
            con.execute("INSERT OR IGNORE INTO summary_parents (parent_id, child_id) VALUES (?,?)",
                        (new_id, s['id']))

            # Replace child summary items in context with parent
            con.execute("""
                DELETE FROM context_items
                WHERE conversation_id=? AND item_type='summary' AND item_id=?
            """, (conv_id, s['id']))

        max_pos = con.execute(
            "SELECT MAX(position) FROM context_items WHERE conversation_id=?", (conv_id,)
        ).fetchone()[0] or 0
        con.execute("""
            INSERT INTO context_items (conversation_id, item_type, item_id, position)
            VALUES (?, 'summary', ?, ?)
        """, (conv_id, new_id, max_pos + 1))

        condensed_total += 1
        print(f"  Created condensed summary: {new_id} (depth={depth+1})")

    depth += 1

con.commit()
con.close()
print(f"\nCondensation complete. Created {condensed_total} condensed summaries.")
PYEOF2
fi

echo ""
echo "Compaction summary:"
sqlite3 "$LCM_DB" "
  SELECT kind, depth, COUNT(*) as count, SUM(token_count) as tokens
  FROM summaries WHERE conversation_id='$CONV_ID'
  GROUP BY kind, depth ORDER BY depth;
" | awk -F'|' '{printf "  %-12s depth=%-2s  count=%-4s  tokens=%s\n", $1, $2, $3, $4}'
