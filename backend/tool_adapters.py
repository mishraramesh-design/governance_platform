"""Governed, bounded adapters for optional deterministic assessment tools.

The adapters never use a shell and never interpret model output as commands.
Targeted runners are deliberately separate from repository-local static scans.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import shutil
import subprocess
import time
import re
from pathlib import Path


TOOL_SPECS = {
    "semgrep-ce": {"name": "Semgrep Community Edition", "binary": "semgrep", "stage": "code_review", "license": "LGPL-2.1", "kind": "static"},
    "native-quality-tools": {"name": "Language-native linters and type checkers", "binary": "ruff", "stage": "code_quality", "license": "varies", "kind": "static"},
    "gitleaks": {"name": "Gitleaks", "binary": "gitleaks", "stage": "secret_scanning", "license": "MIT", "kind": "static"},
    "trivy": {"name": "Trivy", "binary": "trivy", "stage": "supply_chain_and_artifacts", "license": "Apache-2.0", "kind": "static"},
    "structured-log-policy": {"name": "Structured logging allowlist and redaction policy", "binary": None, "stage": "log_prevention", "license": "project_owned", "kind": "application_control"},
    "log-canary-tests": {"name": "Runtime log canary tests", "binary": None, "stage": "log_leak_verification", "license": "project_owned", "kind": "test"},
    "playwright": {"name": "Playwright Test", "binary": "playwright", "stage": "ui_functional", "license": "Apache-2.0", "kind": "conditional"},
    "schemathesis": {"name": "Schemathesis", "binary": "schemathesis", "stage": "api_functional_and_robustness", "license": "MIT", "kind": "conditional"},
    "hypothesis": {"name": "Hypothesis", "binary": "hypothesis", "stage": "property_testing", "license": "MPL-2.0", "kind": "conditional"},
    "k6": {"name": "Grafana k6", "binary": "k6", "stage": "performance_and_scalability", "license": "AGPL-3.0", "kind": "conditional"},
}

MAX_COMMAND_SECONDS = 90


def framework_inventory():
    """Report runtime capability without implying a tool ran or passed."""
    items = []
    for tool_id, spec in TOOL_SPECS.items():
        binary = spec["binary"]
        binary_available = bool(shutil.which(binary)) if binary else False
        if tool_id == "hypothesis":
            # Schemathesis runs generated cases through Hypothesis; Hypothesis
            # itself has no standalone runner for arbitrary target schemas.
            binary_available = bool(shutil.which("schemathesis"))
        if tool_id == "playwright" and binary_available:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as playwright:
                    binary_available = Path(playwright.chromium.executable_path).is_file()
            except Exception:
                binary_available = False
        if tool_id == "log-canary-tests":
            binary_available = True
        status = (
            "available" if spec["kind"] == "static" and binary_available else
            "blocked_tool_not_installed" if spec["kind"] == "static" else
            "requires_gated_execution" if spec["kind"] == "conditional" else
            "available" if tool_id == "structured-log-policy" else
            "available" if tool_id == "log-canary-tests" else
            "blocked_application_instrumentation_required"
        )
        items.append({
            "id": tool_id,
            "name": spec["name"],
            "stage": spec["stage"],
            "license": spec["license"],
            "status": status,
            "binary_available": binary_available,
            "binary": binary,
            "execution_kind": spec["kind"],
        })
    return items


def _clean_path(raw_path, root):
    try:
        candidate = Path(raw_path)
        path = (candidate if candidate.is_absolute() else root / candidate).resolve()
        return path.relative_to(root).as_posix()[:300]
    except (OSError, ValueError, TypeError):
        return None


def _normalized_findings(tool_id, raw_output, root):
    """Keep actionable identifiers and locations, never source or secret values."""
    try:
        payload = json.loads(raw_output)
    except (TypeError, ValueError):
        return []
    findings = []
    if tool_id == "semgrep-ce" and isinstance(payload, dict):
        for item in payload.get("results", [])[:100]:
            extra, start = item.get("extra", {}), item.get("start", {})
            findings.append({"rule_id": item.get("check_id"), "path": _clean_path(item.get("path"), root),
                             "line": start.get("line"), "severity": extra.get("severity"),
                             "summary": "Static security rule matched; review the rule and source location."})
    elif tool_id == "gitleaks" and isinstance(payload, list):
        for item in payload[:100]:
            findings.append({"rule_id": item.get("RuleID"), "path": _clean_path(item.get("File"), root),
                             "line": item.get("StartLine"), "severity": "high",
                             "summary": "Potential secret pattern detected; secret value discarded."})
    elif tool_id == "trivy" and isinstance(payload, dict):
        for result in payload.get("Results", []):
            path = _clean_path(result.get("Target"), root)
            for item in (result.get("Vulnerabilities") or [])[:100]:
                findings.append({"rule_id": item.get("VulnerabilityID"), "path": path,
                                 "severity": item.get("Severity"), "component": item.get("PkgName"),
                                 "installed_version": item.get("InstalledVersion"),
                                 "summary": str(item.get("Title") or "Dependency vulnerability")[:300]})
            for item in (result.get("Misconfigurations") or [])[:100]:
                findings.append({"rule_id": item.get("ID"), "path": path,
                                 "severity": item.get("Severity"),
                                 "line": (item.get("CauseMetadata") or {}).get("StartLine"),
                                 "summary": str(item.get("Title") or "Configuration finding")[:300]})
            for item in (result.get("Secrets") or [])[:100]:
                findings.append({"rule_id": item.get("RuleID"), "path": path,
                                 "severity": item.get("Severity"),
                                 "line": item.get("StartLine"),
                                 "summary": "Potential secret pattern detected; matched value discarded."})
    elif tool_id == "native-quality-tools" and isinstance(payload, list):
        for item in payload[:100]:
            findings.append({"rule_id": item.get("code"), "path": _clean_path(item.get("filename"), root),
                             "line": (item.get("location") or {}).get("row"),
                             "severity": "warning", "summary": "Lint rule matched; review the rule and source location."})
    return findings[:100]


def _run(tool_id, argv, cwd, timeout=MAX_COMMAND_SECONDS):
    """Run a fixed argv with a bounded timeout and bounded, hashed output."""
    started = time.monotonic()
    report_directory = None
    try:
        if tool_id == 'gitleaks':
            report_directory = tempfile.TemporaryDirectory(prefix='governance-gitleaks-')
            report_path = Path(report_directory.name) / 'report.json'
            argv = [*argv, '--report-path', str(report_path)]
        proc = subprocess.run(
            argv, cwd=str(cwd), stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=timeout, check=False,
            env={key: value for key, value in os.environ.items()
                 if key in {"PATH", "HOME", "TMPDIR", "TEMP", "SYSTEMROOT", "WINDIR", "LANG", "LC_ALL", "XDG_CACHE_HOME"}}
                | {"GIT_TERMINAL_PROMPT": "0", "NO_COLOR": "1", "SEMGREP_SEND_METRICS": "off"},
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        if report_directory and report_path.is_file():
            stdout = report_path.read_text(encoding='utf-8')
        # Scanner output can contain source fragments or credentials. Persist only
        # a digest and a bounded finding count, never raw tool output.
        finding_count = None
        findings = _normalized_findings(tool_id, stdout, Path(cwd).resolve())
        parsed = None
        try:
            parsed = json.loads(stdout)
            if isinstance(parsed, list):
                finding_count = len(parsed)
            elif isinstance(parsed, dict):
                if tool_id == 'trivy' and 'Results' in parsed:
                    finding_count = sum(len(result.get(key) or []) for result in parsed.get('Results', [])
                        for key in ('Vulnerabilities', 'Misconfigurations', 'Secrets'))
                for key in ("results", "leaks", "matches", "vulnerabilities"):
                    if isinstance(parsed.get(key), list):
                        finding_count = len(parsed[key])
                        break
        except (TypeError, ValueError):
            pass
        accepted_exit = proc.returncode in ((0,) if tool_id == 'trivy' else (0, 1))
        parsed_output = finding_count is not None
        success = accepted_exit and parsed_output and not (isinstance(parsed, dict) and parsed.get('errors'))
        return {
            "status": ('completed_with_findings' if finding_count else 'completed') if success else 'tool_error',
            'executed': True, 'findings_truncated': bool(finding_count and finding_count > len(findings)),
            'retained_finding_count': len(findings), 'structured_output_parsed': parsed_output,
            "exit_code": proc.returncode,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "output_sha256": hashlib.sha256((stdout + "\n" + stderr).encode()).hexdigest(),
            "finding_count": finding_count,
            "findings": findings,
        }
    except subprocess.TimeoutExpired:
        return {"status": "timed_out", 'executed': True, "duration_ms": round((time.monotonic() - started) * 1000)}
    except OSError as exc:
        return {"status": "runner_error", "error_type": type(exc).__name__}
    finally:
        if report_directory:
            report_directory.cleanup()


def _version(binary):
    try:
        proc = subprocess.run([binary, '--version'], capture_output=True, text=True,
                              timeout=5, check=False, stdin=subprocess.DEVNULL,
                              env={key: value for key, value in os.environ.items()
                                   if key in {'PATH', 'HOME', 'TEMP', 'TMPDIR', 'SYSTEMROOT', 'WINDIR', 'LANG'}})
        match = re.search(r'(?<!\d)\d+\.\d+(?:\.\d+)?(?:[-+][a-zA-Z0-9.]+)?', proc.stdout or '')
        return match.group(0) if proc.returncode == 0 and match else 'not_reported'
    except (OSError, subprocess.TimeoutExpired):
        return 'unavailable'


def run_repository_static_tools(repository_path):
    """Run only fixed, non-project-script static commands on a cloned tree."""
    root = Path(repository_path).resolve()
    if not root.is_dir():
        raise ValueError("repository_path must be an existing directory")
    results = []
    commands = [
        ("semgrep-ce", ["semgrep", "scan", "--config", str(Path(__file__).parent / "tooling_rules" / "semgrep.yml"), "--json", "--metrics", "off", "--timeout", "30", str(root)]),
        ("gitleaks", ["gitleaks", "detect", "--no-git", "--source", str(root), "--redact", "--report-format", "json"]),
        ("trivy", ["trivy", "fs", "--skip-java-db-update", "--scanners", "vuln,misconfig,secret", "--format", "json", "--timeout", "60s", str(root)]),
    ]
    for tool_id, argv in commands:
        spec = TOOL_SPECS[tool_id]
        if not shutil.which(spec["binary"]):
            results.append({"tool_id": tool_id, "name": spec["name"], "status": "blocked_tool_not_installed"})
            continue
        result = {"tool_id": tool_id, "name": spec["name"], 'version': _version(spec['binary']), **_run(tool_id, argv, root)}
        if tool_id == 'semgrep-ce':
            result['ruleset_sha256'] = hashlib.sha256((Path(__file__).parent / 'tooling_rules' / 'semgrep.yml').read_bytes()).hexdigest()
        if tool_id == 'trivy':
            result['database_revision'] = 'not_reported_by_adapter'
        results.append(result)

    py_files = list(root.rglob("*.py"))
    if py_files and shutil.which("ruff"):
        results.append({"tool_id": "native-quality-tools", "name": TOOL_SPECS["native-quality-tools"]["name"],
                        'version': _version('ruff'),
                        **_run("native-quality-tools", ["ruff", "check", "--output-format", "json", str(root)], root)})
    elif py_files:
        results.append({"tool_id": "native-quality-tools", "name": TOOL_SPECS["native-quality-tools"]["name"],
                        "status": "blocked_tool_not_installed"})
    else:
        results.append({"tool_id": "native-quality-tools", "name": TOOL_SPECS["native-quality-tools"]["name"],
                        "status": "not_applicable_no_python_source"})

    # These frameworks execute application-authored code or send traffic. Merely
    # finding a config file is not evidence of execution; require their own gated
    # target/test-runner adapters before reporting a run.
    result_files = [p.name.lower() for p in root.iterdir()] if root.exists() else []
    has_openapi = any("openapi" in name or "swagger" in name for name in result_files)
    for tool_id, prerequisite in [
        ("playwright", "approved browser test suite and isolated browser runner"),
        ("schemathesis", "OpenAPI contract, authorized test target, and bounded request budget" if has_openapi else "OpenAPI contract and authorized test target"),
        ("hypothesis", "reviewed property tests and isolated test runner"),
        ("k6", "approved target, workload ceiling, duration, and SLO thresholds"),
    ]:
        results.append({"tool_id": tool_id, "name": TOOL_SPECS[tool_id]["name"],
                        "status": "blocked_prerequisite_required", "required_prerequisite": prerequisite,
                        "executed": False})
    from safe_logging import run_log_canary_test
    results.extend([
        {"tool_id": "structured-log-policy", "name": TOOL_SPECS["structured-log-policy"]["name"],
         "status": "enforced_in_studio_backend", "executed": True,
         "note": "Studio backend emits allow-listed JSON fields and applies pattern-based redaction to rendered messages."},
        {"tool_id": "log-canary-tests", "name": TOOL_SPECS["log-canary-tests"]["name"],
         **run_log_canary_test(), "executed": True,
         "note": "Synthetic canary verifies the Studio backend logging filter; it does not instrument the assessed application."},
    ])
    return results


def _assessment_argv(framework, target_url, *, openapi_url=None, max_examples=10,
                     virtual_users=2, duration_seconds=15, workdir=None):
    """Build fixed, bounded commands. Exposed separately for auditable tests."""
    if framework == "schemathesis":
        return ["schemathesis", "run", openapi_url, "--url", target_url,
                "--max-examples", str(max_examples), "--workers", "1",
                "--seed", "20261021", "--max-time", "30",
                "--request-timeout", "5", "--request-retries", "0",
                "--max-redirects", "0", "--rate-limit", "1/s",
                "--max-failures", "10"]
    if framework == "k6":
        return ["k6", "run", "--vus", str(virtual_users),
                "--duration", f"{duration_seconds}s", "--summary-export",
                str(Path(workdir) / "k6-summary.json"), str(Path(workdir) / "k6-smoke.js")]
    if framework == "playwright":
        return ["python", "-c", _PLAYWRIGHT_SMOKE, target_url]
    raise ValueError("unsupported framework")


_PLAYWRIGHT_SMOKE = r'''import asyncio, json, sys
from urllib.parse import urlsplit
from playwright.async_api import async_playwright
async def main():
 target=sys.argv[1]; base=urlsplit(target); target_port=base.port or 443; errors=[]; statuses=[]; request_count=[0]
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True)
  context=await browser.new_context()
  async def guard(route):
   u=urlsplit(route.request.url)
   request_port=u.port or (443 if u.scheme == 'https' else 80)
   root=base.path.rstrip('/') or '/'
   request_count[0]+=1
   if request_count[0] > 30 or route.request.resource_type in ('image','font','media') or u.scheme != 'https' or u.hostname != base.hostname or request_port != target_port or (root != '/' and not (u.path == root or u.path.startswith(root + '/'))):
    await route.abort()
   else: await route.continue_()
  await context.route('**/*', guard)
  page=await context.new_page(); page.on('pageerror', lambda e: errors.append(type(e).__name__))
  response=await page.goto(target, wait_until='domcontentloaded', timeout=15000)
  statuses.append(response.status if response else 0)
  await browser.close()
 print(json.dumps({'http_statuses':statuses,'page_error_count':len(errors),'requests_observed':request_count[0]}))
asyncio.run(main())
'''


def _k6_smoke_script(target_url, max_p95_ms=1000, max_error_rate_percent=1.0):
    error_fraction = float(max_error_rate_percent) / 100
    return ("import http from 'k6/http'; import { sleep } from 'k6';\n"
            + f"export const options = {{ thresholds: {{ http_req_duration: ['p(95)<{int(max_p95_ms)}'], http_req_failed: ['rate<{error_fraction}'] }} }};\n"
            + "export default function(){ let r=http.get(" + json.dumps(target_url) + ", { redirects: 0, tags: { name: 'authorized_smoke_get' } }); if(r.status >= 500) throw new Error('server_error'); sleep(1); }\n")


def execute_framework_assessment(framework, target_url, *, openapi_url=None,
                                 max_examples=10, virtual_users=2, duration_seconds=15,
                                 max_p95_ms=1000, max_error_rate_percent=1.0,
                                 timeout_seconds=75):
    """Run a narrowly bounded target smoke/contract/load test and retain no raw output."""
    binaries = {"playwright": "python", "schemathesis": "schemathesis", "k6": "k6"}
    binary = binaries.get(framework)
    if not binary or not shutil.which(binary):
        return {"status": "blocked_tool_not_installed", "framework": framework}
    if framework == "playwright":
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                if not Path(p.chromium.executable_path).exists():
                    return {"status": "blocked_browser_not_installed", "framework": framework}
        except Exception:
            return {"status": "blocked_browser_not_installed", "framework": framework}
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="studio-assessment-") as temp:
            if framework == "k6":
                # GET-only, no auth, no redirects, one-second pacing and low VU cap.
                script = _k6_smoke_script(target_url, max_p95_ms, max_error_rate_percent)
                Path(temp, "k6-smoke.js").write_text(script, encoding="utf-8")
            argv = _assessment_argv(framework, target_url, openapi_url=openapi_url,
                                   max_examples=max_examples, virtual_users=virtual_users,
                                   duration_seconds=duration_seconds, workdir=temp)
            proc = subprocess.run(argv, cwd=temp, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=max(1, min(75, int(timeout_seconds))), check=False,
                                  env={k: v for k, v in os.environ.items() if k in {
                                      "PATH", "HOME", "TMPDIR", "TEMP", "SYSTEMROOT", "WINDIR",
                                      "LANG", "LC_ALL", "PLAYWRIGHT_BROWSERS_PATH", "XDG_CACHE_HOME"}} |
                                      {"NO_COLOR": "1", "GIT_TERMINAL_PROMPT": "0"})
            stdout, stderr = proc.stdout or "", proc.stderr or ""
            result = {"status": "completed" if proc.returncode == 0 else "completed_with_failures",
                      "framework": framework, "exit_code": proc.returncode,
                      "duration_ms": round((time.monotonic() - started) * 1000),
                      "output_sha256": hashlib.sha256((stdout + "\n" + stderr).encode()).hexdigest(),
                      "raw_output_retained": False}
            if framework == "playwright":
                try:
                    smoke = json.loads(stdout.strip().splitlines()[-1])
                    result.update({"http_statuses": smoke.get("http_statuses", [])[:3],
                                   "page_error_count": min(int(smoke.get("page_error_count", 0)), 100),
                                   "requests_observed": min(int(smoke.get("requests_observed", 0)), 31)})
                except (ValueError, IndexError, TypeError):
                    result["status"] = "tool_error"
            if framework == "k6":
                try:
                    summary = json.loads(Path(temp, "k6-summary.json").read_text(encoding="utf-8"))
                    metrics = summary.get("metrics", {})
                    result["metrics"] = {key: metrics[key].get("values", {}) for key in
                        ("http_req_duration", "http_req_failed", "http_reqs") if key in metrics}
                except (OSError, ValueError, TypeError):
                    result["status"] = "tool_error"
            result["hypothesis"] = "Schemathesis uses Hypothesis-based generated cases" if framework == "schemathesis" else None
            return result
    except subprocess.TimeoutExpired:
        return {"status": "timed_out", "framework": framework,
                "duration_ms": round((time.monotonic() - started) * 1000)}
    except OSError as exc:
        return {"status": "runner_error", "framework": framework, "error_type": type(exc).__name__}

