"""Bounded OWASP ZAP web assessment integration for Governance Studio."""
import asyncio
import ipaddress
import os
import re
import socket
from datetime import datetime, timezone
from urllib.parse import unquote, urlsplit

import httpx
from detectors import mask_sensitive_text
from scan_scope import build_zap_context_regexes


MAX_SPIDER_SECONDS = 120
MAX_SPIDER_DEPTH = 5
MAX_PASSIVE_QUEUE_SECONDS = 120
MAX_SPIDER_CHILDREN = 50
MAX_ALERTS = 500
MAX_ACTIVE_SCAN_SECONDS = 180


async def validate_public_target(target_url: str):
    """Reject unsafe schemes, credentials, local names and non-public IPs.

    Resolution is checked before the scan to reduce SSRF risk. Production
    deployments should additionally enforce scanner egress network policy.
    """
    parsed = urlsplit((target_url or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Web security scans require an HTTPS target URL.")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Target URLs cannot contain credentials or fragments.")
    if parsed.query:
        raise ValueError("Target URLs cannot contain query parameters; provide the public page URL without tokens or personal data.")
    decoded_path = parsed.path
    for _ in range(3):
        decoded_path = unquote(decoded_path)
    if "\\" in decoded_path or any(segment in (".", "..") for segment in decoded_path.split("/")):
        raise ValueError("Target URL paths cannot contain dot segments or backslashes.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or "." not in hostname:
        raise ValueError("Target must be a public fully qualified hostname.")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal and not literal.is_global:
        raise ValueError("Private, loopback, link-local, multicast, and reserved targets are blocked.")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Target hostname did not resolve to a public address.") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise ValueError("Target hostname did not resolve to a public address.")
    if any(not ipaddress.ip_address(address.split("%", 1)[0]).is_global for address in addresses):
        raise ValueError("Target resolves to a private, loopback, link-local, multicast, or reserved address.")
    return parsed


class AuthorizationWindowExpired(RuntimeError):
    pass


class ZapApi:
    def __init__(self):
        self.base_url = os.environ["ZAP_API_URL"].rstrip("/")
        self.api_key = os.environ["ZAP_API_KEY"]
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5), trust_env=False)

    async def get(self, path, *, deadline=None, allow_after_deadline=False, **params):
        timeout = 15
        if deadline is not None:
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0 and not allow_after_deadline:
                raise AuthorizationWindowExpired("authorization_window_expired")
            if remaining > 0:
                timeout = min(timeout, remaining)
        response = await self.client.get(f"{self.base_url}/JSON/{path}/", params={"apikey": self.api_key, **params}, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("code"):
            raise RuntimeError(f"ZAP API error: {payload.get('message', payload['code'])}")
        return payload

    async def close(self):
        await self.client.aclose()


def _in_scope(alert: dict, parsed):
    candidate = urlsplit(alert.get("url") or "")
    candidate_host = (candidate.hostname or "").lower()
    target_host = (parsed.hostname or "").lower()
    candidate_port = candidate.port or (443 if candidate.scheme.lower() == "https" else None)
    target_port = parsed.port or 443
    if candidate.scheme.lower() != "https" or candidate_host != target_host or candidate_port != target_port:
        return False
    root = parsed.path.rstrip("/") or "/"
    return candidate.path == root or root == "/" or candidate.path.startswith(root + "/")


def _masked(value, limit):
    text = str(value or "")[:limit]
    return mask_sensitive_text(text)[0]


def validate_scan_exclusions(target_url: str, excluded_paths=None):
    parsed = urlsplit(target_url)
    normalized_root = parsed.path.rstrip("/") or "/"
    exclusions = sorted(set(excluded_paths or []))
    for excluded_path in exclusions:
        excluded_root = excluded_path.rstrip("/") or "/"
        if excluded_root == "/" or normalized_root == excluded_root or normalized_root.startswith(excluded_root + "/"):
            raise ValueError("An excluded path would exclude the entire selected scan scope.")
    return exclusions


async def execute_zap_baseline(target_url: str, run_id: str, window_expires_at: datetime, active=False, excluded_paths=None):
    """Run a bounded spider/passive scan and optionally a low-strength active scan."""
    if window_expires_at.tzinfo is None:
        window_expires_at = window_expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= window_expires_at:
        raise AuthorizationWindowExpired("authorization_window_expired")
    parsed = await validate_public_target(target_url)
    exclusions = validate_scan_exclusions(target_url, excluded_paths)
    if datetime.now(timezone.utc) >= window_expires_at:
        raise AuthorizationWindowExpired("authorization_window_expired")
    zap = ZapApi()
    context_name = f"studio-{re.sub('[^a-zA-Z0-9_-]', '', run_id)[:32]}"
    scan_id = None
    active_scan_id = None
    spider_completed = False
    active_scan_completed = False
    try:
        version_data = await zap.get("core/view/version", deadline=window_expires_at)
        version = version_data.get("version", "unknown")
        # This deployment uses one private, serialized ZAP daemon. Reset its
        # in-memory session so results from earlier projects cannot mix in.
        await zap.get("core/action/newSession", deadline=window_expires_at, name=context_name, overwrite="true")
        await zap.get("spider/action/setOptionMaxDuration", deadline=window_expires_at, Integer=2)
        await zap.get("spider/action/setOptionMaxDepth", deadline=window_expires_at, Integer=MAX_SPIDER_DEPTH)
        await zap.get("spider/action/setOptionMaxChildren", deadline=window_expires_at, Integer=MAX_SPIDER_CHILDREN)
        context_result = await zap.get("context/action/newContext", deadline=window_expires_at, contextName=context_name)
        context_id = str(context_result.get("contextId", ""))
        scope_regex, excluded_regexes = build_zap_context_regexes(parsed, exclusions)
        await zap.get("context/action/includeInContext", deadline=window_expires_at, contextName=context_name, regex=scope_regex)
        for excluded_regex in excluded_regexes:
            await zap.get("context/action/excludeFromContext", deadline=window_expires_at,
                          contextName=context_name, regex=excluded_regex)
        # Initial target is the exact URL supplied. Crawling is restricted to
        # the exact host and target path subtree through the ZAP context.
        scan = await zap.get("spider/action/scan", deadline=window_expires_at, url=target_url, contextName=context_name,
                             recurse="true", subtreeOnly="true", maxChildren=MAX_SPIDER_CHILDREN)
        scan_id = str(scan["scan"])
        loop = asyncio.get_running_loop()
        spider_deadline = min(loop.time() + MAX_SPIDER_SECONDS, loop.time() + max(0, (window_expires_at - datetime.now(timezone.utc)).total_seconds()))
        while loop.time() < spider_deadline:
            status = await zap.get("spider/view/status", deadline=window_expires_at, scanId=scan_id)
            if int(status.get("status", 0)) >= 100:
                spider_completed = True
                break
            await asyncio.sleep(2)
        else:
            if datetime.now(timezone.utc) >= window_expires_at:
                raise AuthorizationWindowExpired("authorization_window_expired")
            await zap.get("spider/action/stop", deadline=window_expires_at, scanId=scan_id)

        passive_deadline = min(loop.time() + MAX_PASSIVE_QUEUE_SECONDS, loop.time() + max(0, (window_expires_at - datetime.now(timezone.utc)).total_seconds()))
        passive_queue_drained = False
        while loop.time() < passive_deadline:
            queue = await zap.get("pscan/view/recordsToScan", deadline=window_expires_at)
            if int(queue.get("recordsToScan", 0)) <= 0:
                passive_queue_drained = True
                break
            await asyncio.sleep(2)

        if datetime.now(timezone.utc) >= window_expires_at:
            raise AuthorizationWindowExpired("authorization_window_expired")

        if active:
            # ZAP active scanning sends attack requests. Keep it opt-in, low
            # strength, single-threaded, exact-context scoped, and time bounded.
            await zap.get("ascan/action/setOptionAttackStrength", deadline=window_expires_at, String="LOW")
            await zap.get("ascan/action/setOptionMaxScanDurationInMins", deadline=window_expires_at, Integer=3)
            await zap.get("ascan/action/setOptionMaxRuleDurationInMins", deadline=window_expires_at, Integer=1)
            await zap.get("ascan/action/setOptionThreadPerHost", deadline=window_expires_at, Integer=1)
            if not context_id:
                raise RuntimeError("zap_context_id_unavailable")
            active_scan = await zap.get("ascan/action/scan", deadline=window_expires_at, url=target_url,
                                       recurse="true", inScopeOnly="true", contextId=context_id)
            active_scan_id = str(active_scan["scan"])
            active_deadline = min(loop.time() + MAX_ACTIVE_SCAN_SECONDS,
                                  loop.time() + max(0, (window_expires_at - datetime.now(timezone.utc)).total_seconds()))
            while loop.time() < active_deadline:
                status = await zap.get("ascan/view/status", deadline=window_expires_at, scanId=active_scan_id)
                if int(status.get("status", 0)) >= 100:
                    active_scan_completed = True
                    break
                await asyncio.sleep(2)
            else:
                if datetime.now(timezone.utc) >= window_expires_at:
                    raise AuthorizationWindowExpired("authorization_window_expired")
                await zap.get("ascan/action/stop", deadline=window_expires_at, scanId=active_scan_id)

        alerts_payload = await zap.get("core/view/alerts", deadline=window_expires_at, baseurl=target_url, start=0, count=MAX_ALERTS)
        alerts = alerts_payload.get("alerts", [])
        findings = []
        seen = set()
        for alert in alerts:
            if not _in_scope(alert, parsed):
                continue
            key = (alert.get("pluginId"), alert.get("url"), alert.get("param"), alert.get("name"))
            if key in seen:
                continue
            seen.add(key)
            findings.append({
                "scanner_id": str(alert.get("pluginId", "")),
                "name": _masked(alert.get("name", "Security alert"), 300),
                "risk": str(alert.get("risk", "Informational")),
                "confidence": str(alert.get("confidence", "")),
                "url": _masked(alert.get("url", ""), 2048),
                "method": str(alert.get("method", ""))[:16],
                "parameter": _masked(alert.get("param", ""), 300),
                "evidence": _masked(alert.get("evidence", ""), 1000),
                "description": _masked(alert.get("description", ""), 5000),
                "remediation": _masked(alert.get("solution", ""), 5000),
                "reference": _masked(alert.get("reference", ""), 3000),
                "cwe_id": str(alert.get("cweid", "")),
                "wasc_id": str(alert.get("wascid", "")),
                "alert_reference": str(alert.get("alertRef", "")),
            })
        return findings, {"name": "OWASP ZAP", "version": str(version),
                          "ruleset": "installed passive and low-strength active rules" if active else "installed passive scan rules",
                          "max_spider_children_per_page": MAX_SPIDER_CHILDREN,
                          "excluded_paths": exclusions,
                          "max_spider_depth": MAX_SPIDER_DEPTH,
                          "max_spider_seconds": MAX_SPIDER_SECONDS, "max_passive_queue_seconds": MAX_PASSIVE_QUEUE_SECONDS,
                          "max_active_scan_seconds": MAX_ACTIVE_SCAN_SECONDS if active else 0,
                          "spider_completed": spider_completed, "passive_queue_drained": passive_queue_drained,
                          "active_scan_completed": active_scan_completed,
                          "coverage_status": "complete" if spider_completed and passive_queue_drained and (not active or active_scan_completed) else "partial",
                          "active_scan": bool(active), "attack_strength": "LOW" if active else None,
                          "authenticated_scan": False}
    finally:
        if scan_id and not spider_completed:
            try:
                await zap.get("spider/action/stop", allow_after_deadline=True, scanId=scan_id)
            except Exception:
                pass
        if active_scan_id and not active_scan_completed:
            try:
                await zap.get("ascan/action/stop", allow_after_deadline=True, scanId=active_scan_id)
            except Exception:
                pass
        await zap.close()
