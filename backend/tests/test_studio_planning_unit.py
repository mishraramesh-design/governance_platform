import unittest

from studio_planning import build_run_plan, extract_candidate_requirements, summarize_runtime_logs


class GovernanceStudioPlanningTests(unittest.TestCase):
    def test_requirement_candidates_keep_source_line_and_id(self):
        result = extract_candidate_requirements("Context\nFR-12 The service shall reject expired tokens.")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "FR-12")
        self.assertEqual(result[0]["source_line"], 2)
        self.assertEqual(result[0]["trace_status"], "candidate_unreviewed")

    def test_runtime_summary_never_returns_raw_log(self):
        raw = "INFO GET /health 200\nERROR GET /api/items 503 unauthorized"
        result = summarize_runtime_logs(raw)
        self.assertEqual(result["line_count"], 2)
        self.assertEqual(result["error_lines"], 1)
        self.assertEqual(result["http_5xx_lines"], 1)
        self.assertFalse(result["raw_log_content_retained"])
        self.assertNotIn(raw, str(result))

    def test_target_requires_authorization_and_dynamic_test_is_not_claimed(self):
        blocked = build_run_plan(False, False, True, False, False)
        self.assertEqual(blocked[0]["state"], "authorization_required")
        web = next(step for step in blocked if step["id"] == "WEB-01")
        self.assertEqual(web["state"], "not_executed_no_scanner_adapter")
        approved = build_run_plan(False, False, True, False, True)
        self.assertEqual(approved[0]["state"], "ready")


if __name__ == "__main__":
    unittest.main()
