#!/usr/bin/env bash
# lcm_grep.sh — Search the LCM immutable store (messages + summaries)
set -euo pipefail

ENV_FILE="${LCM_ENV_FILE:-$HOME/.claude-lcm/session.env}"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

LCM_DB="${LCM_DB:-$HOME/.claude-lcm/lcm.db}"
CONV_ID="${LCM_CONVERSATION_ID:-}"

PATTERN=""
SCOPE="both"       # messages | summaries | both
MODE="fulltext"    # regex | fulltext
ALL_CONVS=0
SINCE=""
BEFORE=""
LIMIT=50

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope)           SCOPE="$2"; shift 2 ;;
    --mode)            MODE="$2"; shift 2 ;;
    --conversation-id) CONV_ID="$2"; shift 2 ;;
    --all-conversations) ALL_CONVS=1; shift ;;
    --since)           SINCE="$2"; shift 2 ;;
    --before)          BEFORE="$2"; shift 2 ;;
    --limit)           LIMIT="$2"; shift 2 ;;
    *)
      if [ -z "$PATTERN" ]; then PATTERN="$1"; shift
      else echo "Unknown arg: $1" >&2; exit 1; fi ;;
  esac
done

if [ -z "$PATTERN" ]; then
  echo "Usage: lcm_grep.sh PATTERN [--scope messages|summaries|both] [--mode regex|fulltext]" >&2
  exit 1
fi

CONV_FILTER=""
if [ "$ALL_CONVS" -eq 0 ] && [ -n "$CONV_ID" ]; then
  CONV_FILTER="AND conversation_id='$CONV_ID'"
fi

SINCE_FILTER=""
[ -n "$SINCE" ] && SINCE_FILTER="AND created_at >= '$SINCE'"
BEFORE_FILTER=""
[ -n "$BEFORE" ] && BEFORE_FILTER="AND created_at <= '$BEFORE'"

echo "Searching for: '$PATTERN' (scope=$SCOPE, mode=$MODE)"
echo "────────────────────────────────────────────────────"

if [ "$SCOPE" = "messages" ] || [ "$SCOPE" = "both" ]; then
  if [ "$MODE" = "fulltext" ]; then
    sqlite3 "$LCM_DB" "
      SELECT m.id, m.role, m.created_at,
             substr(m.content, 1, 300) as snippet
      FROM messages m
      JOIN messages_fts f ON f.rowid = m.rowid
      WHERE messages_fts MATCH '$PATTERN'
        $CONV_FILTER $SINCE_FILTER $BEFORE_FILTER
      ORDER BY m.created_at DESC
      LIMIT $LIMIT;
    " | while IFS='|' read -r id role ts snippet; do
      echo ""
      echo "[msg: $id / $ts / $role]"
      echo "$snippet..."
    done
  else
    sqlite3 "$LCM_DB" "
      SELECT id, role, created_at, substr(content, 1, 300)
      FROM messages
      WHERE content REGEXP '$PATTERN'
        $CONV_FILTER $SINCE_FILTER $BEFORE_FILTER
      ORDER BY created_at DESC
      LIMIT $LIMIT;
    " | while IFS='|' read -r id role ts snippet; do
      echo ""
      echo "[msg: $id / $ts / $role]"
      echo "$snippet..."
    done
  fi
fi

if [ "$SCOPE" = "summaries" ] || [ "$SCOPE" = "both" ]; then
  if [ "$MODE" = "fulltext" ]; then
    sqlite3 "$LCM_DB" "
      SELECT s.id, s.kind, s.depth, s.earliest_at, s.latest_at,
             substr(s.content, 1, 400) as snippet
      FROM summaries s
      JOIN summaries_fts f ON f.rowid = s.rowid
      WHERE summaries_fts MATCH '$PATTERN'
        $CONV_FILTER
      ORDER BY s.earliest_at DESC
      LIMIT $LIMIT;
    " | while IFS='|' read -r id kind depth earliest latest snippet; do
      echo ""
      echo "[sum: $id / $kind / depth=$depth / $earliest → $latest]"
      echo "$snippet..."
    done
  else
    sqlite3 "$LCM_DB" "
      SELECT id, kind, depth, earliest_at, latest_at, substr(content, 1, 400)
      FROM summaries
      WHERE content LIKE '%$PATTERN%'
        $CONV_FILTER
      ORDER BY earliest_at DESC
      LIMIT $LIMIT;
    " | while IFS='|' read -r id kind depth earliest latest snippet; do
      echo ""
      echo "[sum: $id / $kind / depth=$depth / $earliest → $latest]"
      echo "$snippet..."
    done
  fi
fi

echo ""
echo "────────────────────────────────────────────────────"
echo "Done. Use lcm_describe.sh <id> to inspect any result."
echo "Use lcm_expand_query.sh --query '$PATTERN' --prompt '...' to drill deeper."
