#!/usr/bin/env python3
"""lcm_grep.py — Search the LCM immutable store (messages + summaries)."""

import argparse
import re

from lcm_common import get_connection, get_conversation_id, load_session_env


def search_messages_fts(con, pattern, conv_id, since, before, limit):
    """Full-text search over messages using FTS5."""
    params = [pattern]
    filters = ""
    if conv_id:
        filters += " AND m.conversation_id = ?"
        params.append(conv_id)
    if since:
        filters += " AND m.created_at >= ?"
        params.append(since)
    if before:
        filters += " AND m.created_at <= ?"
        params.append(before)
    params.append(limit)

    return con.execute(
        f"""
        SELECT m.id, m.role, m.created_at, substr(m.content, 1, 300)
        FROM messages m
        JOIN messages_fts f ON f.rowid = m.rowid
        WHERE messages_fts MATCH ?
            {filters}
        ORDER BY m.created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()


def search_messages_regex(con, pattern, conv_id, since, before, limit):
    """Regex search over messages using Python re module."""
    params = []
    filters = "WHERE 1=1"
    if conv_id:
        filters += " AND conversation_id = ?"
        params.append(conv_id)
    if since:
        filters += " AND created_at >= ?"
        params.append(since)
    if before:
        filters += " AND created_at <= ?"
        params.append(before)

    rows = con.execute(
        f"""
        SELECT id, role, created_at, content
        FROM messages
        {filters}
        ORDER BY created_at DESC
        """,
        params,
    ).fetchall()

    compiled = re.compile(pattern, re.IGNORECASE)
    results = []
    for row in rows:
        if compiled.search(row[3]):
            results.append((row[0], row[1], row[2], row[3][:300]))
            if len(results) >= limit:
                break
    return results


def search_summaries_fts(con, pattern, conv_id, limit):
    """Full-text search over summaries using FTS5."""
    params = [pattern]
    filters = ""
    if conv_id:
        filters += " AND s.conversation_id = ?"
        params.append(conv_id)
    params.append(limit)

    return con.execute(
        f"""
        SELECT s.id, s.kind, s.depth, s.earliest_at, s.latest_at,
               substr(s.content, 1, 400)
        FROM summaries s
        JOIN summaries_fts f ON f.rowid = s.rowid
        WHERE summaries_fts MATCH ?
            {filters}
        ORDER BY s.earliest_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()


def search_summaries_regex(con, pattern, conv_id, limit):
    """Regex search over summaries using Python re module."""
    params = []
    filters = "WHERE 1=1"
    if conv_id:
        filters += " AND conversation_id = ?"
        params.append(conv_id)

    rows = con.execute(
        f"""
        SELECT id, kind, depth, earliest_at, latest_at, content
        FROM summaries
        {filters}
        ORDER BY earliest_at DESC
        """,
        params,
    ).fetchall()

    compiled = re.compile(pattern, re.IGNORECASE)
    results = []
    for row in rows:
        if compiled.search(row[5]):
            results.append((row[0], row[1], row[2], row[3], row[4], row[5][:400]))
            if len(results) >= limit:
                break
    return results


def main():
    load_session_env()

    parser = argparse.ArgumentParser(description="Search the LCM store")
    parser.add_argument("pattern", help="Search pattern")
    parser.add_argument("--scope", choices=["messages", "summaries", "both"], default="both")
    parser.add_argument("--mode", choices=["regex", "fulltext"], default="fulltext")
    parser.add_argument("--conversation-id", default=None)
    parser.add_argument("--all-conversations", action="store_true")
    parser.add_argument("--since", default=None, help="ISO date lower bound")
    parser.add_argument("--before", default=None, help="ISO date upper bound")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    conv_id = None
    if not args.all_conversations:
        conv_id = args.conversation_id or get_conversation_id()

    con = get_connection()

    print(f"Searching for: '{args.pattern}' (scope={args.scope}, mode={args.mode})")
    print("────────────────────────────────────────────────────")

    if args.scope in ("messages", "both"):
        if args.mode == "fulltext":
            rows = search_messages_fts(con, args.pattern, conv_id, args.since, args.before, args.limit)
        else:
            rows = search_messages_regex(con, args.pattern, conv_id, args.since, args.before, args.limit)

        for mid, role, ts, snippet in rows:
            print(f"\n[msg: {mid} / {ts} / {role}]")
            print(f"{snippet}...")

    if args.scope in ("summaries", "both"):
        if args.mode == "fulltext":
            rows = search_summaries_fts(con, args.pattern, conv_id, args.limit)
        else:
            rows = search_summaries_regex(con, args.pattern, conv_id, args.limit)

        for sid, kind, depth, earliest, latest, snippet in rows:
            print(f"\n[sum: {sid} / {kind} / depth={depth} / {earliest} → {latest}]")
            print(f"{snippet}...")

    print()
    print("────────────────────────────────────────────────────")
    print(f"Done. Use lcm_describe.py <id> to inspect any result.")
    print(f"Use lcm_expand_query.py --query '{args.pattern}' --prompt '...' to drill deeper.")

    con.close()


if __name__ == "__main__":
    main()
