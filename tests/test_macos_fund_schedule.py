"""Mac launchd fund-schedule tests. No live orders. No AI-Knowledge writes."""

from __future__ import annotations

import inspect
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from v2.collect_funds import main as funds_main
from v2.collect_jp import main as jp_main
from v2.collect_us import main as us_main

ROOT = Path(__file__).resolve().parents[1]
MACOS = ROOT / "scripts" / "macos"
RUNNER = MACOS / "run-collect-funds.sh"
INSTALL = MACOS / "install-fund-schedule.sh"
UNINSTALL = MACOS / "uninstall-fund-schedule.sh"
TEMPLATE = MACOS / "com.marume.collect-funds.plist.template"
WORKFLOW = ROOT / ".github" / "workflows" / "collect-market.yml"


class MacosFundScheduleTests(unittest.TestCase):
    def test_runner_executes_only_collect_funds(self):
        text = RUNNER.read_text(encoding="utf-8")
        self.assertIn("python3 -m v2.collect_funds", text)
        self.assertNotIn("collect_jp", text)
        self.assertNotIn("collect_us", text)
        self.assertIn("AI-Knowledge", text)
        self.assertIn("unset AI_KNOWLEDGE_TOKEN", text)
        self.assertNotIn("Holdings.md", text)

    def test_plist_times_and_no_secrets(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("<key>StartCalendarInterval</key>", text)
        self.assertIn("<integer>21</integer>", text)
        self.assertIn("<integer>10</integer>", text)
        self.assertIn("<integer>30</integer>", text)
        self.assertIn("<integer>0</integer>", text)
        self.assertNotIn("RunAtLoad", text)
        self.assertIn("logs/launchd-funds.out", text)
        self.assertNotIn("TOKEN", text)
        self.assertNotIn("OPENAI", text)
        self.assertNotIn("collect_jp", text)
        self.assertNotIn("collect_us", text)

    def test_install_and_uninstall_are_one_command(self):
        self.assertTrue(INSTALL.is_file())
        self.assertTrue(UNINSTALL.is_file())
        install = INSTALL.read_text(encoding="utf-8")
        uninstall = UNINSTALL.read_text(encoding="utf-8")
        self.assertIn("launchctl bootstrap", install)
        self.assertIn("StartCalendarInterval", TEMPLATE.read_text(encoding="utf-8"))
        self.assertIn("bootout", uninstall)
        self.assertNotIn("AI_KNOWLEDGE_TOKEN", install)
        self.assertNotIn("AI_KNOWLEDGE_TOKEN", uninstall)

    def test_install_writes_plist_outside_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp) / "LaunchAgents"
            env = {
                **os.environ,
                "LAUNCH_AGENTS_DIR": str(dest_dir),
                "SKIP_LAUNCHCTL": "1",
                "AI_KNOWLEDGE_PATH": "/Users/marumetakayuki/AI-Knowledge",
            }
            subprocess.run(["bash", str(INSTALL)], check=True, env=env, capture_output=True, text=True)
            plist = dest_dir / "com.marume.collect-funds.plist"
            body = plist.read_text(encoding="utf-8")
            self.assertIn(str(ROOT), body)
            self.assertIn("python3 -m v2.collect_funds", RUNNER.read_text(encoding="utf-8"))
            self.assertIn("<integer>21</integer>", body)
            self.assertIn("<integer>10</integer>", body)
            self.assertIn("/Users/marumetakayuki/AI-Knowledge", body)
            self.assertNotIn("__REPO_ROOT__", body)
            subprocess.run(["bash", str(UNINSTALL)], check=True, env=env, capture_output=True, text=True)
            self.assertFalse(plist.exists())

    def test_install_refuses_knowledge_destination(self):
        env = {
            **os.environ,
            "LAUNCH_AGENTS_DIR": "/Users/marumetakayuki/AI-Knowledge/LaunchAgents",
            "SKIP_LAUNCHCTL": "1",
        }
        completed = subprocess.run(["bash", str(INSTALL)], env=env, capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("AI-Knowledge", completed.stderr)

    def test_equity_collectors_unchanged_by_schedule(self):
        for func in (jp_main, us_main, funds_main):
            source = inspect.getsource(func)
            self.assertNotIn("launchd", source)
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python -m v2.collect_jp", workflow)
        self.assertIn("python -m v2.collect_us", workflow)
        self.assertIn("python -m v2.collect_funds", workflow)

    def test_logs_stay_gitignored(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("logs/", gitignore)
        self.assertTrue(RUNNER.stat().st_mode & stat.S_IXUSR)


if __name__ == "__main__":
    unittest.main()
