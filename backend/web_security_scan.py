"""Bounded OWASP ZAP passive baseline integration for Governance Studio.

The scanner is intentionally limited to an unauthenticated crawl plus passive
rules. It does not run ZAP's active scanner or load/performance tests.
"""
import asyncio
import ipaddress
import os
import re
import socket
from urllib.parse import urlsplit

import httpx
from detectors import mask_sensitive_text


MAX_SPIDER_SECONDS = 120
MAX_SPIDER_DEPTH = 5
MAX_PASSIVE_QUEUE_SECONDS = 120
MAX_SPIDER_CHILDREN = 50
MAX_ALERTS = 500


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


class ZapApi:
    def __init__(self):
        self.base_url = os.environ["ZAP_API_URL"].rstrip("/")
        self.api_key = os.environ["ZAP_API_KEY"]
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5), trust_env=False)

    async def get(self, path, **params):
        response = await self.client.get(f"{self.base_url}/JSON/{path}/", params={"apikey": self.api_key, **params})
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("code"):
            raise RuntimeError(f"ZAP API error: {payload.get('message', payload['code'])}")
        return payload

    async def close(self):
        await self.client.aclose()


def _in_scope(alert: dict, parsed):
    candidate = urlsplit(alert.get("url") or "")
    if candidate.scheme.lower() != "https" or candidate.hostname != parsed.hostname or candidate.port != parsed.port:
        return False
    root = parsed.path.rstrip("/") or "/"
    return candidate.path == root or root == "/" or candidate.path.startswith(root + "/")


def _masked(value, limit):
    text = str(value or "")[:limit]
    return mask_sensitive_text(text)[0]


async def execute_zap_baseline(target_url: str, run_id: str):
    """Run a time- and page-bounded spider and passive scan in ZAP."""
    parsed = await validate_public_target(target_url)
    zap = ZapApi()
    context_name = f"studio-{re.sub('[^a-zA-Z0-9_-]', '', run_id)[:32]}"
    try:
        version_data = await zap.get("core/view/version")
        version = version_data.get("version", "unknown")
        # This deployment uses one private, serialized ZAP daemon. Reset its
        # in-memory session so results from earlier projects cannot mix in.
        await zap.get("core/action/newSession", name=context_name, overwrite="true")
        await zap.get("spider/action/setOptionMaxDuration", Integer=2)
        await zap.get("spider/action/setOptionMaxDepth", Integer=MAX_SPIDER_DEPTH)
        await zap.get("spider/action/setOptionMaxChildren", Integer=MAX_SPIDER_CHILDREN)
        context = await zap.get("context/action/newContext", contextName=context_name)
        escaped_host = re.escape(parsed.hostname)
        port = f":{parsed.port}" if parsed.port and parsed.port != 443 else ""
        root_path = parsed.path.rstrip("/") or "/"
        escaped_path = re.escape(root_path.rstrip("/"))
        if root_path == "/":
            scope_regex = rf"^https://{escaped_host}{port}(?:/.*)?$"
        else:
            scope_regex = rf"^https://{escaped_host}{port}{escaped_path}(?:/.*)?(?:\?.*)?$"
        await zap.get("context/action/includeInContext", contextName=context_name, regex=scope_regex)
        # Initial target is the exact URL supplied. Crawling is restricted to
        # the exact host and target path subtree through the ZAP context.
        scan = await zap.get("spider/action/scan", url=target_url, contextName=context_name,
                             recurse="true", subtreeOnly="true", maxChildren=MAX_SPIDER_CHILDREN)
        scan_id = str(scan["scan"])
        loop = asyncio.get_running_loop()
        deadline = loop.time() + MAX_SPIDER_SECONDS
        spider_completed = False
        while loop.time() < deadline:
            status = await zap.get("spider/view/status", scanId=scan_id)
            if int(status.get("status", 0)) >= 100:
                spider_completed = True
                break
            await asyncio.sleep(2)
        else:
            await zap.get("spider/action/stop", scanId=scan_id)

        deadline = loop.time() + MAX_PASSIVE_QUEUE_SECONDS
        passive_queue_drained = False
        while loop.time() < deadline:
            queue = await zap.get("pscan/view/recordsToScan")
            if int(queue.get("recordsToScan", 0)) <= 0:
                passive_queue_drained = True
                break
            await asyncio.sleep(2)

        alerts_payload = await zap.get("core/view/alerts", baseurl=target_url, start=0, count=MAX_ALERTS)
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
                          "ruleset": "installed passive scan rules", "max_spider_children_per_page": MAX_SPIDER_CHILDREN,
                          "max_spider_depth": MAX_SPIDER_DEPTH,
                          "max_spider_seconds": MAX_SPIDER_SECONDS, "max_passive_queue_seconds": MAX_PASSIVE_QUEUE_SECONDS,
                          "spider_completed": spider_completed, "passive_queue_drained": passive_queue_drained,
                          "coverage_status": "complete" if spider_completed and passive_queue_drained else "partial",
                          "active_scan": False, "authenticated_scan": False}
    finally:
        await zap.close()
