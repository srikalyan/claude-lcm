#!/usr/bin/env python3
"""lcm_expand.py — Expand a summary node back to its source messages.

RESTRICTED: This tool is intended for sub-agents only. The main agent should
use lcm_expand_query.py instead to avoid context flooding.
"""

import argparse
import sys

from lcm_common import get_connection, load_session_env


def expand_summary(con, summary_id, max_tokens=None):
    """Recursively expand a summary to its source messages."""
    # Check if this summary exists
    row = con.execute(
        "SELECT id, kind, depth, content, earliest_at, latest_at "
        "FROM summaries WHERE id = ?",
        (summary_id,),
    ).fetchone()

    if not row:
        print(f"Summary not found: {summary_id}", file=sys.stderr)
        return

    sid, kind, depth, content, earliest, latest = row

    print(f"Expanding: {sid} (kind={kind}, depth={depth}, {earliest} → {latest})")
    print("════════════════════════════════════════")

    if kind == "leaf":
        # Leaf summary — expand to source messages
        msgs = con.execute(
            """
            SELECT m.id, m.role, m.content, m.created_at
            FROM messages m
            JOIN summary_messages sm ON sm.message_id = m.id
            WHERE sm.summary_id = ?
            ORDER BY m.created_at ASC
            """,
            (summary_id,),
        ).fetchall()

        total_tokens = 0
        for mid, role, msg_content, ts in msgs:
            if max_tokens and total_tokens > max_tokens:
                print(f"\n[truncated at {max_tokens} tokens]")
                break
            print(f"\n[{mid} / {ts} / {role}]")
            print(msg_content)
            total_tokens += len(msg_content) // 4

        print(f"\n────────────────────────────────────────")
        print(f"Expanded {len(msgs)} source messages from {sid}")

    else:
        # Condensed summary — expand to child summaries
        children = con.execute(
            """
            SELECT s.id, s.kind, s.depth, s.content, s.earliest_at, s.latest_at
            FROM summaries s
            JOIN summary_parents sp ON sp.child_id = s.id
            WHERE sp.parent_id = ?
            ORDER BY s.earliest_at ASC
            """,
            (summary_id,),
        ).fetchall()

        if not children:
            # No children found — just print the summary content
            print(f"\n[No child summaries found, showing content directly]")
            print(content)
            return

        for cid, ckind, cdepth, ccontent, cearliest, clatest in children:
            print(f"\n[{cid} / {ckind} / depth={cdepth} / {cearliest} → {clatest}]")
            print(ccontent)

        print(f"\n────────────────────────────────────────")
        print(f"Expanded {len(children)} child summaries from {sid}")
        print("Use lcm_expand.py <child_id> to drill deeper into any child.")


def main():
    load_session_env()

    parser = argparse.ArgumentParser(
        description="Expand a summary to source messages (sub-agent only)"
    )
    parser.add_argument("summary_id", help="Summary ID to expand (sum_*)")
    parser.add_argument(
        "--max-tokens", type=int, default=None,
        help="Max tokens to output (truncates if exceeded)",
    )
    args = parser.parse_args()

    if not args.summary_id.startswith("sum_"):
        print(f"Expected a summary ID (sum_*), got: {args.summary_id}", file=sys.stderr)
        sys.exit(1)

    con = get_connection()
    expand_summary(con, args.summary_id, args.max_tokens)
    con.close()


if __name__ == "__main__":
    main()
