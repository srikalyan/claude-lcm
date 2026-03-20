#!/usr/bin/env python3
"""LCM hook handler — ingests events into the immutable store.

Called by hooks.json for each Claude Code event.
Usage: python3 lcm_hook.py <action>

Actions:
  session-start   — Initialize or resume LCM session
  ingest-user     — Ingest user prompt
  ingest-tool     — Ingest tool use (PostToolUse)
  stop            — Ingest final response, check thresholds, checkpoint
"""

import io
import json
import os
import sys
from pathlib import Path

# Find scripts directory relative to this hook
PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", str(Path(__file__).parent.parent))
SCRIPTS_DIR = os.path.join(PLUGIN_ROOT, "scripts")
sys.path.insert(0, SCRIPTS_DIR)


def ok(message=None, suppress=True):
    """Return success response to Claude Code.

    This MUST be the only thing printed to stdout.
    """
    resp = {"continue": True, "suppressOutput": suppress}
    if message:
        resp["systemMessage"] = message
    print(json.dumps(resp))
    sys.exit(0)


def read_stdin():
    """Read hook input JSON from stdin."""
    try:
        return json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        return {}


def quiet_call(func, argv):
    """Call a script's main() with stdout suppressed so it doesn't pollute hook output."""
    old_stdout = sys.stdout
    old_argv = sys.argv
    try:
        sys.stdout = io.StringIO()
        sys.argv = argv
        func()
    except SystemExit:
        pass
    finally:
        sys.stdout = old_stdout
        sys.argv = old_argv


def ensure_session():
    """Ensure LCM session exists, return True if ready."""
    import lcm_common
    lcm_common.load_session_env()

    db_path = lcm_common.get_db_path()
    if not os.path.isfile(db_path):
        return False

    conv_id = os.environ.get("LCM_CONVERSATION_ID", "")
    return bool(conv_id)


def persist_env_vars():
    """Write LCM env vars to CLAUDE_ENV_FILE so Claude can use them in Bash calls."""
    env_file = os.environ.get("CLAUDE_ENV_FILE", "")
    if not env_file:
        return

    with open(env_file, "a") as f:
        f.write(f'export LCM_SCRIPTS="{SCRIPTS_DIR}"\n')
        f.write(f'export LCM_DB="{os.environ.get("LCM_DB", "")}"\n')
        f.write(f'export LCM_CONVERSATION_ID="{os.environ.get("LCM_CONVERSATION_ID", "")}"\n')
        f.write(f'export LCM_SESSION_ID="{os.environ.get("LCM_SESSION_ID", "")}"\n')


def handle_session_start():
    """Initialize or resume LCM session."""
    import lcm_common
    lcm_common.load_session_env()

    db_path = lcm_common.get_db_path()
    checkpoint = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR", "."), ".lcm-checkpoint.md")

    if os.path.isfile(checkpoint) and os.path.isfile(db_path):
        import lcm_resume
        quiet_call(lcm_resume.main, ["lcm_resume", "--checkpoint", checkpoint])
        lcm_common.load_session_env()
        persist_env_vars()
        ok("LCM session resumed from checkpoint.")
    elif not os.path.isfile(db_path) or not os.environ.get("LCM_CONVERSATION_ID"):
        import lcm_init
        quiet_call(lcm_init.main, ["lcm_init"])
        lcm_common.load_session_env()
        persist_env_vars()
        ok("LCM session initialized.")
    else:
        persist_env_vars()
        ok()


def handle_ingest_user():
    """Ingest user prompt into immutable store."""
    if not ensure_session():
        ok()
        return

    data = read_stdin()
    user_prompt = data.get("user_prompt", "")
    if not user_prompt:
        ok()
        return

    import lcm_ingest
    quiet_call(lcm_ingest.main, ["lcm_ingest", "--role", "user", "--content", user_prompt])
    ok()


def handle_ingest_tool():
    """Ingest tool use + result into immutable store."""
    if not ensure_session():
        ok()
        return

    data = read_stdin()
    tool_name = data.get("tool_name", "unknown")
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", "")

    input_str = json.dumps(tool_input, indent=None)
    if len(input_str) > 2000:
        input_str = input_str[:2000] + "...(truncated)"

    result_str = str(tool_result)
    if len(result_str) > 5000:
        result_str = result_str[:5000] + "...(truncated)"

    content = f"[Tool: {tool_name}]\nInput: {input_str}\nResult: {result_str}"

    import lcm_ingest
    quiet_call(lcm_ingest.main, ["lcm_ingest", "--role", "tool", "--content", content])
    ok()


def handle_stop():
    """On stop: check context health, auto-compact if needed, write checkpoint."""
    if not ensure_session():
        ok()
        return

    import lcm_common
    lcm_common.load_session_env()

    data = read_stdin()
    reason = data.get("reason", "")
    if reason:
        import lcm_ingest
        quiet_call(lcm_ingest.main, ["lcm_ingest", "--role", "assistant", "--content", reason])

    # Check if compaction is needed
    con = lcm_common.get_connection()
    conv_id = lcm_common.get_conversation_id()

    total_tokens = con.execute(
        """
        SELECT COALESCE(SUM(CASE
            WHEN ci.item_type = 'message' THEN m.token_count
            WHEN ci.item_type = 'summary' THEN s.token_count
            ELSE 0
        END), 0)
        FROM context_items ci
        LEFT JOIN messages m ON ci.item_type = 'message' AND ci.item_id = m.id
        LEFT JOIN summaries s ON ci.item_type = 'summary' AND ci.item_id = s.id
        WHERE ci.conversation_id = ?
        """,
        (conv_id,),
    ).fetchone()[0]

    threshold = int(lcm_common.get_config_int("LCM_TOKEN_BUDGET") *
                    lcm_common.get_config_float("LCM_CONTEXT_THRESHOLD"))
    con.close()

    if total_tokens > threshold:
        import lcm_compact
        quiet_call(lcm_compact.main, ["lcm_compact"])

    # Write checkpoint
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    checkpoint_path = os.path.join(project_dir, ".lcm-checkpoint.md")

    import lcm_checkpoint
    quiet_call(lcm_checkpoint.main, ["lcm_checkpoint", "--output", checkpoint_path])

    ok()


def main():
    if len(sys.argv) < 2:
        ok()
        return

    action = sys.argv[1]
    handlers = {
        "session-start": handle_session_start,
        "ingest-user": handle_ingest_user,
        "ingest-tool": handle_ingest_tool,
        "stop": handle_stop,
    }

    handler = handlers.get(action)
    if handler:
        try:
            handler()
        except Exception as e:
            ok(f"LCM hook error ({action}): {e}")
    else:
        ok()


if __name__ == "__main__":
    main()
