#!/usr/bin/env bash
# install.sh — Install claude-lcm as a Claude Code skill
set -euo pipefail

SKILL_DIR="${HOME}/.claude/skills/claude-lcm"
SCRIPTS_DIR="${HOME}/.claude-lcm/scripts"

echo "Installing claude-lcm..."

# Copy skill files
mkdir -p "$SKILL_DIR/references"
cp .claude/skills/claude-lcm/SKILL.md "$SKILL_DIR/"
cp .claude/skills/claude-lcm/references/*.md "$SKILL_DIR/references/"

# Copy scripts
mkdir -p "$SCRIPTS_DIR"
cp scripts/*.py "$SCRIPTS_DIR/"

echo ""
echo "Installed:"
echo "  Skill:   $SKILL_DIR"
echo "  Scripts: $SCRIPTS_DIR"
echo ""
echo "Claude Code will auto-discover the skill."
echo "To use manually: python3 $SCRIPTS_DIR/lcm_init.py"
