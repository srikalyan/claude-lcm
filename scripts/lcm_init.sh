#!/usr/bin/env bash
# lcm_init.sh — Initialize the LCM store for a Claude Code session
set -euo pipefail

# --- Config ---
LCM_DB="${LCM_DB:-$HOME/.claude-lcm/lcm.db}"
LCM_FILES_DIR="${LCM_FILES_DIR:-$HOME/.claude-lcm/files}"
SESSION_ID="${1:-sess_$(openssl rand -hex 8)}"

mkdir -p "$(dirname "$LCM_DB")" "$LCM_FILES_DIR"

# --- Create schema ---
sqlite3 "$LCM_DB" <<'SQL'
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now')),
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  token_count INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
  USING fts5(content, content=messages, content_rowid=rowid);

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
  INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TABLE IF NOT EXISTS summaries (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('leaf','condensed')),
  depth INTEGER NOT NULL DEFAULT 0,
  content TEXT NOT NULL,
  token_count INTEGER DEFAULT 0,
  earliest_at TEXT,
  latest_at TEXT,
  descendant_count INTEGER DEFAULT 0,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS summaries_fts
  USING fts5(content, content=summaries, content_rowid=rowid);

CREATE TRIGGER IF NOT EXISTS summaries_fts_insert AFTER INSERT ON summaries BEGIN
  INSERT INTO summaries_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TABLE IF NOT EXISTS summary_messages (
  summary_id TEXT NOT NULL,
  message_id TEXT NOT NULL,
  PRIMARY KEY (summary_id, message_id),
  FOREIGN KEY (summary_id) REFERENCES summaries(id),
  FOREIGN KEY (message_id) REFERENCES messages(id)
);

CREATE TABLE IF NOT EXISTS summary_parents (
  parent_id TEXT NOT NULL,
  child_id TEXT NOT NULL,
  PRIMARY KEY (parent_id, child_id),
  FOREIGN KEY (parent_id) REFERENCES summaries(id),
  FOREIGN KEY (child_id) REFERENCES summaries(id)
);

CREATE TABLE IF NOT EXISTS context_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL,
  item_type TEXT NOT NULL CHECK(item_type IN ('message','summary')),
  item_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
CREATE INDEX IF NOT EXISTS idx_context_items_conv ON context_items(conversation_id, position);

CREATE TABLE IF NOT EXISTS large_files (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL,
  original_path TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  mime_type TEXT,
  token_count INTEGER DEFAULT 0,
  exploration_summary TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);
SQL

# --- Create or retrieve conversation ---
CONV_ID="conv_$(openssl rand -hex 8)"
sqlite3 "$LCM_DB" "
  INSERT OR IGNORE INTO conversations (id, session_id)
  VALUES ('$CONV_ID', '$SESSION_ID');
"

# Write env file for other scripts to pick up
LCM_ENV_FILE="${LCM_ENV_FILE:-$HOME/.claude-lcm/session.env}"
cat > "$LCM_ENV_FILE" <<ENV
export LCM_DB="$LCM_DB"
export LCM_SESSION_ID="$SESSION_ID"
export LCM_CONVERSATION_ID="$CONV_ID"
export LCM_FILES_DIR="$LCM_FILES_DIR"
ENV

echo "LCM initialized"
echo "Session ID:      $SESSION_ID"
echo "Conversation ID: $CONV_ID"
echo "DB:              $LCM_DB"
echo "Env file:        $LCM_ENV_FILE"
echo ""
echo "Source env with: source $LCM_ENV_FILE"
