"""Deterministic intake transforms used by Governance Studio."""
import hashlib
import re

from detectors import mask_sensitive_text


def sha256_text(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest() if text else None


def extract_candidate_requirements(text):
    """Extract candidate requirement lines; this is a draft, not an approved baseline."""
    candidates = []
    for line_no, raw in enumerate((text or "").splitlines(), start=1):
        line = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", raw).strip()
        if not line or len(line) < 12:
            continue
        if re.search(r"\b(shall|must|required to|user story|acceptance criteria)\b", line, re.I) or re.match(r"(?:FR|NFR|REQ|US)[-_ ]?\d+\b", line, re.I):
            line = line[:600]
            line, _ = mask_sensitive_text(line)
            explicit_id = re.match(r"((?:FR|NFR|REQ|US)[-_ ]?\d+)\b", line, re.I)
            candidates.append({
                "id": explicit_id.group(1).replace(" ", "-").upper() if explicit_id else f"FRS-L{line_no}",
                "source_line": line_no,
                "text": line,
                "text_sha256": sha256_text(line),
                "trace_status": "candidate_unreviewed",
            })
        if len(candidates) >= 300:
            break
    return candidates


def summarize_runtime_logs(text):
    if not text:
        return None
    lines = text.splitlines()
    return {
        "line_count": len(lines),
        "error_lines": sum(bool(re.search(r"\b(error|exception|fatal|panic)\b", line, re.I)) for line in lines),
        "http_5xx_lines": sum(bool(re.search(r"\b5\d\d\b", line)) for line in lines),
        "http_4xx_lines": sum(bool(re.search(r"\b4\d\d\b", line)) for line in lines),
        "security_signal_lines": sum(bool(re.search(r"(unauthori[sz]ed|access denied|injection|csrf|xss|permission denied|secret detected)", line, re.I)) for line in lines),
        "content_sha256": sha256_text(text),
        "raw_log_content_retained": False,
        "method": "deterministic keyword and status-code counts; not a log security verdict",
    }


def build_run_plan(has_repo, has_frs, has_target, has_logs, authorized):
    return [
        {"id": "SCOPE-01", "stage": "Governance", "activity": "Validate approved scope and exclusions", "executor": "deterministic_policy", "state": "ready" if (not has_target or authorized) else "authorization_required", "evidence": "authorization and scope record", "human_gate": True},
        {"id": "REQ-01", "stage": "Requirements", "activity": "Extract candidate functional requirements and trace source lines", "executor": "deterministic_parser", "state": "ready" if has_frs else "blocked_missing_input", "evidence": "candidate requirement IDs, source lines and hashes", "human_gate": True},
        {"id": "SEC-01", "stage": "Security", "activity": "Run repository secret, PII, logging and static-pattern checks", "executor": "existing_repository_audit", "state": "planned_execution_available" if has_repo else "blocked_missing_input", "evidence": "repository audit findings and ledger references", "human_gate": True},
        {"id": "TEST-01", "stage": "Verification", "activity": "Map requirements to existing test evidence and identify untested requirements", "executor": "deterministic_traceability", "state": "planned_requires_repository_test_execution", "evidence": "requirement-to-test coverage gaps", "human_gate": True},
        {"id": "RUNTIME-01", "stage": "Runtime", "activity": "Summarize supplied runtime log signals", "executor": "deterministic_log_summary", "state": "ready" if has_logs else "blocked_missing_input", "evidence": "counts and content hash; raw logs are not retained", "human_gate": True},
        {"id": "WEB-01", "stage": "Web Security", "activity": "Assess web attack surface within approved target boundary", "executor": "approved_scanner_adapter_required", "state": "not_executed_no_scanner_adapter", "evidence": "must include exact target, tool/ruleset versions and approved run window", "human_gate": True},
        {"id": "PERF-01", "stage": "Performance", "activity": "Run bounded workload against an approved non-production target", "executor": "approved_load_test_adapter_required", "state": "not_executed_requires_test_environment_and_limits", "evidence": "workload profile, rate ceiling, latency/error percentiles", "human_gate": True},
        {"id": "CMMI-01", "stage": "Evidence", "activity": "Project evidence and traceability readiness review", "executor": "evidence_projection", "state": "advisory_readiness_only", "evidence": "artifact register, trace matrix, approvals and provenance", "human_gate": True},
    ]
