"""Deterministic intake transforms used by Governance Studio."""
import hashlib
import re

from detectors import mask_sensitive_text, scan_pii, scan_secrets


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
    secret_hits = scan_secrets(text)
    pii_hits = scan_pii(text)
    sensitive_lines = {hit["line"] for hit in [*secret_hits, *pii_hits]}
    return {
        "line_count": len(lines),
        "error_lines": sum(bool(re.search(r"\b(error|exception|fatal|panic)\b", line, re.I)) for line in lines),
        "http_5xx_lines": sum(bool(re.search(r"\b5\d\d\b", line)) for line in lines),
        "http_4xx_lines": sum(bool(re.search(r"\b4\d\d\b", line)) for line in lines),
        "security_signal_lines": sum(bool(re.search(r"(unauthori[sz]ed|access denied|injection|csrf|xss|permission denied|secret detected)", line, re.I)) for line in lines),
        "secret_signal_count": len(secret_hits),
        "pii_signal_count": len(pii_hits),
        "sensitive_line_count": len(sensitive_lines),
        "sensitive_signal_types": sorted({hit["type"] for hit in [*secret_hits, *pii_hits]}),
        "sensitive_data_review": "signals_detected_review_required" if sensitive_lines else "no_known_patterns_detected",
        "content_sha256": sha256_text(text),
        "raw_log_content_retained": False,
        "method": "deterministic keyword, status-code, secret-pattern and PII-pattern counts; not a complete log security verdict",
    }


_NFR_CLASSIFIERS = (
    ("performance", re.compile(r"\b(latency|response time|throughput|requests per second|performance)\b", re.I), "k6"),
    ("scalability", re.compile(r"\b(scal(e|ability)|concurrent users|capacity|load)\b", re.I), "k6"),
    ("availability", re.compile(r"\b(availability|uptime|recovery time|recovery point|resilien|failover)\b", re.I), "k6"),
    ("security", re.compile(r"\b(security|unauthori[sz]ed|access control|encryption|audit log)\b", re.I), "security review"),
)


def draft_test_cases(requirements):
    """Create conservative, trace-linked test outlines; never invent thresholds or results."""
    drafts = []
    for requirement in requirements or []:
        text = requirement.get("text", "")
        category = "functional"
        recommended_runner = "Playwright or Schemathesis; select after interface review"
        rationale = "No interface or assertion oracle was inferred from the requirement alone."
        matched_classification = next((item for item in _NFR_CLASSIFIERS if item[1].search(text)), None)
        if matched_classification:
            category, _, recommended_runner = matched_classification
            rationale = "Confirm a measurable acceptance threshold and representative test environment before execution."
        elif requirement.get("id", "").startswith("NFR"):
            category = "non_functional_unclassified"
            recommended_runner = "Select a deterministic runner after the quality attribute and measurable threshold are approved"
            rationale = "The requirement ID indicates an NFR, but its quality attribute and pass/fail threshold need review."
        lower = text.lower()
        if category == "functional" and re.search(r"\b(api|endpoint|request|response|http|graphql|openapi)\b", lower):
            recommended_runner = "Schemathesis or API test suite; confirm contract availability"
        elif category == "functional" and re.search(r"\b(page|screen|form|button|browser|user interface|ui)\b", lower):
            recommended_runner = "Playwright; confirm a test account and stable test data"
        drafts.append({
            "id": f"TC-{requirement.get('id', 'UNASSIGNED')}",
            "source_requirement_id": requirement.get("id"),
            "source_line": requirement.get("source_line"),
            "category": category,
            "title": f"Verify {requirement.get('id', 'requirement')} ({category})",
            "objective": text,
            "preconditions": ["TBD by requirement owner / test designer"],
            "steps": ["Define representative input and preconditions", "Exercise the behavior described by the linked requirement"],
            "expected_result": "Derive and approve an observable pass/fail oracle from the requirement; do not infer unstated behavior.",
            "recommended_runner": recommended_runner,
            "review_note": rationale,
            "status": "draft_requires_human_review",
            "executed": False,
        })
    return drafts


