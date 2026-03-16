#!/usr/bin/env python3
"""lcm_compact.py — Run a compaction pass (leaf + optional condensation)."""

import argparse
import hashlib
import sys

from lcm_common import (
    call_claude,
    estimate_tokens,
    get_config_int,
    get_connection,
    get_conversation_id,
    load_session_env,
)


def get_compactable_messages(con, conv_id, fresh_tail_count):
    """Get messages outside fresh tail, not yet covered by a leaf summary."""
    return con.execute(
        """
        SELECT m.id, m.role, m.content, m.token_count, m.created_at
        FROM messages m
        WHERE m.conversation_id = ?
          AND m.id NOT IN (
            SELECT sm.message_id FROM summary_messages sm
            JOIN summaries s ON s.id = sm.summary_id
            WHERE s.conversation_id = ?
          )
        ORDER BY m.created_at ASC
        LIMIT (
            SELECT MAX(0, COUNT(*) - ?)
            FROM messages WHERE conversation_id = ?
        )
        """,
        (conv_id, conv_id, fresh_tail_count, conv_id),
    ).fetchall()


def chunk_messages(messages, chunk_token_limit):
    """Split messages into chunks of approximately chunk_token_limit tokens."""
    chunks = []
    current_chunk = []
    current_tokens = 0

    for msg in messages:
        msg_tokens = msg[3] if msg[3] > 0 else estimate_tokens(msg[2])
        if current_tokens + msg_tokens > chunk_token_limit and current_chunk:
            chunks.append(current_chunk)
            current_chunk = [msg]
            current_tokens = msg_tokens
        else:
            current_chunk.append(msg)
            current_tokens += msg_tokens

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def escalated_summarize(messages, target_tokens):
    """Three-level escalation as per LCM paper (Figure 3)."""
    source_text = "\n\n".join(
        f"[{m[4]} / {m[1]}]\n{m[2]}" for m in messages
    )
    source_token_count = estimate_tokens(source_text)

    # Level 1: detailed narrative
    prompt = (
        f"You are compacting a coding session segment. Preserve all decisions, "
        f"file paths, tool outcomes, config values, and timestamps. Write narrative "
        f'prose. End with "Expand for details about: <topics>". '
        f"Target: {target_tokens} tokens.\n\nSOURCE:\n{source_text}"
    )
    summary = call_claude(prompt, max_tokens=target_tokens + 200)
    if summary and estimate_tokens(summary) < source_token_count:
        print(f"  Summarized at level 1 (detailed): {estimate_tokens(summary)} tokens")
        return summary

    print("  Level 1 (detailed) failed to reduce, escalating...")

    # Level 2: bullet points, half target
    prompt = (
        f"Compress this coding session into bullet points only. Key decisions, "
        f"file changes, outcomes. Target: {target_tokens // 2} tokens max."
        f"\n\nSOURCE:\n{source_text}"
    )
    summary = call_claude(prompt, max_tokens=target_tokens + 200)
    if summary and estimate_tokens(summary) < source_token_count:
        print(f"  Summarized at level 2 (bullets): {estimate_tokens(summary)} tokens")
        return summary

    print("  Level 2 (bullets) failed to reduce, escalating...")

    # Level 3: deterministic truncation (never fails)
    truncated = source_text[: 512 * 4]
    print(f"  Summarized at level 3 (truncation): {estimate_tokens(truncated)} tokens")
    return truncated


def leaf_compact(con, conv_id, dry_run):
    """Compact raw messages into leaf summaries."""
    fresh_tail = get_config_int("LCM_FRESH_TAIL_COUNT")
    chunk_tokens = get_config_int("LCM_LEAF_CHUNK_TOKENS")
    target_tokens = get_config_int("LCM_LEAF_TARGET_TOKENS")

    messages = get_compactable_messages(con, conv_id, fresh_tail)

    if not messages:
        print("[lcm_compact] No messages to compact.")
        return 0

    print(f"[lcm_compact] Found {len(messages)} messages eligible for compaction.")

    if dry_run:
        chunks = chunk_messages(messages, chunk_tokens)
        print(f"[lcm_compact] [DRY RUN] Would create {len(chunks)} leaf summaries.")
        return 0

    chunks = chunk_messages(messages, chunk_tokens)
    print(f"[lcm_compact] Chunked into {len(chunks)} leaf chunks.")

    leaf_count = 0
    for i, chunk in enumerate(chunks):
        print(f"Processing chunk {i + 1}/{len(chunks)} ({len(chunk)} messages)...")
        summary_text = escalated_summarize(chunk, target_tokens)

        sum_id = f"sum_{hashlib.sha256(f'{conv_id}{i}'.encode()).hexdigest()[:16]}"
        earliest = chunk[0][4]
        latest = chunk[-1][4]
        token_count = estimate_tokens(summary_text)

        con.execute(
            """
            INSERT OR REPLACE INTO summaries
            (id, conversation_id, kind, depth, content, token_count,
             earliest_at, latest_at, descendant_count)
            VALUES (?, ?, 'leaf', 0, ?, ?, ?, ?, ?)
            """,
            (sum_id, conv_id, summary_text, token_count, earliest, latest, len(chunk)),
        )

        for msg in chunk:
            con.execute(
                "INSERT OR IGNORE INTO summary_messages (summary_id, message_id) "
                "VALUES (?, ?)",
                (sum_id, msg[0]),
            )

        # Update context_items: remove message items, add summary
        msg_ids = [m[0] for m in chunk]
        placeholders = ",".join(["?"] * len(msg_ids))
        con.execute(
            f"""
            DELETE FROM context_items
            WHERE conversation_id = ? AND item_type = 'message'
              AND item_id IN ({placeholders})
            """,
            [conv_id] + msg_ids,
        )

        max_pos = con.execute(
            "SELECT COALESCE(MAX(position), 0) FROM context_items WHERE conversation_id = ?",
            (conv_id,),
        ).fetchone()[0]

        con.execute(
            "INSERT INTO context_items (conversation_id, item_type, item_id, position) "
            "VALUES (?, 'summary', ?, ?)",
            (conv_id, sum_id, max_pos + 1),
        )

        leaf_count += 1
        print(f"  Created leaf summary: {sum_id}")

    con.commit()
    print(f"\nLeaf compaction complete. Created {leaf_count} leaf summaries.")
    return leaf_count


