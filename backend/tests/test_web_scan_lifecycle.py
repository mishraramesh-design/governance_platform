"""Offline adapter lifecycle tests; no target requests or real ZAP daemon."""
import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

spec = importlib.util.spec_from_file_location("zap_lifecycle_under_test", Path(__file__).parents[1] / "web_security_scan.py")
scan = importlib.util.module_from_spec(spec)
# The lightweight local runtime need not install the HTTP transport to test policy.
with patch.dict(sys.modules, {"httpx": SimpleNamespace()}):
    spec.loader.exec_module(scan)


def finish(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    raise AssertionError("Unexpected real asynchronous I/O in offline test")


class ScanLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.queue_calls = 0
        self.target = "https://staging.example.test/"
        self.expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        self.progress = AsyncMock()
        self.zap = SimpleNamespace(get=AsyncMock(side_effect=self.reply), close=AsyncMock())

    def reply(self, path, **kwargs):
        self.calls.append((path, kwargs))
        if path == "core/view/version": return {"version": "test"}
        if path == "context/action/newContext": return {"contextId": "1"}
        if path in ("spider/action/scan", "ascan/action/scan"): return {"scan": "0"}
        if path.endswith("/status"): return {"status": "100"}
        if path == "pscan/view/recordsToScan":
            self.queue_calls += 1
            return {"recordsToScan": "0"}
        if path == "core/view/alerts":
            return {"alerts": [{"url": self.target + "logout?next=1", "name": "excluded"},
                               {"url": self.target, "name": "retained", "risk": "Low"}]}
        return {}

    def execute(self, active=True):
        with patch.object(scan, "ZapApi", return_value=self.zap), \
             patch.object(scan, "validate_public_target", AsyncMock(return_value=urlsplit(self.target))), \
             patch.object(scan.asyncio, "get_running_loop", return_value=SimpleNamespace(time=lambda: 0)):
            return finish(scan.execute_zap_baseline(self.target, "test", self.expiry,
                active=active, excluded_paths=["/logout"], progress=self.progress))

    def test_active_job_drains_passive_queue_twice_and_filters_exclusions(self):
        findings, metadata = self.execute()
        self.assertEqual([item["name"] for item in findings], ["retained"])
        self.assertEqual(self.queue_calls, 2)
        self.assertEqual(metadata["coverage_status"], "bounded_run_finished")
        self.assertIn(10047, metadata["excluded_active_rule_ids"])
        self.assertIn("context/action/setContextInScope", [path for path, _ in self.calls])
        self.assertIn("finalizing_passive_analysis", [call.args[0] for call in self.progress.await_args_list])
        self.zap.close.assert_awaited_once()

    def test_cancel_during_crawl_stops_scanner(self):
        class CancelledByOperator(Exception): pass
        async def cancel(stage, details):
            if stage == "crawling": raise CancelledByOperator()
        self.progress.side_effect = cancel
        with self.assertRaises(CancelledByOperator): self.execute()
        self.assertIn("spider/action/stop", [path for path, _ in self.calls])
        self.zap.close.assert_awaited_once()

    def test_failed_stop_is_not_silently_reported_as_cancelled(self):
        async def cancel(stage, details):
            if stage == "crawling": raise ValueError("cancelled")
        self.progress.side_effect = cancel
        original = self.reply
        def fail_stop(path, **kwargs):
            if path == "spider/action/stop": raise ConnectionError()
            return original(path, **kwargs)
        self.zap.get.side_effect = fail_stop
        with self.assertRaises(scan.ScannerCleanupFailed): self.execute()
        self.zap.close.assert_awaited_once()

    def test_api_key_is_header_only(self):
        response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"version": "test"})
        transport = SimpleNamespace(get=AsyncMock(return_value=response))
        api = scan.ZapApi.__new__(scan.ZapApi)
        api.base_url = "http://zap:8080"
        api.api_key = "synthetic-canary"
        api.client = transport
        finish(api.get("core/view/version"))
        args = transport.get.await_args
        self.assertEqual(args.kwargs["headers"], {"X-ZAP-API-Key": "synthetic-canary"})
        self.assertNotIn("apikey", args.kwargs["params"])
        self.assertNotIn("synthetic-canary", args.args[0])


if __name__ == "__main__": unittest.main()
