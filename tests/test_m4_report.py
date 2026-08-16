import unittest

from social_content_engine.intelligence.m4_report import build_viral_pattern_report


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


if __name__ == "__main__":
    unittest.main()
