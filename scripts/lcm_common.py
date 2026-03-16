"""Shared utilities for LCM scripts — DB access, token estimation, ID generation."""

import os
import secrets
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".claude-lcm" / "lcm.db"
DEFAULT_FILES_DIR = Path.home() / ".claude-lcm" / "files"
DEFAULT_ENV_FILE = Path.home() / ".claude-lcm" / "session.env"

# --- Config defaults ---
DEFAULTS = {
    "LCM_DB": str(DEFAULT_DB_PATH),
    "LCM_FILES_DIR": str(DEFAULT_FILES_DIR),
    "LCM_ENV_FILE": str(DEFAULT_ENV_FILE),
    "LCM_CONTEXT_THRESHOLD": "0.75",
    "LCM_FRESH_TAIL_COUNT": "32",
    "LCM_LEAF_CHUNK_TOKENS": "20000",
    "LCM_LEAF_TARGET_TOKENS": "1200",
    "LCM_CONDENSED_TARGET_TOKENS": "2000",
    "LCM_CONDENSED_MIN_FANOUT": "4",
    "LCM_LARGE_FILE_THRESHOLD": "25000",
    "LCM_TOKEN_BUDGET": "200000",
    "LCM_SUMMARY_MODEL": "",  # empty = inherit parent model
}


def get_config(key: str) -> str:
    """Get a config value from env, falling back to DEFAULTS."""
    return os.environ.get(key, DEFAULTS.get(key, ""))


def get_config_int(key: str) -> int:
    return int(get_config(key))


def get_config_float(key: str) -> float:
    return float(get_config(key))


def get_db_path() -> str:
    return get_config("LCM_DB")


def get_env_file() -> str:
    return get_config("LCM_ENV_FILE")


def generate_id(prefix: str) -> str:
    """Generate a unique ID like 'msg_a1b2c3d4e5f6g7h8'."""
    return f"{prefix}_{secrets.token_hex(8)}"


def estimate_tokens(text: str) -> int:
    """Rough token estimate: chars / 4."""
    return len(text) // 4


def load_session_env():
    """Load session.env file into os.environ if it exists."""
    env_file = get_env_file()
    if not os.path.isfile(env_file):
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            if "=" in line:
                key, _, value = line.partition("=")
                # Strip surrounding quotes
                value = value.strip().strip('"').strip("'")
                os.environ[key] = value


def get_connection(db_path: str = None) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and foreign keys enabled."""
    if db_path is None:
        db_path = get_db_path()
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def get_conversation_id() -> str:
    """Get the active conversation ID from env."""
    conv_id = os.environ.get("LCM_CONVERSATION_ID", "")
    if not conv_id:
        raise SystemExit("ERROR: No active conversation. Run lcm_init.py first.")
    return conv_id


def get_session_id() -> str:
    """Get the active session ID from env."""
    return os.environ.get("LCM_SESSION_ID", "unknown")


def call_claude(prompt: str, max_tokens: int = 4096) -> str:
    """Call claude -p for summarization. Uses parent model by default.

    Returns the response text, or None on failure.
    """
    import subprocess

    cmd = ["claude", "-p", prompt, "--max-tokens", str(max_tokens)]

    model = get_config("LCM_SUMMARY_MODEL")
    if model:
        cmd.extend(["--model", model])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
