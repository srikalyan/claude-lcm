#!/usr/bin/env bash
# lcm_expand_query.sh — Deep recall: answer a focused question from compacted history
set -euo pipefail

ENV_FILE="${LCM_ENV_FILE:-$HOME/.claude-lcm/session.env}"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

LCM_DB="${LCM_DB:-$HOME/.claude-lcm/lcm.db}"
CONV_ID="${LCM_CONVERSATION_ID:-}"
LCM_SUMMARY_MODEL="${LCM_SUMMARY_MODEL:-claude-haiku-4-5-20251001}"

PROMPT=""
QUERY=""
SUMMARY_IDS=""
MAX_TOKENS=2000

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prompt)       PROMPT="$2"; shift 2 ;;
    --query)        QUERY="$2"; shift 2 ;;
    --summary-ids)  SUMMARY_IDS="$2"; shift 2 ;;
    --max-tokens)   MAX_TOKENS="$2"; shift 2 ;;
    --conversation-id) CONV_ID="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$PROMPT" ]; then
  echo "Usage: lcm_expand_query.sh --prompt 'Your question' [--query 'search terms'] [--summary-ids 'sum_a,sum_b']" >&2
  exit 1
fi

python3 - <<PYEOF
import json, subprocess, sqlite3

db_path = "$LCM_DB"
conv_id = "$CONV_ID"
prompt = "$PROMPT"
query = "$QUERY"
summary_ids_arg = "$SUMMARY_IDS"
max_tokens = int("$MAX_TOKENS")
model = "$LCM_SUMMARY_MODEL"

con = sqlite3.connect(db_path)

# Find relevant summaries
if summary_ids_arg:
    ids = [s.strip() for s in summary_ids_arg.split(',')]
    summaries = con.execute(
        "SELECT id, content, depth, earliest_at, latest_at FROM summaries WHERE id IN ({})".format(
            ','.join(['?']*len(ids))), ids
    ).fetchall()
elif query:
    # FTS search over summaries
    summaries = con.execute("""
        SELECT s.id, s.content, s.depth, s.earliest_at, s.latest_at
        FROM summaries s
        JOIN summaries_fts f ON f.rowid = s.rowid
        WHERE summaries_fts MATCH ? AND s.conversation_id=?
        ORDER BY s.depth DESC, s.latest_at DESC
        LIMIT 5
    """, (query, conv_id)).fetchall()

    if not summaries:
        # Fallback to LIKE search
        summaries = con.execute("""
            SELECT id, content, depth, earliest_at, latest_at
            FROM summaries
            WHERE conversation_id=? AND content LIKE ?
            ORDER BY depth DESC, latest_at DESC
            LIMIT 5
        """, (conv_id, f'%{query}%')).fetchall()
else:
    # Use most recent summaries
    summaries = con.execute("""
        SELECT id, content, depth, earliest_at, latest_at
        FROM summaries WHERE conversation_id=?
        ORDER BY latest_at DESC LIMIT 5
    """, (conv_id,)).fetchall()

if not summaries:
    print("No relevant summaries found for this query.")
    con.close()
    exit(0)

# Build context from summaries + their source messages
context_parts = []
cited_ids = []

for s in summaries:
    sid, content, depth, earliest, latest = s
    cited_ids.append(sid)
    context_parts.append(f"[Summary {sid} / depth={depth} / {earliest}–{latest}]\n{content}")

    # For leaf summaries, also include source messages
    if depth == 0:
        msgs = con.execute("""
            SELECT m.role, m.content, m.created_at
            FROM messages m
            JOIN summary_messages sm ON sm.message_id = m.id
            WHERE sm.summary_id=?
            ORDER BY m.created_at ASC
            LIMIT 20
        """, (sid,)).fetchall()
        if msgs:
            msg_text = "\n".join(f"[{r}/{ts}] {c[:500]}" for r, c, ts in msgs)
            context_parts.append(f"[Source messages for {sid}]\n{msg_text}")

context = "\n\n---\n\n".join(context_parts)

# Ask Claude to answer the focused question from this context
payload = json.dumps({
    "model": model,
    "max_tokens": max_tokens,
    "messages": [{
        "role": "user",
        "content": f"""You are answering a focused question from compacted session history.

CONTEXT FROM HISTORY:
{context}

QUESTION: {prompt}

Answer concisely and directly from the context. If the answer isn't in the context, say so.
Cite summary IDs where relevant."""
    }]
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
    answer = resp['content'][0]['text']
    print(f"Answer (from summaries: {', '.join(cited_ids)}):")
    print("────────────────────────────────────────")
    print(answer)
except Exception as e:
    print(f"Error calling LLM: {e}")
    print(f"Raw response: {result.stdout[:500]}")

con.close()
PYEOF