def framework_catalog():
    """Framework choices for the governed plan; catalog entries are not claims of installation."""
    return [
        {"id": "semgrep-ce", "name": "Semgrep Community Edition", "stage": "code_review", "mode": "local_deterministic", "license": "LGPL-2.1", "status": "candidate_not_integrated", "note": "SAST rule engine; use with existing checks and review its language/rule coverage."},
        {"id": "gitleaks", "name": "Gitleaks", "stage": "secret_scanning", "mode": "local_deterministic", "license": "MIT", "status": "candidate_not_integrated", "note": "Scan repository history and files for committed credentials."},
        {"id": "trivy", "name": "Trivy", "stage": "supply_chain_and_artifacts", "mode": "local_deterministic", "license": "Apache-2.0", "status": "candidate_not_integrated", "note": "Scan dependencies, images, configuration and files for vulnerabilities, misconfiguration and secrets."},
        {"id": "playwright", "name": "Playwright Test", "stage": "ui_functional", "mode": "local_deterministic", "license": "Apache-2.0", "status": "candidate_not_integrated", "note": "Browser functional tests; recorded interactions are drafts that need assertions and maintenance."},
        {"id": "schemathesis", "name": "Schemathesis", "stage": "api_functional_and_robustness", "mode": "local_deterministic", "license": "MIT", "status": "candidate_not_integrated", "note": "Generate bounded API tests from an OpenAPI or GraphQL contract."},
        {"id": "hypothesis", "name": "Hypothesis", "stage": "property_testing", "mode": "local_deterministic", "license": "MPL-2.0", "status": "candidate_not_integrated", "note": "Generate boundary and property-based inputs for Python code."},
        {"id": "k6", "name": "Grafana k6", "stage": "performance_and_scalability", "mode": "local_deterministic", "license": "AGPL-3.0", "status": "candidate_not_integrated", "note": "Bounded smoke, load, stress, spike and soak tests; requires approved environment, workload ceiling and SLO thresholds."},
    ]


def build_run_plan(has_repo, has_frs, has_target, has_logs, authorized):
    return [
        {"id": "SCOPE-01", "stage": "Governance", "activity": "Validate approved scope and exclusions", "executor": "deterministic_policy", "state": "ready" if (not has_target or authorized) else "authorization_required", "evidence": "authorization and scope record", "human_gate": True},
        {"id": "REQ-01", "stage": "Requirements", "activity": "Extract candidate functional requirements and trace source lines", "executor": "deterministic_parser", "state": "ready" if has_frs else "blocked_missing_input", "evidence": "candidate requirement IDs, source lines and hashes", "human_gate": True},
        {"id": "TEST-DRAFT-01", "stage": "Test Design", "activity": "Draft trace-linked functional and non-functional test outlines", "executor": "deterministic_requirement_mapper", "state": "drafts_require_review" if has_frs else "blocked_missing_input", "evidence": "requirement-to-test draft links; no execution or pass verdict", "human_gate": True},
        {"id": "SEC-01", "stage": "Security", "activity": "Run repository secret, PII, logging and static-pattern checks", "executor": "existing_repository_audit", "state": "planned_execution_available" if has_repo else "blocked_missing_input", "evidence": "repository audit findings and ledger references", "human_gate": True},
        {"id": "TEST-01", "stage": "Verification", "activity": "Map requirements to existing test evidence and identify untested requirements", "executor": "deterministic_traceability", "state": "planned_requires_repository_test_execution", "evidence": "requirement-to-test coverage gaps; generated drafts are not execution evidence", "human_gate": True},
        {"id": "RUNTIME-01", "stage": "Runtime", "activity": "Review supplied runtime logs for operational signals and known secret/PII patterns", "executor": "deterministic_log_review", "state": "ready" if has_logs else "blocked_missing_input", "evidence": "signal counts, content hash and review status; raw log content is not retained", "human_gate": True},
        {"id": "WEB-01", "stage": "Web Security", "activity": "Assess web attack surface within approved target boundary", "executor": "approved_scanner_adapter_required", "state": "not_executed_no_scanner_adapter", "evidence": "must include exact target, tool/ruleset versions and approved run window", "human_gate": True},
        {"id": "PERF-01", "stage": "Performance", "activity": "Run bounded workload against an approved non-production target", "executor": "approved_load_test_adapter_required", "state": "not_executed_requires_test_environment_and_limits", "evidence": "workload profile, rate ceiling, latency/error percentiles", "human_gate": True},
        {"id": "CMMI-01", "stage": "Evidence", "activity": "Project evidence and traceability readiness review", "executor": "evidence_projection", "state": "advisory_readiness_only", "evidence": "artifact register, trace matrix, approvals and provenance", "human_gate": True},
    ]
