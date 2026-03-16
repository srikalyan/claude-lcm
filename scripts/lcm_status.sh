#!/usr/bin/env bash
# lcm_status.sh — Report current LCM context health
set -euo pipefail

# Load session env
ENV_FILE="${LCM_ENV_FILE:-$HOME/.claude-lcm/session.env}"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

LCM_DB="${LCM_DB:-$HOME/.claude-lcm/lcm.db}"
CONV_ID="${LCM_CONVERSATION_ID:-}"
LCM_CONTEXT_THRESHOLD="${LCM_CONTEXT_THRESHOLD:-0.75}"
LCM_FRESH_TAIL_COUNT="${LCM_FRESH_TAIL_COUNT:-32}"
TOKEN_BUDGET="${LCM_TOKEN_BUDGET:-200000}"

if [ -z "$CONV_ID" ]; then
  echo "ERROR: No active conversation. Run lcm_init.sh first." >&2
  exit 1
fi

if [ ! -f "$LCM_DB" ]; then
  echo "ERROR: LCM database not found at $LCM_DB" >&2
  exit 1
fi

# Query stats
TOTAL_MSGS=$(sqlite3 "$LCM_DB" "SELECT COUNT(*) FROM messages WHERE conversation_id='$CONV_ID';")
LEAF_SUMS=$(sqlite3 "$LCM_DB" "SELECT COUNT(*) FROM summaries WHERE conversation_id='$CONV_ID' AND kind='leaf';")
COND_SUMS=$(sqlite3 "$LCM_DB" "SELECT COUNT(*) FROM summaries WHERE conversation_id='$CONV_ID' AND kind='condensed';")

# Estimate tokens (use stored counts, fallback to rough estimate)
EST_MSG_TOKENS=$(sqlite3 "$LCM_DB" "
  SELECT COALESCE(SUM(token_count), 0) FROM messages
  WHERE conversation_id='$CONV_ID';
")

EST_SUM_TOKENS=$(sqlite3 "$LCM_DB" "
  SELECT COALESCE(SUM(s.token_count), 0)
  FROM summaries s
  JOIN context_items ci ON ci.item_id = s.id
  WHERE ci.conversation_id='$CONV_ID' AND ci.item_type='summary';
")

# If token counts are zero (not tracked), estimate from content length
if [ "$EST_MSG_TOKENS" -eq 0 ] && [ "$TOTAL_MSGS" -gt 0 ]; then
  EST_MSG_TOKENS=$(sqlite3 "$LCM_DB" "
    SELECT COALESCE(SUM(length(content) / 4), 0)
    FROM messages WHERE conversation_id='$CONV_ID';
  ")
fi

EST_TOTAL=$((EST_MSG_TOKENS + EST_SUM_TOKENS))
THRESHOLD=$(echo "$TOKEN_BUDGET * $LCM_CONTEXT_THRESHOLD" | bc | cut -d. -f1)
FRESH_TAIL=$LCM_FRESH_TAIL_COUNT
COMPACTABLE=$((TOTAL_MSGS > FRESH_TAIL ? TOTAL_MSGS - FRESH_TAIL : 0))

# Determine status
if [ "$EST_TOTAL" -lt "$THRESHOLD" ]; then
  STATUS="OK — no compaction needed"
elif [ "$EST_TOTAL" -lt "$((TOKEN_BUDGET * 95 / 100))" ]; then
  STATUS="WARNING — approaching threshold, compaction recommended"
else
  STATUS="CRITICAL — compaction required now"
fi

PCT=$(echo "scale=1; $EST_TOTAL * 100 / $TOKEN_BUDGET" | bc)

cat <<EOF
LCM Status
──────────────────────────────────────
Session:          ${LCM_SESSION_ID:-unknown}
Conversation:     $CONV_ID
DB:               $LCM_DB

Messages:         $TOTAL_MSGS total, $FRESH_TAIL in fresh tail, $COMPACTABLE compactable
Summaries:        $LEAF_SUMS leaf, $COND_SUMS condensed

Est. tokens:      $EST_TOTAL / $TOKEN_BUDGET ($PCT%)
Threshold:        $THRESHOLD (${LCM_CONTEXT_THRESHOLD} × budget)

Status:           $STATUS
EOF
