#!/usr/bin/env bash
# lcm_checkpoint.sh — Write a session checkpoint before ending a long session
set -euo pipefail

ENV_FILE="${LCM_ENV_FILE:-$HOME/.claude-lcm/session.env}"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

LCM_DB="${LCM_DB:-$HOME/.claude-lcm/lcm.db}"
CONV_ID="${LCM_CONVERSATION_ID:-}"
OUTPUT="${1:-.lcm-checkpoint.md}"

if [ -z "$CONV_ID" ]; then
  echo "ERROR: No active conversation. Run lcm_init.sh first." >&2; exit 1
fi

TOTAL_MSGS=$(sqlite3 "$LCM_DB" "SELECT COUNT(*) FROM messages WHERE conversation_id='$CONV_ID';")
LEAF_SUMS=$(sqlite3 "$LCM_DB" "SELECT COUNT(*) FROM summaries WHERE conversation_id='$CONV_ID' AND kind='leaf';")
COND_SUMS=$(sqlite3 "$LCM_DB" "SELECT COUNT(*) FROM summaries WHERE conversation_id='$CONV_ID' AND kind='condensed';")
EST_TOKENS=$(sqlite3 "$LCM_DB" "SELECT COALESCE(SUM(token_count),0) FROM messages WHERE conversation_id='$CONV_ID';")

# Get the most recent condensed summary as the "state of work"
LATEST_SUMMARY=$(sqlite3 "$LCM_DB" "
  SELECT content FROM summaries
  WHERE conversation_id='$CONV_ID'
  ORDER BY depth DESC, latest_at DESC
  LIMIT 1;
")

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)

cat > "$OUTPUT" <<CHECKPOINT
# LCM Session Checkpoint
Generated: $TIMESTAMP

## Session Info
- Session ID: ${LCM_SESSION_ID:-unknown}
- Conversation ID: $CONV_ID
- DB: $LCM_DB

## Context State
- Total messages: $TOTAL_MSGS
- Summaries: $LEAF_SUMS leaf, $COND_SUMS condensed
- Est. active tokens: ~$EST_TOKENS

## Current Work State
(From most recent summary node)

$LATEST_SUMMARY

## Resume Instructions

1. Source the env: \`source $HOME/.claude-lcm/session.env\`
2. Run: \`bash scripts/lcm_resume.sh\`
3. Check status: \`bash scripts/lcm_status.sh\`

To search history: \`bash scripts/lcm_grep.sh "your query"\`
To drill into a summary: \`bash scripts/lcm_describe.sh <sum_id>\`
CHECKPOINT

echo "Checkpoint written to: $OUTPUT"
echo "Messages: $TOTAL_MSGS | Summaries: $LEAF_SUMS leaf + $COND_SUMS condensed"
