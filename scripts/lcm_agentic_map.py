#!/usr/bin/env python3
"""lcm_agentic_map.py — Process items via full claude sub-agent sessions.

Implements the Agentic-Map operator from the LCM paper (Section 3.1, Figure 4).
Unlike LLM-Map, each item gets a full sub-agent session with tool access,
suitable for multi-step reasoning tasks.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from lcm_common import get_config, load_session_env


def process_item(item, prompt_template, schema, max_retries, model_args, read_only):
    """Process a single item through a full claude sub-agent session."""
    item_json = json.dumps(item, indent=2)
    prompt = f"{prompt_template}\n\nINPUT:\n{item_json}"

    if schema:
        prompt += (
            f"\n\nOUTPUT FORMAT: Return your final answer as valid JSON "
            f"matching this schema:\n{json.dumps(schema)}"
        )

    for attempt in range(max_retries + 1):
        # Write prompt to temp file (avoids shell escaping issues)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(prompt)
            prompt_file = f.name

        try:
            # Use claude in non-interactive mode with full tool access
            cmd = ["claude", "-p", "--output-format", "json"]
            cmd.extend(model_args)

            if read_only:
                cmd.append("--permission-mode=plan")

            # Read prompt from stdin
            with open(prompt_file) as pf:
                result = subprocess.run(
                    cmd, stdin=pf, capture_output=True, text=True, timeout=300
                )

            if result.returncode != 0:
                if attempt < max_retries:
                    continue
                return {
                    "status": "error",
                    "input": item,
                    "error": result.stderr.strip()[:500],
                }

            output_text = result.stdout.strip()

            # Parse claude's JSON output
            try:
                wrapper = json.loads(output_text)
                raw_text = wrapper.get("result", output_text)
            except json.JSONDecodeError:
                raw_text = output_text

            # Try to extract JSON from the response
            try:
                output = json.loads(raw_text)
            except json.JSONDecodeError:
                # Try to find JSON in the response
                import re
                json_match = re.search(r'\{[^{}]*\}', raw_text, re.DOTALL)
                if json_match:
                    try:
                        output = json.loads(json_match.group())
                    except json.JSONDecodeError:
                        if attempt < max_retries:
                            continue
                        return {
                            "status": "error",
                            "input": item,
                            "error": f"No valid JSON in response: {raw_text[:200]}",
                        }
                else:
                    # Return raw text as the output
                    output = {"text": raw_text}

            return {"status": "ok", "input": item, "output": output}

        except subprocess.TimeoutExpired:
            if attempt < max_retries:
                continue
            return {"status": "error", "input": item, "error": "Timeout (300s)"}
        except FileNotFoundError:
            return {"status": "error", "input": item, "error": "claude CLI not found"}
        finally:
            os.unlink(prompt_file)

    return {"status": "error", "input": item, "error": "Max retries exceeded"}


def main():
    load_session_env()

    parser = argparse.ArgumentParser(
        description="Process JSONL items via claude sub-agent sessions (Agentic-Map)"
    )
    parser.add_argument("--input", required=True, help="Input JSONL file path")
    parser.add_argument("--output", required=True, help="Output JSONL file path")
    parser.add_argument("--prompt", required=True, help="Prompt template for each item")
    parser.add_argument("--schema", default=None, help="JSON schema file for output validation")
    parser.add_argument("--concurrency", type=int, default=4, help="Max parallel agents (default 4, lower than llm_map)")
    parser.add_argument("--max-retries", type=int, default=2, help="Max retries per item")
    parser.add_argument("--read-only", action="store_true", help="Restrict agents to read-only operations")
    args = parser.parse_args()

    schema = None
    if args.schema:
        with open(args.schema) as f:
            schema = json.load(f)

    model_args = []
    model = get_config("LCM_SUMMARY_MODEL")
    if model:
        model_args.extend(["--model", model])

    # Load input items
    items = []
    with open(args.input) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"WARNING: Skipping invalid JSON on line {line_num}: {e}", file=sys.stderr)

    if not items:
        print("No items to process.")
        return

    print(f"Processing {len(items)} items with {args.concurrency} concurrent agents...")
    start_time = time.time()

    results = []
    ok_count = 0
    error_count = 0

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(
                process_item, item, args.prompt, schema,
                args.max_retries, model_args, args.read_only
            ): i
            for i, item in enumerate(items)
        }

        for future in as_completed(futures):
            idx = futures[future]
            result = future.result()
            results.append((idx, result))

            if result["status"] == "ok":
                ok_count += 1
            else:
                error_count += 1
                print(f"  Item {idx}: ERROR - {result.get('error', 'unknown')}", file=sys.stderr)

            processed = ok_count + error_count
            if processed % 5 == 0 or processed == len(items):
                print(f"  Progress: {processed}/{len(items)} ({ok_count} ok, {error_count} errors)")

    results.sort(key=lambda x: x[0])

    with open(args.output, "w") as f:
        for _, result in results:
            f.write(json.dumps(result) + "\n")

    elapsed = time.time() - start_time
    print(f"\nComplete in {elapsed:.1f}s")
    print(f"  OK: {ok_count}, Errors: {error_count}")
    print(f"  Output: {args.output}")
    if elapsed > 0:
        print(f"  Throughput: {len(items) / elapsed:.2f} items/sec")


if __name__ == "__main__":
    main()
