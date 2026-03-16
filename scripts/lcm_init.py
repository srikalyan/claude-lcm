#!/usr/bin/env python3
"""lcm_init.py — Initialize the LCM store for a Claude Code session."""

import argparse
import os
import sys
from pathlib import Path

from lcm_common import (
    generate_id,
    get_config,
    get_connection,
    get_db_path,
    get_env_file,
)

SCHEMA_SQL = """
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
CREATE INDEX IF NOT EXISTS idx_messages_conv
    ON messages(conversation_id, created_at);

-- Full-text search for messages
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
    USING fts5(content, content=messages, content_rowid=rowid);

-- FTS sync triggers (INSERT + DELETE)
CREATE TRIGGER IF NOT EXISTS messages_fts_insert
    AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_delete
    AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content)
        VALUES ('delete', old.rowid, old.content);
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

-- Full-text search for summaries
CREATE VIRTUAL TABLE IF NOT EXISTS summaries_fts
    USING fts5(content, content=summaries, content_rowid=rowid);

CREATE TRIGGER IF NOT EXISTS summaries_fts_insert
    AFTER INSERT ON summaries BEGIN
    INSERT INTO summaries_fts(rowid, content) VALUES (new.rowid, new.content);
END;

CREATE TRIGGER IF NOT EXISTS summaries_fts_delete
    AFTER DELETE ON summaries BEGIN
    INSERT INTO summaries_fts(summaries_fts, rowid, content)
        VALUES ('delete', old.rowid, old.content);
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
CREATE INDEX IF NOT EXISTS idx_context_items_conv
    ON context_items(conversation_id, position);

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
"""


def main():
    parser = argparse.ArgumentParser(description="Initialize the LCM store")
    parser.add_argument("--db", default=None, help="SQLite database path")
    parser.add_argument("--session-id", default=None, help="Session ID (auto-generated if omitted)")
    args = parser.parse_args()

    db_path = args.db or get_db_path()
    session_id = args.session_id or generate_id("sess")
    files_dir = get_config("LCM_FILES_DIR")

    # Ensure directories exist
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    Path(files_dir).mkdir(parents=True, exist_ok=True)

    # Create schema
    con = get_connection(db_path)
    con.executescript(SCHEMA_SQL)

    # Create conversation
    conv_id = generate_id("conv")
    con.execute(
        "INSERT INTO conversations (id, session_id) VALUES (?, ?)",
        (conv_id, session_id),
    )
    con.commit()
    con.close()

    # Write session env file
    env_file = get_env_file()
    Path(env_file).parent.mkdir(parents=True, exist_ok=True)
    with open(env_file, "w") as f:
        f.write(f'export LCM_DB="{db_path}"\n')
        f.write(f'export LCM_SESSION_ID="{session_id}"\n')
        f.write(f'export LCM_CONVERSATION_ID="{conv_id}"\n')
        f.write(f'export LCM_FILES_DIR="{files_dir}"\n')

    print("LCM initialized")
    print(f"Session ID:      {session_id}")
    print(f"Conversation ID: {conv_id}")
    print(f"DB:              {db_path}")
    print(f"Env file:        {env_file}")
    print()
    print(f"Source env with: source {env_file}")


if __name__ == "__main__":
    main()
