#!/usr/bin/env python3
"""lcm_describe.py — Inspect a summary or large file by ID."""

import argparse
import sys

from lcm_common import get_connection, load_session_env


def describe_summary(con, summary_id):
    row = con.execute(
        """
        SELECT s.id, s.kind, s.depth, s.token_count, s.descendant_count,
               s.earliest_at, s.latest_at, s.content
        FROM summaries s WHERE s.id = ?
        """,
        (summary_id,),
    ).fetchone()

    if not row:
        print(f"Summary not found: {summary_id}", file=sys.stderr)
        return

    sid, kind, depth, tokens, descs, earliest, latest, content = row

    # Get parent summaries
    parents = con.execute(
        "SELECT parent_id FROM summary_parents WHERE child_id = ?",
        (summary_id,),
    ).fetchall()
    parent_ids = ", ".join(r[0] for r in parents) if parents else None

    # Get child summaries
    children = con.execute(
        "SELECT child_id FROM summary_parents WHERE parent_id = ?",
        (summary_id,),
    ).fetchall()
    child_ids = ", ".join(r[0] for r in children) if children else None

    # Get source message count for leaf summaries
    source_msgs = con.execute(
        "SELECT COUNT(*) FROM summary_messages WHERE summary_id = ?",
        (summary_id,),
    ).fetchone()[0]

    print(f"ID:             {sid}")
    print(f"Kind:           {kind}")
    print(f"Depth:          {depth}")
    print(f"Tokens:         {tokens}")
    print(f"Descendants:    {descs} messages")
    print(f"Time range:     {earliest} → {latest}")
    if parent_ids:
        print(f"Parents:        {parent_ids}")
    if child_ids:
        print(f"Children:       {child_ids}")
    if source_msgs > 0:
        print(f"Source msgs:    {source_msgs}")
    print()
    print("Content:")
    print("────────────────────────────────────────")
    print(content)


def describe_file(con, file_id):
    row = con.execute(
        """
        SELECT id, original_path, stored_path, mime_type, token_count, exploration_summary
        FROM large_files WHERE id = ?
        """,
        (file_id,),
    ).fetchone()

    if not row:
        print(f"File not found: {file_id}", file=sys.stderr)
        return

    fid, orig, stored, mime, tokens, summary = row

    print(f"ID:             {fid}")
    print(f"Original path:  {orig}")
    print(f"Stored at:      {stored}")
    print(f"MIME type:      {mime}")
    print(f"Est. tokens:    {tokens} (too large for inline context)")
    print()
    print("Exploration Summary:")
    print("────────────────────────────────────────")
    print(summary or "(no summary generated)")


def main():
    load_session_env()

    parser = argparse.ArgumentParser(description="Inspect a summary or file by ID")
    parser.add_argument("id", help="Summary ID (sum_*) or file ID (file_*)")
    args = parser.parse_args()

    con = get_connection()

    if args.id.startswith("sum_"):
        describe_summary(con, args.id)
    elif args.id.startswith("file_"):
        describe_file(con, args.id)
    else:
        print(f"Unknown ID format: {args.id} (expected sum_* or file_*)", file=sys.stderr)
        sys.exit(1)

    con.close()


if __name__ == "__main__":
    main()
