#!/usr/bin/env python3
"""lcm_llm_map.py — Process items in a JSONL file via claude -p with concurrency.

Implements the LLM-Map operator from the LCM paper (Section 3.1, Figure 4).
Each item is dispatched as an independent LLM call. The engine manages iteration,
concurrency, schema validation, and retries.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from lcm_common import get_config, load_session_env


def validate_against_schema(output, schema):
    """Basic JSON schema validation (type checking only, no jsonschema dep)."""
    if not schema:
        return True

    if not isinstance(output, dict):
        return False

    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for field in required:
        if field not in output:
            return False

    type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}

    for key, prop in properties.items():
        if key in output:
            expected_type = type_map.get(prop.get("type", ""), None)
            if expected_type and not isinstance(output[key], expected_type):
                return False

    return True


def process_item(item, prompt_template, schema, max_retries, model_args):
    """Process a single item through claude -p."""
    item_json = json.dumps(item)
    prompt = f"{prompt_template}\n\nINPUT:\n{item_json}"

    if schema:
        prompt += f"\n\nOUTPUT FORMAT: Return valid JSON matching this schema:\n{json.dumps(schema)}"

    for attempt in range(max_retries + 1):
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        cmd.extend(model_args)

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                if attempt < max_retries:
                    continue
                return {"status": "error", "input": item, "error": result.stderr.strip()}

            # Parse the output
            output_text = result.stdout.strip()
            try:
                # claude -p --output-format json wraps in {"result": "..."}
                wrapper = json.loads(output_text)
                raw_text = wrapper.get("result", output_text)
            except json.JSONDecodeError:
                raw_text = output_text

            # Try to parse as JSON
            try:
                output = json.loads(raw_text)
            except json.JSONDecodeError:
                if attempt < max_retries:
                    continue
                return {"status": "error", "input": item, "error": f"Invalid JSON: {raw_text[:200]}"}

            # Validate against schema
            if schema and not validate_against_schema(output, schema):
                if attempt < max_retries:
                    continue
                return {"status": "error", "input": item, "error": "Schema validation failed", "output": output}

            return {"status": "ok", "input": item, "output": output}

        except subprocess.TimeoutExpired:
            if attempt < max_retries:
                continue
            return {"status": "error", "input": item, "error": "Timeout"}
        except FileNotFoundError:
            return {"status": "error", "input": item, "error": "claude CLI not found"}

    return {"status": "error", "input": item, "error": "Max retries exceeded"}


def main():
    load_session_env()

    parser = argparse.ArgumentParser(
        description="Process JSONL items via claude -p (LLM-Map operator)"
    )
    parser.add_argument("--input", required=True, help="Input JSONL file path")
    parser.add_argument("--output", required=True, help="Output JSONL file path")
    parser.add_argument("--prompt", required=True, help="Prompt template for each item")
    parser.add_argument("--schema", default=None, help="JSON schema file for output validation")
    parser.add_argument("--concurrency", type=int, default=16, help="Max parallel workers")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retries per item")
    args = parser.parse_args()

    # Load schema if provided
    schema = None
    if args.schema:
        with open(args.schema) as f:
            schema = json.load(f)

    # Build model args
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

    print(f"Processing {len(items)} items with concurrency={args.concurrency}...")
    start_time = time.time()

    # Process in parallel
    results = []
    ok_count = 0
    error_count = 0

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(process_item, item, args.prompt, schema, args.max_retries, model_args): i
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
            if processed % 10 == 0 or processed == len(items):
                print(f"  Progress: {processed}/{len(items)} ({ok_count} ok, {error_count} errors)")

    # Sort by original index and write output
    results.sort(key=lambda x: x[0])

    with open(args.output, "w") as f:
        for _, result in results:
            f.write(json.dumps(result) + "\n")

    elapsed = time.time() - start_time
    print(f"\nComplete in {elapsed:.1f}s")
    print(f"  OK: {ok_count}, Errors: {error_count}")
    print(f"  Output: {args.output}")
    if elapsed > 0:
        print(f"  Throughput: {len(items) / elapsed:.1f} items/sec")


if __name__ == "__main__":
    main()
