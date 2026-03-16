#!/usr/bin/env python3
"""Integration tests validating claude-lcm plugin structure.

Verifies that the plugin is correctly structured for Claude Code
marketplace distribution. Does not require Claude Code CLI.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


class PluginStructureTest:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def assert_true(self, condition, message):
        if condition:
            self.passed += 1
            print(f"  PASS: {message}")
        else:
            self.failed += 1
            print(f"  FAIL: {message}")

    def assert_equal(self, actual, expected, message):
        if actual == expected:
            self.passed += 1
            print(f"  PASS: {message}")
        else:
            self.failed += 1
            print(f"  FAIL: {message} (expected {expected!r}, got {actual!r})")

    def test_plugin_json_exists(self):
        print("\n── Test: plugin.json ──")
        path = ROOT / ".claude-plugin" / "plugin.json"
        self.assert_true(path.is_file(), ".claude-plugin/plugin.json exists")

        with open(path) as f:
            data = json.load(f)

        self.assert_true("name" in data, "plugin.json has 'name' field")
        self.assert_equal(data["name"], "claude-lcm", "plugin name is 'claude-lcm'")
        self.assert_true("description" in data, "plugin.json has 'description' field")
        self.assert_true(len(data["description"]) > 20, "description is meaningful (>20 chars)")
        self.assert_true("source" in data, "plugin.json has 'source' field")
        self.assert_true("homepage" in data, "plugin.json has 'homepage' field")

    def test_skills_directory(self):
        print("\n── Test: skills directory ──")
        skills_dir = ROOT / "skills" / "claude-lcm"
        self.assert_true(skills_dir.is_dir(), "skills/claude-lcm/ directory exists")

        skill_md = skills_dir / "SKILL.md"
        self.assert_true(skill_md.is_file(), "skills/claude-lcm/SKILL.md exists")

        content = skill_md.read_text()
        self.assert_true(content.startswith("---"), "SKILL.md starts with YAML frontmatter")
        self.assert_true("name: claude-lcm" in content, "SKILL.md frontmatter has correct name")
        self.assert_true("description:" in content, "SKILL.md frontmatter has description")

        # Check frontmatter is properly closed
        parts = content.split("---")
        self.assert_true(len(parts) >= 3, "SKILL.md has complete frontmatter (opening + closing ---)")

    def test_skill_references(self):
        print("\n── Test: skill reference files ──")
        refs_dir = ROOT / "skills" / "claude-lcm" / "references"
        self.assert_true(refs_dir.is_dir(), "references/ directory exists")

        for ref_file in ["architecture.md", "tools.md", "prompts.md"]:
            path = refs_dir / ref_file
            self.assert_true(path.is_file(), f"references/{ref_file} exists")
            content = path.read_text()
            self.assert_true(len(content) > 100, f"references/{ref_file} has content (>100 chars)")

    def test_scripts_directory(self):
        print("\n── Test: scripts directory ──")
        scripts_dir = ROOT / "scripts"
        self.assert_true(scripts_dir.is_dir(), "scripts/ directory exists")

        expected_scripts = [
            "lcm_common.py",
            "lcm_init.py",
            "lcm_ingest.py",
            "lcm_status.py",
            "lcm_compact.py",
            "lcm_grep.py",
            "lcm_describe.py",
            "lcm_expand.py",
            "lcm_expand_query.py",
            "lcm_checkpoint.py",
            "lcm_resume.py",
            "lcm_llm_map.py",
            "lcm_agentic_map.py",
        ]

        for script in expected_scripts:
            path = scripts_dir / script
            self.assert_true(path.is_file(), f"scripts/{script} exists")

    def test_scripts_importable(self):
        print("\n── Test: scripts importable ──")
        scripts_dir = ROOT / "scripts"
        sys.path.insert(0, str(scripts_dir))

        importable = [
            "lcm_common",
            "lcm_init",
            "lcm_ingest",
            "lcm_status",
            "lcm_grep",
            "lcm_describe",
            "lcm_expand",
            "lcm_checkpoint",
        ]

        for module_name in importable:
            try:
                __import__(module_name)
                self.assert_true(True, f"{module_name} imports successfully")
            except Exception as e:
                self.assert_true(False, f"{module_name} imports successfully ({e})")

    def test_no_old_sh_scripts(self):
        print("\n── Test: no old .sh scripts ──")
        scripts_dir = ROOT / "scripts"
        sh_files = list(scripts_dir.glob("*.sh"))
        self.assert_equal(len(sh_files), 0, "No .sh scripts in scripts/ directory")

    def test_skill_references_python(self):
        print("\n── Test: SKILL.md references Python scripts ──")
        skill_md = ROOT / "skills" / "claude-lcm" / "SKILL.md"
        content = skill_md.read_text()

        self.assert_true("python3 scripts/" in content, "SKILL.md references python3 scripts")
        self.assert_true("lcm_init.py" in content, "SKILL.md references lcm_init.py")
        self.assert_true("lcm_compact.py" in content, "SKILL.md references lcm_compact.py")
        self.assert_true(".sh" not in content.split("---", 2)[-1], "SKILL.md body has no .sh references")

    def test_tools_md_references_python(self):
        print("\n── Test: tools.md references Python scripts ──")
        tools_md = ROOT / "skills" / "claude-lcm" / "references" / "tools.md"
        content = tools_md.read_text()

        self.assert_true("python3 scripts/" in content, "tools.md references python3 scripts")
        self.assert_true("lcm_llm_map.py" in content, "tools.md documents lcm_llm_map")
        self.assert_true("lcm_agentic_map.py" in content, "tools.md documents lcm_agentic_map")
        self.assert_true(".sh" not in content, "tools.md has no .sh references")

    def test_readme_install_instructions(self):
        print("\n── Test: README install instructions ──")
        readme = ROOT / "README.md"
        content = readme.read_text()

        self.assert_true("claude-marketplace" in content, "README references marketplace")
        self.assert_true("python3 scripts/" in content, "README uses python3 commands")

    def run_all(self):
        print("=" * 60)
        print("Plugin Structure Integration Tests")
        print("=" * 60)

        self.test_plugin_json_exists()
        self.test_skills_directory()
        self.test_skill_references()
        self.test_scripts_directory()
        self.test_scripts_importable()
        self.test_no_old_sh_scripts()
        self.test_skill_references_python()
        self.test_tools_md_references_python()
        self.test_readme_install_instructions()

        print("\n" + "=" * 60)
        print(f"Results: {self.passed} passed, {self.failed} failed")
        print("=" * 60)

        return self.failed == 0


if __name__ == "__main__":
    test = PluginStructureTest()
    success = test.run_all()
    sys.exit(0 if success else 1)
