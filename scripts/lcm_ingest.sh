#!/usr/bin/env bash
# lcm_ingest.sh — Persist a message into the LCM immutable store
set -euo pipefail

ENV_FILE="${LCM_ENV_FILE:-$HOME/.claude-lcm/session.env}"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

LCM_DB="${LCM_DB:-$HOME/.claude-lcm/lcm.db}"
CONV_ID="${LCM_CONVERSATION_ID:-}"

ROLE=""
CONTENT=""
TOKENS=0

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) ROLE="$2"; shift 2 ;;
    --content) CONTENT="$2"; shift 2 ;;
    --tokens) TOKENS="$2"; shift 2 ;;
    --conversation-id) CONV_ID="$2"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$CONV_ID" ] || [ -z "$ROLE" ] || [ -z "$CONTENT" ]; then
  echo "Usage: lcm_ingest.sh --role ROLE --content CONTENT [--tokens N] [--conversation-id ID]" >&2
  exit 1
fi

# Estimate tokens if not provided
if [ "$TOKENS" -eq 0 ]; then
  TOKENS=$(echo "${#CONTENT} / 4" | bc)
fi

MSG_ID="msg_$(openssl rand -hex 8)"

# Escape content for SQLite
ESCAPED_CONTENT=$(printf '%s' "$CONTENT" | sed "s/'/''/g")

sqlite3 "$LCM_DB" "
  INSERT INTO messages (id, conversation_id, role, content, token_count)
  VALUES ('$MSG_ID', '$CONV_ID', '$ROLE', '$ESCAPED_CONTENT', $TOKENS);

  INSERT INTO context_items (conversation_id, item_type, item_id, position)
  SELECT '$CONV_ID', 'message', '$MSG_ID',
    COALESCE(MAX(position), 0) + 1
  FROM context_items WHERE conversation_id='$CONV_ID';
"

echo "message_id: $MSG_ID"
echo "tokens: $TOKENS"
