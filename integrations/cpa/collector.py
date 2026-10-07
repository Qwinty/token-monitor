#!/usr/bin/env python3
"""Publish CPA account quotas to the Token Monitor Hub without exporting credentials."""
import argparse
import base64
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

SUPPORTED = {"codex", "claude", "antigravity"}
POLL_SECONDS = 300


def timestamp(value):
    if isinstance(value, (int, float)):
        return value / 1000 if value > 10**12 else value
    if isinstance(value, str) and value:
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return 0


def iso(value=None):
    return dt.datetime.fromtimestamp(time.time() if value is None else value, dt.timezone.utc).isoformat()


def number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def identity(file):
    claims = file.get("id_token") or {}
    if isinstance(claims, str):
        try:
            segment = claims.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        except (ValueError, IndexError):
            claims = {}
    auth = claims.get("https://api.openai.com/auth", claims) if isinstance(claims, dict) else {}
    account_id = auth.get("chatgpt_account_id", "") or file.get("account_id", "")
    email = file.get("email") or file.get("account") or ""
    provider = file.get("provider") or file.get("type") or ""
    # A member can own several workspaces; an email alone is not an identity.
    discriminator = (str(account_id) + "\0" + email.lower()) if account_id and email else str(file.get("id") or file.get("name") or file.get("auth_index"))
    key = "sha256:" + hashlib.sha256(("cpa\0" + provider + "\0" + discriminator).encode()).hexdigest()
    return key, str(account_id), str(auth.get("plan_type") or file.get("account_type") or ""), email


def window(kind, label, used, reset=None, duration=None, **extra):
    used = number(used)
    if used is None:
        return None
    return {"kind": kind, "label": label, "usedPercent": max(0, min(100, used)),
            "resetsAt": iso(timestamp(reset)) if timestamp(reset) else None,
            "windowMinutes": duration, **extra}


def parse_quota(provider, payload):
    windows = []
    if provider == "codex":
        def append_limits(limits, label="", additional=False):
            for name in ("primary_window", "secondary_window"):
                item = limits.get(name)
                if not isinstance(item, dict):
                    continue
                seconds = number(item.get("limit_window_seconds"))
                kind = "weekly" if seconds and seconds >= 604800 else "daily" if seconds and seconds >= 86400 else "session"
                windows.append(window(kind, label, item.get("used_percent"), item.get("reset_at"), seconds / 60 if seconds else None, additional=additional))
        append_limits(payload.get("rate_limit") or {})
        for item in payload.get("additional_rate_limits") or []:
            append_limits(item.get("rate_limit") or {}, item.get("limit_name") or item.get("metered_feature") or "Additional", True)
    elif provider == "claude":
        for key, label in (("five_hour", ""), ("seven_day", ""), ("seven_day_opus", "Opus"), ("seven_day_sonnet", "Sonnet"), ("seven_day_oauth_apps", "OAuth apps")):
            item = payload.get(key)
            if isinstance(item, dict):
                windows.append(window("session" if key == "five_hour" else "weekly", label, item.get("utilization"), item.get("resets_at"), 300 if key == "five_hour" else 10080))
    elif provider == "antigravity":
        payload = payload.get("response", payload)
        for group in payload.get("groups") or []:
            for bucket in group.get("buckets") or []:
                fraction = number(bucket.get("remainingFraction", bucket.get("remaining_fraction")))
                if fraction is None:
                    continue
                cadence = str(bucket.get("window") or "weekly").lower()
                kind = "session" if "hour" in cadence else "daily" if "day" in cadence and "week" not in cadence else "weekly"
                label = group.get("displayName") or group.get("display_name") or "Models"
                windows.append(window(kind, label, (1 - fraction) * 100, bucket.get("resetTime") or bucket.get("reset_time")))
        if not windows:
            # Older endpoints return model records, with several aliases sharing a quota.
            groups = {}
            for model, item in (payload.get("models") or {}).items():
                quota = item.get("quotaInfo") or item.get("quota_info") or {}
                fraction = number(quota.get("remainingFraction", quota.get("remaining_fraction")))
                if fraction is None:
                    continue
                label = "Claude" if "claude" in model or "gpt-oss" in model else "Gemini Flash" if "flash" in model else "Gemini Pro" if "gemini" in model and "pro" in model else model
                candidate = window("weekly", label, (1 - fraction) * 100, quota.get("resetTime") or quota.get("reset_time"))
                if label not in groups or candidate["usedPercent"] > groups[label]["usedPercent"]:
                    groups[label] = candidate
            windows.extend(groups.values())
    return [item for item in windows if item]


