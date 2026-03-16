#!/usr/bin/env python3
"""lcm_expand_query.py — Deep recall: answer a focused question from compacted history."""

import argparse
import sys

from lcm_common import (
    call_claude,
    get_config_int,
    get_connection,
    get_conversation_id,
    load_session_env,
)


def find_relevant_summaries(con, conv_id, query=None, summary_ids=None):
    """Find summaries relevant to the query."""
    if summary_ids:
        ids = [s.strip() for s in summary_ids.split(",")]
        placeholders = ",".join(["?"] * len(ids))
        return con.execute(
            f"SELECT id, content, depth, earliest_at, latest_at "
            f"FROM summaries WHERE id IN ({placeholders})",
            ids,
        ).fetchall()

    if query:
        # Try FTS first
        rows = con.execute(
            """
            SELECT s.id, s.content, s.depth, s.earliest_at, s.latest_at
            FROM summaries s
            JOIN summaries_fts f ON f.rowid = s.rowid
            WHERE summaries_fts MATCH ? AND s.conversation_id = ?
            ORDER BY s.depth DESC, s.latest_at DESC
            LIMIT 5
            """,
            (query, conv_id),
        ).fetchall()

        if not rows:
            # Fallback to LIKE
            rows = con.execute(
                """
                SELECT id, content, depth, earliest_at, latest_at
                FROM summaries
                WHERE conversation_id = ? AND content LIKE ?
                ORDER BY depth DESC, latest_at DESC
                LIMIT 5
                """,
                (conv_id, f"%{query}%"),
            ).fetchall()
        return rows

    # No query — use most recent summaries
    return con.execute(
        """
        SELECT id, content, depth, earliest_at, latest_at
        FROM summaries WHERE conversation_id = ?
        ORDER BY latest_at DESC LIMIT 5
        """,
        (conv_id,),
    ).fetchall()


def main():
    load_session_env()

    parser = argparse.ArgumentParser(description="Deep recall via focused question")
    parser.add_argument("--prompt", required=True, help="The question to answer")
    parser.add_argument("--query", default=None, help="Search terms for finding relevant summaries")
    parser.add_argument("--summary-ids", default=None, help="Comma-separated summary IDs")
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("--conversation-id", default=None)
    args = parser.parse_args()

    conv_id = args.conversation_id or get_conversation_id()
    con = get_connection()

    summaries = find_relevant_summaries(con, conv_id, args.query, args.summary_ids)

    if not summaries:
        print("No relevant summaries found for this query.")
        con.close()
        return

    # Build context from summaries + source messages for leaf summaries
    context_parts = []
    cited_ids = []

    for sid, content, depth, earliest, latest in summaries:
        cited_ids.append(sid)
        context_parts.append(
            f"[Summary {sid} / depth={depth} / {earliest}–{latest}]\n{content}"
        )

        # For leaf summaries, include source messages
        if depth == 0:
            msgs = con.execute(
                """
                SELECT m.role, m.content, m.created_at
                FROM messages m
                JOIN summary_messages sm ON sm.message_id = m.id
                WHERE sm.summary_id = ?
                ORDER BY m.created_at ASC
                LIMIT 20
                """,
                (sid,),
            ).fetchall()
            if msgs:
                msg_text = "\n".join(
                    f"[{role}/{ts}] {content[:500]}" for role, content, ts in msgs
                )
                context_parts.append(f"[Source messages for {sid}]\n{msg_text}")

    context = "\n\n---\n\n".join(context_parts)

    prompt = (
        f"You are answering a focused question from compacted session history.\n\n"
        f"CONTEXT FROM HISTORY:\n{context}\n\n"
        f"QUESTION: {args.prompt}\n\n"
        f"Answer concisely and directly from the context. If the answer isn't "
        f"in the context, say so. Cite summary IDs where relevant."
    )

    answer = call_claude(prompt, max_tokens=args.max_tokens)

    if answer:
        print(f"Answer (from summaries: {', '.join(cited_ids)}):")
        print("────────────────────────────────────────")
        print(answer)
    else:
        print("Error: failed to get response from Claude.", file=sys.stderr)

    con.close()


if __name__ == "__main__":
    main()
