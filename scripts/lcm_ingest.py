#!/usr/bin/env python3
"""lcm_ingest.py — Persist a message into the LCM immutable store."""

import argparse
import sys

from lcm_common import (
    estimate_tokens,
    generate_id,
    get_connection,
    get_conversation_id,
    load_session_env,
)


def main():
    load_session_env()

    parser = argparse.ArgumentParser(description="Ingest a message into LCM")
    parser.add_argument("--role", required=True, choices=["user", "assistant", "tool"])
    parser.add_argument("--content", required=True)
    parser.add_argument("--tokens", type=int, default=0)
    parser.add_argument("--conversation-id", default=None)
    args = parser.parse_args()

    conv_id = args.conversation_id or get_conversation_id()
    content = args.content
    tokens = args.tokens or estimate_tokens(content)
    msg_id = generate_id("msg")

    con = get_connection()

    con.execute(
        "INSERT INTO messages (id, conversation_id, role, content, token_count) "
        "VALUES (?, ?, ?, ?, ?)",
        (msg_id, conv_id, args.role, content, tokens),
    )

    # Add to context_items at next position
    row = con.execute(
        "SELECT COALESCE(MAX(position), 0) + 1 FROM context_items "
        "WHERE conversation_id = ?",
        (conv_id,),
    ).fetchone()
    next_pos = row[0]

    con.execute(
        "INSERT INTO context_items (conversation_id, item_type, item_id, position) "
        "VALUES (?, 'message', ?, ?)",
        (conv_id, msg_id, next_pos),
    )

    con.commit()
    con.close()

    print(f"message_id: {msg_id}")
    print(f"tokens: {tokens}")


if __name__ == "__main__":
    main()
