import json
import tempfile
import unittest
from pathlib import Path

from social_content_engine.intelligence.m4_report import (
    build_viral_pattern_report,
    write_viral_pattern_report,
)


class _Connection:
    def execute(self, query, _params=()):
        value = {"dataset_snapshot_id": 2} if "m4_intelligence_runs" in query else (0,)
        return _Rows(value)


class _Rows:
    def __init__(self, one):
        self.one = one

    def fetchone(self):
        return self.one

    def fetchall(self):
        return []


class _Repository:
    connection = _Connection()


class M4ReportTest(unittest.TestCase):
    def test_missing_metrics_are_explicitly_insufficient(self):
        report = build_viral_pattern_report(_Repository(), 1)
        self.assertEqual("INSUFFICIENT_COVERAGE", report["performance_association"]["status"])
        self.assertEqual([], report["top_first_line_patterns"])
        self.assertEqual(
            "INSUFFICIENT_EVIDENCE", report["section_status"]["top_open_loop_patterns"]
        )

    def test_written_report_is_deterministic_and_text_free(self):
        report = build_viral_pattern_report(_Repository(), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_path = root / "report.json"
            markdown_path = root / "report.md"
            write_viral_pattern_report(report, json_path, markdown_path)
            first_json = json_path.read_text(encoding="utf-8")
            first_markdown = markdown_path.read_text(encoding="utf-8")
            write_viral_pattern_report(report, json_path, markdown_path)
            self.assertEqual(first_json, json_path.read_text(encoding="utf-8"))
            self.assertEqual(first_markdown, markdown_path.read_text(encoding="utf-8"))
            self.assertNotIn("source_post", first_json)
            self.assertNotIn("username", first_markdown)
            self.assertEqual(report, json.loads(first_json))


if __name__ == "__main__":
    unittest.main()
