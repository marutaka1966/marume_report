"""Public collection summary tests. No live orders. No AI-Knowledge writes."""

from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v2 import DATA_UNAVAILABLE
from v2.collect_funds import main as funds_main
from v2.collect_jp import main as jp_main
from v2.collect_report import (
    collection_exit_code,
    finish_collection,
    public_summary,
)
from v2.collect_us import main as us_main

WORKFLOW = Path(".github/workflows/collect-market.yml")
DAILY = Path(".github/workflows/daily.yml")


class PublicSummaryTests(unittest.TestCase):
    def test_partial_failure_is_success_without_names(self):
        document = {
            "holdings_error": None,
            "quotes": [
                {"symbol": "148A", "price": 100.0, "error": None},
                {"symbol": "9432", "price": DATA_UNAVAILABLE, "error": DATA_UNAVAILABLE},
            ],
        }
        payload = public_summary("jp", document)
        dumped = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["ok"], 1)
        self.assertEqual(payload["failed"], 1)
        self.assertEqual(payload["reasons"], [{"reason": DATA_UNAVAILABLE, "count": 1}])
        self.assertEqual(collection_exit_code(document), 0)
        self.assertNotIn("148A", dumped)
        self.assertNotIn("9432", dumped)
        self.assertNotIn("100.0", dumped)

    def test_holdings_unreadable_and_all_failed_exit_nonzero(self):
        unread = {"holdings_error": DATA_UNAVAILABLE, "quotes": []}
        all_failed = {
            "holdings_error": None,
            "quotes": [
                {"name": "secret-fund", "status": DATA_UNAVAILABLE, "error": "基準日が一意に確定できない"},
            ],
        }
        unread_payload = public_summary("funds", unread)
        failed_payload = public_summary("funds", all_failed)
        self.assertEqual(collection_exit_code(unread), 1)
        self.assertEqual(collection_exit_code(all_failed), 1)
        self.assertEqual(unread_payload["holdings"], "holdings_unreadable")
        self.assertEqual(failed_payload["ok"], 0)
        self.assertEqual(failed_payload["failed"], 1)
        self.assertNotIn("secret-fund", json.dumps(failed_payload))

    def test_finish_collection_writes_summary_without_quotes(self):
        document = {
            "holdings_error": None,
            "quotes": [
                {"status": "ok", "error": None, "name": "hidden"},
                {"status": DATA_UNAVAILABLE, "error": "HTMLの構造が変わった", "name": "hidden-2"},
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "summary.md"
            with patch.dict(
                "os.environ",
                {"GITHUB_STEP_SUMMARY": str(summary)},
            ):
                code = finish_collection(
                    "funds",
                    document,
                    required_fields=("status", "error"),
                )
            text = summary.read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertIn("ok: 1", text)
        self.assertIn("failed: 1", text)
        self.assertIn("HTMLの構造が変わった (1)", text)
        self.assertNotIn("hidden", text)


class WorkflowFileTests(unittest.TestCase):
    def test_manual_only_and_no_secrets_leak_paths(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        daily = DAILY.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", text)
        self.assertNotIn("schedule:", text)
        self.assertIn("python -m v2.collect_jp", text)
        self.assertIn("python -m v2.collect_us", text)
        self.assertIn("python -m v2.collect_funds", text)
        self.assertIn("secrets.AI_KNOWLEDGE_TOKEN", text)
        self.assertIn("marutaka1966/AI-Knowledge", text)
        self.assertNotIn("upload-artifact", text)
        self.assertNotIn("OPENAI", text)
        self.assertNotIn("GMAIL", text)
        self.assertNotIn("schedule:", text.split("workflow_dispatch")[0])
        self.assertIn("cron:", daily)
        self.assertNotIn("collect_jp", daily)

    def test_collect_mains_do_not_print_identifiers(self):
        for func in (jp_main, us_main, funds_main):
            source = inspect.getsource(func)
            self.assertIn("finish_collection", source)
            self.assertNotIn('row["symbol"]', source)
            self.assertNotIn('row["name"]', source)


if __name__ == "__main__":
    unittest.main()
