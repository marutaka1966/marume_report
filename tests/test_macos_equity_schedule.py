"""Mac launchd JP/US schedule tests. No live orders. No AI-Knowledge writes."""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from v2.us_session import NY

ROOT = Path(__file__).resolve().parents[1]
MACOS = ROOT / "scripts" / "macos"
JP_RUNNER = MACOS / "run-collect-jp.sh"
US_RUNNER = MACOS / "run-collect-us.sh"
FUND_RUNNER = MACOS / "run-collect-funds.sh"
JP_TEMPLATE = MACOS / "com.marume.collect-jp.plist.template"
US_TEMPLATE = MACOS / "com.marume.collect-us.plist.template"
JP_INSTALL = MACOS / "install-jp-schedule.sh"
US_INSTALL = MACOS / "install-us-schedule.sh"
JP_UNINSTALL = MACOS / "uninstall-jp-schedule.sh"
US_UNINSTALL = MACOS / "uninstall-us-schedule.sh"
EQUITY_INSTALL = MACOS / "install-equity-schedule.sh"
EQUITY_UNINSTALL = MACOS / "uninstall-equity-schedule.sh"
TOKYO = ZoneInfo("Asia/Tokyo")


class MacosEquityScheduleTests(unittest.TestCase):
    def test_runners_stay_on_their_own_market(self):
        jp = JP_RUNNER.read_text(encoding="utf-8")
        us = US_RUNNER.read_text(encoding="utf-8")
        funds = FUND_RUNNER.read_text(encoding="utf-8")
        self.assertIn("python3 -m v2.collect_jp", jp)
        self.assertNotIn("collect_us", jp)
        self.assertNotIn("collect_funds", jp)
        self.assertIn("python3 -m v2.collect_us", us)
        self.assertNotIn("collect_jp", us)
        self.assertNotIn("collect_funds", us)
        self.assertIn("python3 -m v2.collect_funds", funds)
        self.assertIn("unset AI_KNOWLEDGE_TOKEN", jp)
        self.assertIn("unset AI_KNOWLEDGE_TOKEN", us)
        self.assertNotIn("Holdings.md", jp)
        self.assertNotIn("Holdings.md", us)

    def test_jp_agent_is_1610_and_separate_from_us(self):
        jp = JP_TEMPLATE.read_text(encoding="utf-8")
        us = US_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("com.marume.collect-jp", jp)
        self.assertIn("com.marume.collect-us", us)
        self.assertNotEqual(jp, us)
        self.assertIn("<integer>16</integer>", jp)
        self.assertIn("<integer>10</integer>", jp)
        self.assertNotIn("RunAtLoad", jp)
        self.assertNotIn("TOKEN", jp)
        self.assertNotIn("collect_us", jp)
        self.assertNotIn("collect_funds", jp)

    def test_us_agent_is_0700_after_both_dst_closes(self):
        us = US_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("<integer>7</integer>", us)
        self.assertIn("<integer>0</integer>", us)
        self.assertNotIn("RunAtLoad", us)
        self.assertNotIn("TOKEN", us)
        summer_close = datetime(2026, 7, 10, 16, 0, tzinfo=NY).astimezone(TOKYO)
        winter_close = datetime(2026, 1, 9, 16, 0, tzinfo=NY).astimezone(TOKYO)
        seven_am = 7 * 60
        self.assertLess(summer_close.hour * 60 + summer_close.minute, seven_am)
        self.assertLess(winter_close.hour * 60 + winter_close.minute, seven_am)

    def test_install_writes_separate_plists(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest_dir = Path(tmp) / "LaunchAgents"
            env = {
                **os.environ,
                "LAUNCH_AGENTS_DIR": str(dest_dir),
                "SKIP_LAUNCHCTL": "1",
                "AI_KNOWLEDGE_PATH": "/Users/marumetakayuki/AI-Knowledge",
            }
            subprocess.run(["bash", str(EQUITY_INSTALL)], check=True, env=env, capture_output=True, text=True)
            jp_plist = (dest_dir / "com.marume.collect-jp.plist").read_text(encoding="utf-8")
            us_plist = (dest_dir / "com.marume.collect-us.plist").read_text(encoding="utf-8")
            self.assertIn("<integer>16</integer>", jp_plist)
            self.assertIn("<integer>10</integer>", jp_plist)
            self.assertIn("<integer>7</integer>", us_plist)
            self.assertNotIn("__REPO_ROOT__", jp_plist)
            self.assertNotIn("__REPO_ROOT__", us_plist)
            self.assertNotEqual(jp_plist, us_plist)
            subprocess.run(["bash", str(EQUITY_UNINSTALL)], check=True, env=env, capture_output=True, text=True)
            self.assertFalse((dest_dir / "com.marume.collect-jp.plist").exists())
            self.assertFalse((dest_dir / "com.marume.collect-us.plist").exists())

    def test_install_refuses_knowledge_destination(self):
        env = {
            **os.environ,
            "LAUNCH_AGENTS_DIR": "/Users/marumetakayuki/AI-Knowledge/LaunchAgents",
            "SKIP_LAUNCHCTL": "1",
        }
        jp = subprocess.run(["bash", str(JP_INSTALL)], env=env, capture_output=True, text=True)
        us = subprocess.run(["bash", str(US_INSTALL)], env=env, capture_output=True, text=True)
        self.assertNotEqual(jp.returncode, 0)
        self.assertNotEqual(us.returncode, 0)
        self.assertIn("AI-Knowledge", jp.stderr)
        self.assertIn("AI-Knowledge", us.stderr)

    def test_scripts_are_executable_and_logs_gitignored(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("logs/", gitignore)
        for path in (JP_RUNNER, US_RUNNER, JP_INSTALL, US_INSTALL, JP_UNINSTALL, US_UNINSTALL, EQUITY_INSTALL):
            self.assertTrue(path.stat().st_mode & stat.S_IXUSR, msg=path.name)


if __name__ == "__main__":
    unittest.main()
