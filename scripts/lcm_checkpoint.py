#!/usr/bin/env python3
"""lcm_checkpoint.py — Write a session checkpoint before ending a long session."""

import argparse
from datetime import datetime, timezone

from lcm_common import (
    get_connection,
    get_conversation_id,
    get_db_path,
    get_env_file,
    get_session_id,
    load_session_env,
)


def main():
    load_session_env()

    parser = argparse.ArgumentParser(description="Write a session checkpoint")
    parser.add_argument("--output", default=".lcm-checkpoint.md")
    parser.add_argument("--conversation-id", default=None)
    args = parser.parse_args()

    conv_id = args.conversation_id or get_conversation_id()
    db_path = get_db_path()
    session_id = get_session_id()
    env_file = get_env_file()
    con = get_connection()

    total_msgs = con.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv_id,)
    ).fetchone()[0]

    leaf_sums = con.execute(
        "SELECT COUNT(*) FROM summaries WHERE conversation_id = ? AND kind = 'leaf'",
        (conv_id,),
    ).fetchone()[0]

    cond_sums = con.execute(
        "SELECT COUNT(*) FROM summaries WHERE conversation_id = ? AND kind = 'condensed'",
        (conv_id,),
    ).fetchone()[0]

    est_tokens = con.execute(
        "SELECT COALESCE(SUM(token_count), 0) FROM messages WHERE conversation_id = ?",
        (conv_id,),
    ).fetchone()[0]

    # Get the most recent high-depth summary as work state
    latest_summary = con.execute(
        """
        SELECT content FROM summaries
        WHERE conversation_id = ?
        ORDER BY depth DESC, latest_at DESC
        LIMIT 1
        """,
        (conv_id,),
    ).fetchone()

    summary_text = latest_summary[0] if latest_summary else "(no summaries yet)"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    checkpoint = f"""# LCM Session Checkpoint
Generated: {timestamp}

## Session Info
- Session ID: {session_id}
- Conversation ID: {conv_id}
- DB: {db_path}

## Context State
- Total messages: {total_msgs}
- Summaries: {leaf_sums} leaf, {cond_sums} condensed
- Est. active tokens: ~{est_tokens}

## Current Work State
(From most recent summary node)

{summary_text}

## Resume Instructions

1. Source the env: `source {env_file}`
2. Run: `python3 scripts/lcm_resume.py`
3. Check status: `python3 scripts/lcm_status.py`

To search history: `python3 scripts/lcm_grep.py "your query"`
To drill into a summary: `python3 scripts/lcm_describe.py <sum_id>`
"""

    with open(args.output, "w") as f:
        f.write(checkpoint)

    print(f"Checkpoint written to: {args.output}")
    print(f"Messages: {total_msgs} | Summaries: {leaf_sums} leaf + {cond_sums} condensed")

    con.close()


if __name__ == "__main__":
    main()
