#!/usr/bin/env bash
# lcm_resume.sh — Resume an LCM session from a checkpoint file
set -euo pipefail

CHECKPOINT="${1:-.lcm-checkpoint.md}"

if [ ! -f "$CHECKPOINT" ]; then
  echo "ERROR: Checkpoint file not found: $CHECKPOINT" >&2
  echo "Run lcm_checkpoint.sh first to create one." >&2
  exit 1
fi

# Extract session info from checkpoint
CONV_ID=$(grep "Conversation ID:" "$CHECKPOINT" | awk '{print $NF}')
DB_PATH=$(grep "^- DB:" "$CHECKPOINT" | awk '{print $NF}')
SESSION_ID=$(grep "Session ID:" "$CHECKPOINT" | awk '{print $NF}')

if [ -z "$CONV_ID" ] || [ -z "$DB_PATH" ]; then
  echo "ERROR: Could not parse checkpoint file." >&2; exit 1
fi

if [ ! -f "$DB_PATH" ]; then
  echo "ERROR: LCM database not found at: $DB_PATH" >&2; exit 1
fi

# Restore env
ENV_FILE="${LCM_ENV_FILE:-$HOME/.claude-lcm/session.env}"
cat > "$ENV_FILE" <<ENV
export LCM_DB="$DB_PATH"
export LCM_SESSION_ID="$SESSION_ID"
export LCM_CONVERSATION_ID="$CONV_ID"
export LCM_FILES_DIR="$(dirname "$DB_PATH")/files"
ENV

source "$ENV_FILE"

echo "Session resumed:"
echo "  Conversation ID: $CONV_ID"
echo "  DB: $DB_PATH"
echo ""

# Print status
bash "$(dirname "$0")/lcm_status.sh"

echo ""
echo "Checkpoint contents:"
echo "────────────────────────────────────────"
cat "$CHECKPOINT"
