import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from collector import APIError, Collector, identity, parse_quota


class QuotaTests(unittest.TestCase):
    def test_codex_keeps_additional_quotas_separate(self):
        payload = {"rate_limit": {"primary_window": {"used_percent": 10, "limit_window_seconds": 18000}},
                   "additional_rate_limits": [{"limit_name": "Spark", "rate_limit": {"primary_window": {"used_percent": 100}}}]}
        result = parse_quota("codex", payload)
        self.assertFalse(result[0]["additional"])
        self.assertTrue(result[1]["additional"])

    def test_missing_percent_is_unknown_instead_of_zero(self):
        self.assertEqual(parse_quota("codex", {"rate_limit": {"primary_window": {}}}), [])
        self.assertEqual(parse_quota("claude", {"five_hour": {"utilization": None}}), [])

    def test_antigravity_group_buckets_keep_model_scopes(self):
        result = parse_quota("antigravity", {"groups": [{"displayName": "Claude", "buckets": [{"remainingFraction": 0}, {"remainingFraction": .6}]}]})
        self.assertEqual([item["usedPercent"] for item in result], [100, 40])
        self.assertTrue(all(item["label"] == "Claude" for item in result))

    def test_workspace_members_have_separate_stable_identities(self):
        base = {"provider": "codex", "email": "a@example.com", "id_token": {"chatgpt_account_id": "one"}}
        other = {**base, "id_token": {"chatgpt_account_id": "two"}}
        self.assertNotEqual(identity(base)[0], identity(other)[0])
        self.assertEqual(identity(base)[0], identity({**base, "name": "renamed.json"})[0])

    def test_failed_probe_retains_quota_timestamp_and_backs_off(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = Collector.__new__(Collector)
            collector.device_id = "cpa-test"
            collector.cache_path = Path(directory) / "cache.json"
            collector.cache = {}
            files = [{"provider": "codex", "name": "one.json", "auth_index": "one"}]
            collector.request = lambda path, body=None, hub=False: {"files": files} if not hub else {"ok": True}
            collector.snapshots = lambda accounts: {}
            collector.fetch_quota = lambda file: ([{"kind": "session", "usedPercent": 20}], "Plus")
            with patch("collector.time.time", return_value=1000000000):
                successful = collector.collect()["limits"]["providers"][0]
            def fail(file):
                raise APIError(429, 900)
            collector.fetch_quota = fail
            with patch("collector.time.time", return_value=1000000400):
                failed = collector.collect()["limits"]["providers"][0]
            self.assertEqual(failed["updatedAt"], successful["updatedAt"])
            self.assertEqual(failed["windows"], successful["windows"])
            self.assertEqual(failed["status"], "sourceRateLimited")
            self.assertGreaterEqual(collector.cache[failed["accountKey"]]["nextAttempt"], 1000001300)
            files.clear()
            with patch("collector.time.time", return_value=1000000500):
                self.assertEqual(collector.collect()["limits"]["providers"], [])
            self.assertEqual(collector.cache, {})


if __name__ == "__main__":
    unittest.main()
