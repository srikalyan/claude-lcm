#!/usr/bin/env python3
"""lcm_resume.py — Resume an LCM session from a checkpoint file."""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from lcm_common import get_env_file


def parse_checkpoint(path):
    """Extract session info from a checkpoint markdown file."""
    text = Path(path).read_text()

    conv_match = re.search(r"Conversation ID:\s*(\S+)", text)
    db_match = re.search(r"^- DB:\s*(\S+)", text, re.MULTILINE)
    sess_match = re.search(r"Session ID:\s*(\S+)", text)

    if not conv_match or not db_match:
        print("ERROR: Could not parse checkpoint file.", file=sys.stderr)
        sys.exit(1)

    return {
        "conversation_id": conv_match.group(1),
        "db_path": db_match.group(1),
        "session_id": sess_match.group(1) if sess_match else "unknown",
    }


def main():
    parser = argparse.ArgumentParser(description="Resume from a checkpoint")
    parser.add_argument("--checkpoint", default=".lcm-checkpoint.md")
    args = parser.parse_args()

    if not os.path.isfile(args.checkpoint):
        print(f"ERROR: Checkpoint file not found: {args.checkpoint}", file=sys.stderr)
        print("Run lcm_checkpoint.py first to create one.", file=sys.stderr)
        sys.exit(1)

    info = parse_checkpoint(args.checkpoint)

    if not os.path.isfile(info["db_path"]):
        print(f"ERROR: LCM database not found at: {info['db_path']}", file=sys.stderr)
        sys.exit(1)

    # Restore env file
    env_file = get_env_file()
    files_dir = str(Path(info["db_path"]).parent / "files")

    Path(env_file).parent.mkdir(parents=True, exist_ok=True)
    with open(env_file, "w") as f:
        f.write(f'export LCM_DB="{info["db_path"]}"\n')
        f.write(f'export LCM_SESSION_ID="{info["session_id"]}"\n')
        f.write(f'export LCM_CONVERSATION_ID="{info["conversation_id"]}"\n')
        f.write(f'export LCM_FILES_DIR="{files_dir}"\n')

    # Load into current process env
    os.environ["LCM_DB"] = info["db_path"]
    os.environ["LCM_SESSION_ID"] = info["session_id"]
    os.environ["LCM_CONVERSATION_ID"] = info["conversation_id"]
    os.environ["LCM_FILES_DIR"] = files_dir

    print("Session resumed:")
    print(f"  Conversation ID: {info['conversation_id']}")
    print(f"  DB: {info['db_path']}")
    print()

    # Run status
    scripts_dir = Path(__file__).parent
    subprocess.run([sys.executable, str(scripts_dir / "lcm_status.py")])

    print()
    print("Checkpoint contents:")
    print("────────────────────────────────────────")
    print(Path(args.checkpoint).read_text())


if __name__ == "__main__":
    main()
