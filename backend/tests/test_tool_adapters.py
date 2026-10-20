import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tool_adapters import (TOOL_SPECS, _PLAYWRIGHT_SMOKE, _assessment_argv, _k6_smoke_script, framework_inventory,
                           run_repository_static_tools)
from safe_logging import run_log_canary_test
from models import StudioFrameworkAssessmentRequest


class GovernanceToolAdapterTests(unittest.TestCase):
    def test_inventory_covers_every_recommended_framework(self):
        self.assertEqual({item["id"] for item in framework_inventory()}, set(TOOL_SPECS))

    def test_static_runner_reports_missing_tools_and_gated_tool_prerequisites(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[2]) as directory:
            Path(directory, "app.py").write_text("print('ok')", encoding="utf-8")
            with patch("tool_adapters.shutil.which", return_value=None):
                results = run_repository_static_tools(directory)
        by_id = {item["tool_id"]: item for item in results}
        for tool_id in ("semgrep-ce", "gitleaks", "trivy", "native-quality-tools"):
            self.assertEqual(by_id[tool_id]["status"], "blocked_tool_not_installed")
        for tool_id in ("playwright", "schemathesis", "hypothesis", "k6"):
            self.assertEqual(by_id[tool_id]["status"], "blocked_prerequisite_required")
            self.assertFalse(by_id[tool_id]["executed"])

    def test_tool_output_is_hashed_and_not_retained(self):
        sensitive = "synthetic-secret-canary-do-not-store"
        completed = SimpleNamespace(returncode=1, stdout=json.dumps({"results": [{"secret": sensitive}]}), stderr=sensitive)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[2]) as directory:
            Path(directory, "app.py").write_text("print('ok')", encoding="utf-8")
            for name in ("semgrep", "gitleaks", "trivy", "ruff"):
                Path(directory, name).write_text("", encoding="utf-8")
            with patch("tool_adapters.shutil.which", return_value="/fake/tool"), patch("tool_adapters.subprocess.run", return_value=completed):
                results = run_repository_static_tools(directory)
        rendered = json.dumps(results)
        self.assertNotIn(sensitive, rendered)
        self.assertTrue(all(item.get("output_sha256") for item in results if item["tool_id"] in {"semgrep-ce", "gitleaks", "trivy", "native-quality-tools"}))
        semgrep = next(item for item in results if item["tool_id"] == "semgrep-ce")
        self.assertEqual(semgrep["finding_count"], 1)
        self.assertEqual(semgrep["status"], "completed_with_findings")

    def test_dynamic_tool_commands_are_fixed_and_bounded(self):
        compile(_PLAYWRIGHT_SMOKE, "playwright_smoke.py", "exec")
        target = "https://staging.example.test/app"
        schema = "https://staging.example.test/app/openapi.json"
        playwright = _assessment_argv("playwright", target)
        self.assertEqual(playwright[0:2], ["python", "-c"])
        self.assertEqual(playwright[-1], target)
        schemathesis = _assessment_argv("schemathesis", target, openapi_url=schema, max_examples=12)
        self.assertIn("--max-examples", schemathesis)
        self.assertEqual(schemathesis[schemathesis.index("--max-examples") + 1], "12")
        self.assertIn("--workers", schemathesis)
        self.assertIn("--seed", schemathesis)
        self.assertEqual(schemathesis[schemathesis.index("--rate-limit") + 1], "1/s")
        self.assertEqual(schemathesis[schemathesis.index("--max-redirects") + 1], "0")
        k6 = _assessment_argv("k6", target, virtual_users=3, duration_seconds=30, workdir="/tmp")
        self.assertEqual(k6[k6.index("--vus") + 1], "3")
        self.assertEqual(k6[k6.index("--duration") + 1], "30s")
        script = _k6_smoke_script(target, 850, 2.5)
        self.assertIn("p(95)<850", script)
        self.assertIn("rate<0.025", script)
        self.assertIn("redirects: 0", script)
        self.assertIn("sleep(1)", script)

    def test_studio_logging_canary_is_redacted(self):
        result = run_log_canary_test()
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["canary_absent"])
        self.assertNotIn("synthetic authorization token", json.dumps(result))

    def test_framework_request_enforces_bounded_parameters(self):
        request = StudioFrameworkAssessmentRequest(framework="k6", staging_authorized=True)
        self.assertEqual(request.virtual_users, 2)
        with self.assertRaises(ValueError):
            StudioFrameworkAssessmentRequest(framework="k6", virtual_users=4)
        with self.assertRaises(ValueError):
            StudioFrameworkAssessmentRequest(framework="schemathesis", max_examples=100)


if __name__ == "__main__":
    unittest.main()