class APIError(Exception):
    def __init__(self, status, retry_seconds=0):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.retry_seconds = retry_seconds


class Collector:
    def __init__(self):
        self.base = os.environ.get("CPA_MANAGER_URL", "http://127.0.0.1:18317").rstrip("/")
        self.admin = os.environ["CPA_MANAGER_ADMIN_KEY"]
        self.hub = os.environ.get("TOKEN_MONITOR_HUB_URL", "http://127.0.0.1:17321").rstrip("/")
        self.secret = os.environ["TOKEN_MONITOR_SECRET"]
        self.device_id = os.environ.get("CPA_DEVICE_ID", "cpa-maxim")
        self.cache_path = Path(os.environ.get("CPA_CACHE_PATH", "/opt/token-monitor/data/cpa-cache.json"))
        try:
            self.cache = json.loads(self.cache_path.read_text())
        except (OSError, ValueError):
            self.cache = {}

    def request(self, path, body=None, hub=False):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request((self.hub if hub else self.base) + path, data=data,
                                        headers={"Authorization": "Bearer " + (self.secret if hub else self.admin), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=65) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise APIError(error.code) from None

    def fetch_quota(self, file):
        provider = file["provider"]
        _, account_id, _, _ = identity(file)
        headers = {"Authorization": "Bearer $TOKEN$", "Content-Type": "application/json"}
        data = ""
        method = "GET"
        if provider == "codex":
            urls = ["https://chatgpt.com/backend-api/wham/usage"]
            if account_id:
                headers["Chatgpt-Account-Id"] = account_id
        elif provider == "claude":
            urls = ["https://api.anthropic.com/api/oauth/usage"]
            headers["anthropic-beta"] = "oauth-2025-04-20"
        else:
            urls = ["https://daily-cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary",
                    "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuotaSummary",
                    "https://daily-cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels",
                    "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"]
            headers["User-Agent"] = "antigravity/1.20.5 linux/amd64"
            data = json.dumps({"project": file.get("project_id") or "bamboo-precept-lgxtn"})
            method = "POST"
        last_status = 502
        for url in urls:
            result = self.request("/v0/management/api-call", {"auth_index": str(file["auth_index"]), "method": method, "url": url, "header": headers, "data": data})
            status = result.get("status_code", 502)
            last_status = status
            if status == 429:
                raw_retry = next((v for k, v in result.get("header", {}).items() if k.lower() == "retry-after"), [0])
                try:
                    retry = float(raw_retry[0] if isinstance(raw_retry, list) else raw_retry)
                except (ValueError, TypeError):
                    retry = max(0, timestamp(raw_retry) - time.time())
                raise APIError(status, max(retry, 900))
            if status in (401, 403) and provider != "antigravity":
                raise APIError(status)
            if 200 <= status < 300:
                payload = json.loads(result.get("body", "{}"))
                windows = parse_quota(provider, payload)
                if windows:
                    return windows, payload.get("plan_type", "")
        raise APIError(last_status if last_status >= 400 else 502)

    def snapshots(self, files):
        accounts = []
        for file in files:
            key, account_id, _, email = identity(file)
            accounts.append({"row_key": key, "provider": file["provider"], "account": {
                "auth_index": str(file.get("auth_index", "")), "auth_file_snapshot": file.get("name", ""),
                "auth_provider_snapshot": file["provider"], "auth_account_id_snapshot": account_id,
                "account_snapshot": email, "auth_label_snapshot": file.get("label", ""),
                "auth_project_id_snapshot": "" if file["provider"] == "codex" else file.get("project_id", ""),
                "source": file.get("name", "")}})
        try:
            return {item["row_key"]: item.get("windows", []) for item in self.request("/v0/management/quota-snapshots/query", {"accounts": accounts}).get("items", [])}
        except (APIError, urllib.error.URLError, ValueError):
            return {}

    def collect(self):
        now = time.time()
        files = self.request("/v0/management/auth-files").get("files", [])
        files = [dict(file, provider=file.get("provider") or file.get("type")) for file in files if (file.get("provider") or file.get("type")) in SUPPORTED]
        snapshots = self.snapshots(files)
        providers = []
        for file in files:
            key, _, plan, email = identity(file)
            entry = self.cache.get(key, {})
            snapshot = entry.get("snapshot", {})
            fresh = [item for item in snapshots.get(key, []) if not item.get("stale") and now - item.get("observed_at_ms", 0) / 1000 < POLL_SECONDS and item.get("availability") == "active"]
            observed = min((item.get("observed_at_ms", 0) / 1000 for item in fresh), default=0)
            if fresh and not snapshot:
                windows = [window("session" if item["window_kind"] in ("five_hour", "session") else "daily" if item["window_kind"] == "daily" else "weekly", item.get("model_scope_key", "") if file["provider"] == "antigravity" else "", item.get("used_percent", 100 - item["remaining_percent"] if number(item.get("remaining_percent")) is not None else None), item.get("cycle_end_ms"), (item.get("duration_seconds") or 0) / 60 or None) for item in fresh]
                windows = [item for item in windows if item]
                if windows:
                    snapshot = {"windows": windows, "updatedAt": iso(observed)}
                    # A snapshot is a fallback, not proof that all required windows are present.
                    entry = {"snapshot": snapshot, "nextAttempt": 0, "status": "unavailable"}
            if not file.get("disabled") and now >= entry.get("nextAttempt", 0):
                try:
                    windows, quota_plan = self.fetch_quota(file)
                    snapshot = {"windows": windows, "updatedAt": iso(), "planLabel": quota_plan or plan}
                    entry = {"snapshot": snapshot, "nextAttempt": time.time() + POLL_SECONDS, "status": "ok"}
                except (APIError, urllib.error.URLError, ValueError, TimeoutError) as error:
                    status = getattr(error, "status", 0)
                    entry = {"snapshot": snapshot, "nextAttempt": time.time() + max(POLL_SECONDS, getattr(error, "retry_seconds", 0)),
                             "status": "unauthorized" if status in (401, 403) else "sourceRateLimited" if status == 429 else "unavailable"}
                    print(f"quota probe: {file['provider']} {key[-8:]} {entry['status']}", flush=True)
            self.cache[key] = entry
            state = "disabled" if file.get("disabled") else entry.get("status", "unavailable")
            windows = list(snapshot.get("windows", []))
            for cooldown in file.get("cooldowns") or []:
                if cooldown.get("scope") == "credential" and timestamp(cooldown.get("retry_at")) > now:
                    state = "rateLimited"
                    windows.append(window("session", "CPA cooldown", 100, cooldown["retry_at"]))
            providers.append({"provider": file["provider"], "accountKey": key, "accountEmail": email if "@" in email else "",
                              "accountName": file.get("label") or email or file.get("name", "Account"),
                              "planLabel": snapshot.get("planLabel") or plan, "source": "api", "sourceDetail": "managed",
                              "status": state, "updatedAt": snapshot.get("updatedAt") or iso(now), "windows": windows})
        active = {provider["accountKey"] for provider in providers}
        self.cache = {key: value for key, value in self.cache.items() if key in active}
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.cache))
        temporary.chmod(0o600)
        temporary.replace(self.cache_path)
        payload = {"deviceId": self.device_id, "hostname": "CPA · maxim", "platform": "linux-x64", "osName": "Linux",
                   "updatedAt": iso(), "agentRuntime": "cpa-collector", "limitsOnly": True, "syncUploadIntervalMs": 0,
                   "historyAvailable": False, "projectsEnabled": False, "trackedClients": [],
                   "limits": {"updatedAt": iso(), "refreshMs": POLL_SECONDS * 1000, "providers": providers}}
        self.request("/api/ingest", payload, hub=True)
        counts = {provider: sum(item["provider"] == provider for item in providers) for provider in sorted(SUPPORTED)}
        print(f"published {len(providers)} accounts: {json.dumps(counts)}", flush=True)
        return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    collector = Collector()
    while True:
        try:
            collector.collect()
        except (APIError, urllib.error.URLError, ValueError, TimeoutError) as error:
            print(f"collector unavailable: {type(error).__name__} {getattr(error, 'status', '')}", flush=True)
            if args.once:
                raise SystemExit(1) from None
        if args.once:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
