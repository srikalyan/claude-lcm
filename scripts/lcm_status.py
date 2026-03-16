#!/usr/bin/env python3
"""lcm_status.py — Report current LCM context health."""

import argparse

from lcm_common import (
    get_config,
    get_config_float,
    get_config_int,
    get_connection,
    get_conversation_id,
    get_db_path,
    get_session_id,
    load_session_env,
)


def main():
    load_session_env()

    parser = argparse.ArgumentParser(description="Check LCM context health")
    parser.add_argument("--conversation-id", default=None)
    args = parser.parse_args()

    conv_id = args.conversation_id or get_conversation_id()
    db_path = get_db_path()
    threshold_frac = get_config_float("LCM_CONTEXT_THRESHOLD")
    fresh_tail = get_config_int("LCM_FRESH_TAIL_COUNT")
    token_budget = get_config_int("LCM_TOKEN_BUDGET")

    con = get_connection()

    # Total messages
    total_msgs = con.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conv_id,)
    ).fetchone()[0]

    # Summary counts
    leaf_sums = con.execute(
        "SELECT COUNT(*) FROM summaries WHERE conversation_id = ? AND kind = 'leaf'",
        (conv_id,),
    ).fetchone()[0]

    cond_sums = con.execute(
        "SELECT COUNT(*) FROM summaries WHERE conversation_id = ? AND kind = 'condensed'",
        (conv_id,),
    ).fetchone()[0]

    # Active context tokens: fresh tail messages + active summaries in context_items
    # This is the ACTUAL context cost, not total historical message tokens
    fresh_tail_tokens = con.execute(
        """
        SELECT COALESCE(SUM(m.token_count), 0)
        FROM messages m
        JOIN context_items ci ON ci.item_id = m.id AND ci.item_type = 'message'
        WHERE ci.conversation_id = ?
        ORDER BY ci.position DESC
        LIMIT ?
        """,
        (conv_id, fresh_tail),
    ).fetchone()[0]

    # If token counts are zero, estimate from content length
    if fresh_tail_tokens == 0 and total_msgs > 0:
        fresh_tail_tokens = con.execute(
            """
            SELECT COALESCE(SUM(length(m.content) / 4), 0)
            FROM messages m
            JOIN context_items ci ON ci.item_id = m.id AND ci.item_type = 'message'
            WHERE ci.conversation_id = ?
            """,
            (conv_id,),
        ).fetchone()[0]

    summary_tokens = con.execute(
        """
        SELECT COALESCE(SUM(s.token_count), 0)
        FROM summaries s
        JOIN context_items ci ON ci.item_id = s.id AND ci.item_type = 'summary'
        WHERE ci.conversation_id = ?
        """,
        (conv_id,),
    ).fetchone()[0]

    est_total = fresh_tail_tokens + summary_tokens
    threshold = int(token_budget * threshold_frac)
    compactable = max(0, total_msgs - fresh_tail)

    # Determine status
    hard_threshold = int(token_budget * 0.95)
    if est_total < threshold:
        status = "OK — no compaction needed"
    elif est_total < hard_threshold:
        status = "WARNING — approaching threshold, compaction recommended"
    else:
        status = "CRITICAL — compaction required now"

    pct = (est_total * 100 / token_budget) if token_budget > 0 else 0

    print("LCM Status")
    print("──────────────────────────────────────")
    print(f"Session:          {get_session_id()}")
    print(f"Conversation:     {conv_id}")
    print(f"DB:               {db_path}")
    print()
    print(f"Messages:         {total_msgs} total, {fresh_tail} in fresh tail, {compactable} compactable")
    print(f"Summaries:        {leaf_sums} leaf, {cond_sums} condensed")
    print()
    print(f"Est. tokens:      {est_total} / {token_budget} ({pct:.1f}%)")
    print(f"Threshold:        {threshold} ({threshold_frac} × budget)")
    print()
    print(f"Status:           {status}")

    con.close()


if __name__ == "__main__":
    main()
