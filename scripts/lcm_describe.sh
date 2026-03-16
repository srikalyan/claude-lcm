#!/usr/bin/env bash
# lcm_describe.sh — Inspect a summary or large file by ID
set -euo pipefail

ENV_FILE="${LCM_ENV_FILE:-$HOME/.claude-lcm/session.env}"
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

LCM_DB="${LCM_DB:-$HOME/.claude-lcm/lcm.db}"
ID="${1:-}"

if [ -z "$ID" ]; then
  echo "Usage: lcm_describe.sh <summary_id|file_id>" >&2; exit 1
fi

# Detect type
if [[ "$ID" == sum_* ]]; then
  sqlite3 "$LCM_DB" "
    SELECT s.id, s.kind, s.depth, s.token_count, s.descendant_count,
           s.earliest_at, s.latest_at, s.content,
           (SELECT GROUP_CONCAT(parent_id, ', ')
            FROM summary_parents WHERE child_id=s.id) as parents,
           (SELECT GROUP_CONCAT(child_id, ', ')
            FROM summary_parents WHERE parent_id=s.id) as children
    FROM summaries s WHERE s.id='$ID';
  " | while IFS='|' read -r id kind depth tokens descs earliest latest content parents children; do
    echo "ID:             $id"
    echo "Kind:           $kind"
    echo "Depth:          $depth"
    echo "Tokens:         $tokens"
    echo "Descendants:    $descs messages"
    echo "Time range:     $earliest → $latest"
    [ -n "$parents" ] && echo "Parents:        $parents"
    [ -n "$children" ] && echo "Children:       $children"
    echo ""
    echo "Content:"
    echo "────────────────────────────────────────"
    echo "$content"
  done

elif [[ "$ID" == file_* ]]; then
  sqlite3 "$LCM_DB" "
    SELECT id, original_path, stored_path, mime_type, token_count, exploration_summary
    FROM large_files WHERE id='$ID';
  " | while IFS='|' read -r id orig stored mime tokens summary; do
    echo "ID:             $id"
    echo "Original path:  $orig"
    echo "Stored at:      $stored"
    echo "MIME type:      $mime"
    echo "Est. tokens:    $tokens (too large for inline context)"
    echo ""
    echo "Exploration Summary:"
    echo "────────────────────────────────────────"
    echo "$summary"
  done

else
  echo "Unknown ID format: $ID (expected sum_* or file_*)" >&2; exit 1
fi