def condensation_pass(con, conv_id):
    """Condense leaf/lower summaries into higher-level DAG nodes."""
    min_fanout = get_config_int("LCM_CONDENSED_MIN_FANOUT")
    target_tokens = get_config_int("LCM_CONDENSED_TARGET_TOKENS")

    depth = 0
    condensed_total = 0

    while True:
        uncondensed = con.execute(
            """
            SELECT s.id, s.content, s.depth, s.token_count, s.earliest_at, s.latest_at
            FROM summaries s
            WHERE s.conversation_id = ? AND s.depth = ?
              AND s.id NOT IN (SELECT child_id FROM summary_parents)
            ORDER BY s.earliest_at ASC
            """,
            (conv_id, depth),
        ).fetchall()

        if len(uncondensed) < min_fanout:
            if depth > 0 or len(uncondensed) == 0:
                break
            depth += 1
            continue

        print(f"Condensing {len(uncondensed)} summaries at depth {depth} → depth {depth + 1}...")

        # Group into batches of min_fanout (not all at once)
        for i in range(0, len(uncondensed), min_fanout):
            batch = uncondensed[i : i + min_fanout]
            if len(batch) < min_fanout and i > 0:
                break  # don't condense a partial trailing batch

            source = "\n\n".join(
                f"[depth={r[2]} / {r[4]}–{r[5]}]\n{r[1]}" for r in batch
            )

            if depth + 1 == 1:
                instruction = (
                    f"Merge these session summaries chronologically. Deduplicate. "
                    f"Preserve decisions and key values. Target: {target_tokens} tokens."
                )
            elif depth + 1 == 2:
                instruction = (
                    f"Create an arc-level summary: goal, achieved, carries forward. "
                    f"Self-contained. Target: {target_tokens} tokens."
                )
            else:
                instruction = (
                    f"Durable context only: key decisions, constraints, lessons. "
                    f"Omit completed tasks. Target: {target_tokens} tokens."
                )

            content = call_claude(
                f"{instruction}\n\nSOURCE:\n{source}",
                max_tokens=target_tokens + 200,
            )
            if not content:
                content = source[: target_tokens * 4]

            new_id = (
                f"sum_{hashlib.sha256(f'{conv_id}d{depth+1}{i}'.encode()).hexdigest()[:16]}"
            )

            con.execute(
                """
                INSERT OR REPLACE INTO summaries
                (id, conversation_id, kind, depth, content, token_count,
                 earliest_at, latest_at, descendant_count)
                VALUES (?, ?, 'condensed', ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id, conv_id, depth + 1, content,
                    estimate_tokens(content),
                    batch[0][4], batch[-1][5], len(batch),
                ),
            )

            for r in batch:
                con.execute(
                    "INSERT OR IGNORE INTO summary_parents (parent_id, child_id) "
                    "VALUES (?, ?)",
                    (new_id, r[0]),
                )
                con.execute(
                    "DELETE FROM context_items "
                    "WHERE conversation_id = ? AND item_type = 'summary' AND item_id = ?",
                    (conv_id, r[0]),
                )

            max_pos = con.execute(
                "SELECT COALESCE(MAX(position), 0) FROM context_items WHERE conversation_id = ?",
                (conv_id,),
            ).fetchone()[0]

            con.execute(
                "INSERT INTO context_items (conversation_id, item_type, item_id, position) "
                "VALUES (?, 'summary', ?, ?)",
                (conv_id, new_id, max_pos + 1),
            )

            condensed_total += 1
            print(f"  Created condensed summary: {new_id} (depth={depth + 1})")

        depth += 1

    con.commit()
    print(f"\nCondensation complete. Created {condensed_total} condensed summaries.")
    return condensed_total


def main():
    load_session_env()

    parser = argparse.ArgumentParser(description="Run a compaction pass")
    parser.add_argument("--conversation-id", default=None)
    parser.add_argument("--mode", choices=["leaf", "full"], default="full")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conv_id = args.conversation_id or get_conversation_id()
    con = get_connection()

    leaf_count = leaf_compact(con, conv_id, args.dry_run)

    if args.mode == "full" and not args.dry_run and leaf_count > 0:
        print("\n[lcm_compact] Running condensation pass...")
        condensation_pass(con, conv_id)

    # Print summary
    if not args.dry_run:
        print("\nCompaction summary:")
        rows = con.execute(
            """
            SELECT kind, depth, COUNT(*) as count, SUM(token_count) as tokens
            FROM summaries WHERE conversation_id = ?
            GROUP BY kind, depth ORDER BY depth
            """,
            (conv_id,),
        ).fetchall()
        for kind, depth, count, tokens in rows:
            print(f"  {kind:<12} depth={depth:<2}  count={count:<4}  tokens={tokens}")

    con.close()


if __name__ == "__main__":
    main()
