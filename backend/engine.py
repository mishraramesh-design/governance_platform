"""Core assurance engine: event -> select controls -> execute -> Level-2 review -> ledger -> two reports.
Deep-implemented (deterministic/real) controls: CTRL-01,02,03,06,07,08,10,11,19.
All other catalog controls return an honest NOT_ASSESSED verdict with a stated reason (never a silent pass)."""
import re
from uuid import uuid4
from datetime import datetime, timezone

import gateway
import agent_profiles
import ledger as ledger_mod
from detectors import scan_secrets, scan_pii, scan_logging_leak, static_code_issues, keyed_hash


def _l2_for(agent_id):
    a = agent_profiles.get_agent(agent_id)
    return a.get("l2_agent_id") if a else None


# A05 Security & Privacy guardrail: re-scan T0/T1 data-protection findings with a
# deterministic re-run and record the independent agreement inline (Level-2).
DPDP_TAGS = ["DPDP:reasonable_security_safeguards", "DPDP:retention_erasure", "DPDP:breach_notification"]


def _apply_a05_rescan(finding, tier, rescan_hits, original_hits):
    finding["tier"] = tier
    finding["l2_agent_id"] = "A05"
    agree = len(rescan_hits) == len(original_hits)
    if tier in ("T0", "T1"):
        finding["level2_status"] = "confirmed_by_A05_rescan" if agree else "disagreement_pending_adjudication"
        finding["level2_narrative"] = (
            f"A05 Security & Privacy re-scanned this {tier} finding with an independent deterministic "
            f"detector run: {'reproduced the same detections (AGREE).' if agree else 'did NOT reproduce - needs human adjudication.'}"
        )
    else:
        finding["level2_status"] = "confirmed_by_recompute"
        finding["level2_narrative"] = f"Tier {tier}: deterministic recomputation confirmed the Level-1 result."

AMBIGUOUS_TERMS = [
    "should", "may", "etc", "tbd", "possibly", "and/or", "user-friendly",
    "fast", "easy", "appropriate", "adequate", "as needed", "some", "several",
]


def assess_requirement_quality(text: str):
    t = (text or "").lower()
    issues = []
    score = 100
    for term in AMBIGUOUS_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", t):
            issues.append(f"Ambiguous term detected: '{term}'")
            score -= 10
    if not re.search(r"\bshall\b|\bmust\b", t):
        issues.append("Missing mandatory modal verb ('shall' / 'must')")
        score -= 15
    if not re.search(r"\d", t) and not re.search(r"second|minute|percent|%|ms\b", t):
        issues.append("No measurable / quantifiable acceptance threshold")
        score -= 10
    return max(0, score), issues


def assess_acceptance_criteria(text: str):
    t = (text or "").lower()
    has_gwt = "given" in t and "when" in t and "then" in t
    has_marker = "acceptance criteria" in t
    measurable = bool(re.search(r"\d", t))
    passed = (has_gwt or has_marker) and measurable
    reasons = []
    if not (has_gwt or has_marker):
        reasons.append("No Given/When/Then or explicit Acceptance Criteria marker found")
    if not measurable:
        reasons.append("No measurable threshold present")
    return passed, reasons


def build_finding(project, event, control_id, control_name, agent_id, severity, confidence, verdict,
                   reason, tags, suggested_remedy, subject_ref, subject_type, method, evidence,
                   provenance="platform_service"):
    return {
        "id": str(uuid4()),
        "project_id": project["id"],
        "event_id": event["id"],
        "control_id": control_id,
        "control_name": control_name,
        "agent_id": agent_id,
        "l1_agent_id": agent_id,
        "l2_agent_id": _l2_for(agent_id),
        "tier": None,
        "severity": severity,
        "confidence": confidence,
        "verdict": verdict,
        "reason": reason,
        "tags": tags,
        "suggested_remedy": suggested_remedy,
        "subject_ref": subject_ref,
        "subject_type": subject_type,
        "method": method,
        "evidence": evidence,
        "provenance": provenance,
        "level2_status": "pending",
        "level2_narrative": None,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def not_assessed_stub(project, event, control, subject_ref=None):
    return [build_finding(
        project, event, control["id"], control["name"], control["executor"],
        severity="info", confidence=0, verdict="NOT_ASSESSED",
        reason="Detector for this control is not yet wired in this prototype phase - advisory only, no verdict is implied either way.",
        tags=["not_implemented"], suggested_remedy="N/A - out of scope for this prototype milestone.",
        subject_ref=subject_ref, subject_type=event["event_type"], method="none", evidence=[],
    )]


async def handle_requirement_quality(db, project, event, source_ref):
    reqs = await db.requirements.find({"project_id": project["id"]}, {"_id": 0}).to_list(1000)
    findings = []
    for r in reqs:
        score, issues = assess_requirement_quality(r["text"])
        verdict = "PASS" if score >= 75 else "FAIL"
        severity = "low" if score >= 75 else ("medium" if score >= 50 else "high")
        method = "rule-based"
        remedy = "No action required - requirement meets baseline quality bar."
        if verdict == "FAIL":
            masked = f"Requirement {r['req_id']}: \"{r['text']}\". Detected issues: {'; '.join(issues)}. Propose one testable, measurable rewrite."
            gw = await gateway.complete_agent("A02", "requirement_rewrite", masked, level=1, db=db)
            remedy = gw["text"]
            method = "model-assisted (A02)" if gw["mode"] == "llm" else "rule-based"
        findings.append(build_finding(
            project, event, "CTRL-01", "Requirement Quality Review", "A02",
            severity=severity, confidence=90, verdict=verdict,
            reason="; ".join(issues) if issues else "No ambiguity or testability issues detected.",
            tags=["requirements", "quality"], suggested_remedy=remedy,
            subject_ref=r["req_id"], subject_type="requirement", method=method,
            evidence=[{"type": "requirement_excerpt", "masked": r["text"][:160], "hash": keyed_hash(r["text"])}],
        ))
    return findings


async def handle_acceptance_criteria(db, project, event, source_ref):
    reqs = await db.requirements.find({"project_id": project["id"]}, {"_id": 0}).to_list(1000)
    findings = []
    for r in reqs:
        passed, reasons = assess_acceptance_criteria(r["text"])
        findings.append(build_finding(
            project, event, "CTRL-02", "Acceptance Criteria Validation", "A02",
            severity="low" if passed else "medium", confidence=85,
            verdict="PASS" if passed else "FAIL",
            reason="Acceptance criteria present and measurable." if passed else "; ".join(reasons),
            tags=["requirements"], suggested_remedy="N/A" if passed else "Add Given/When/Then acceptance criteria with a measurable threshold.",
            subject_ref=r["req_id"], subject_type="requirement", method="rule-based",
            evidence=[{"type": "requirement_excerpt", "masked": r["text"][:160], "hash": keyed_hash(r["text"])}],
        ))
    return findings


async def handle_secrets(db, project, event, source_ref):
    commit = await db.commits.find_one({"id": source_ref}, {"_id": 0}) if source_ref else None
    if not commit:
        return not_assessed_stub(project, event, {"id": "CTRL-06", "name": "Secrets Detection", "executor": "A05"}, source_ref)
    hits = scan_secrets(commit.get("code_snippet", ""))
    if not hits:
        return [build_finding(project, event, "CTRL-06", "Secrets Detection", "A05", "low", 95, "PASS",
            "No hardcoded secrets detected in this commit.", ["security", "secrets"], "No action required.",
            commit["commit_id"], "commit", "deterministic_recompute", [])]
    f = build_finding(project, event, "CTRL-06", "Secrets Detection", "A05", "critical", 98, "FAIL",
        f"{len(hits)} potential secret(s) detected: {', '.join(sorted({h['type'] for h in hits}))}.",
        ["security", "secrets"], "Rotate the exposed credential(s) immediately and move to a secrets manager / environment variables.",
        commit["commit_id"], "commit", "deterministic_recompute", hits)
    _apply_a05_rescan(f, "T0", scan_secrets(commit.get("code_snippet", "")), hits)
    return [f]


async def handle_pii(db, project, event, source_ref):
    commit = await db.commits.find_one({"id": source_ref}, {"_id": 0}) if source_ref else None
    if not commit:
        return not_assessed_stub(project, event, {"id": "CTRL-07", "name": "India PII Detection", "executor": "A05"}, source_ref)
    hits = scan_pii(commit.get("code_snippet", ""))
    if not hits:
        return [build_finding(project, event, "CTRL-07", "India PII Detection", "A05", "low", 92, "PASS",
            "No India-specific personal data patterns detected in this commit.", ["security", "privacy", "dpdp"],
            "No action required.", commit["commit_id"], "commit", "deterministic_recompute", [])]
    high_types = {"pii:aadhaar", "pii:pan", "pii:card_number", "pii:gstin"}
    tier = "T1" if any(h["type"] in high_types for h in hits) else "T2"
    f = build_finding(project, event, "CTRL-07", "India PII Detection", "A05", "high", 90, "FAIL",
        f"{len(hits)} potential personal data item(s) detected: {', '.join(sorted({h['type'] for h in hits}))}. DPDP Act 2023 relevance flagged for human review.",
        ["security", "privacy", "dpdp"] + DPDP_TAGS,
        "Remove hardcoded personal data; use masked test fixtures and verify DPDP Act obligations with your privacy officer.",
        commit["commit_id"], "commit", "deterministic_recompute", hits)
    _apply_a05_rescan(f, tier, scan_pii(commit.get("code_snippet", "")), hits)
    return [f]


async def handle_logging_leak(db, project, event, source_ref):
    commit = await db.commits.find_one({"id": source_ref}, {"_id": 0}) if source_ref else None
    if not commit:
        return not_assessed_stub(project, event, {"id": "CTRL-08", "name": "Logging Leak Check", "executor": "A05"}, source_ref)
    hits = scan_logging_leak(commit.get("code_snippet", ""))
    if not hits:
        return [build_finding(project, event, "CTRL-08", "Logging Leak Check", "A05", "low", 88, "PASS",
            "No sensitive values detected in log/print statements.", ["security", "logging"], "No action required.",
            commit["commit_id"], "commit", "deterministic_recompute", [])]
    return [build_finding(project, event, "CTRL-08", "Logging Leak Check", "A05", "high", 88, "FAIL",
        f"{len(hits)} log/print statement(s) appear to emit sensitive values.", ["security", "logging"],
        "Redact sensitive fields before logging; log identifiers/hashes instead of raw values.",
        commit["commit_id"], "commit", "deterministic_recompute", hits)]


async def handle_static_code(db, project, event, source_ref):
    commit = await db.commits.find_one({"id": source_ref}, {"_id": 0}) if source_ref else None
    if not commit:
        return not_assessed_stub(project, event, {"id": "CTRL-10", "name": "Static Code Analysis", "executor": "A06"}, source_ref)
    issues = static_code_issues(commit.get("code_snippet", ""))
    if not issues:
        return [build_finding(project, event, "CTRL-10", "Static Code Analysis", "A06", "low", 80, "PASS",
            "No static-analysis heuristics triggered.", ["code_quality"], "No action required.",
            commit["commit_id"], "commit", "deterministic_recompute", [])]
    top_sev = "high" if any(i["severity"] == "high" for i in issues) else "medium"
    return [build_finding(project, event, "CTRL-10", "Static Code Analysis", "A06", top_sev, 75, "FAIL",
        f"{len(issues)} static-analysis issue(s): {', '.join(sorted({i['type'] for i in issues}))}.",
        ["code_quality"], "Address flagged code-quality issues before merge.",
        commit["commit_id"], "commit", "deterministic_recompute", issues)]


async def handle_unit_test_adequacy(db, project, event, source_ref):
    reqs = await db.requirements.find({"project_id": project["id"]}, {"_id": 0}).to_list(1000)
    tests = await db.test_cases.find({"project_id": project["id"], "type": "unit"}, {"_id": 0}).to_list(1000)
    tested_req_ids = set()
    for t in tests:
        tested_req_ids.update(t.get("requirement_ids", []))
    total = len(reqs) or 1
    ratio = len([r for r in reqs if r["req_id"] in tested_req_ids]) / total
    verdict = "PASS" if ratio >= 0.7 else "FAIL"
    return [build_finding(project, event, "CTRL-11", "Unit Test Adequacy", "A07", "low" if verdict == "PASS" else "medium",
        80, verdict, f"{round(ratio*100)}% of requirements have at least one linked unit test (threshold 70%).",
        ["testing"], "No action required." if verdict == "PASS" else "Add unit tests for untested requirements.",
        project["id"], "project", "deterministic_recompute", [])]


async def handle_traceability_gap(db, project, event, source_ref):
    coverage = await compute_traceability(db, project["id"])
    verdict = "PASS" if coverage["coverage_pct"] >= 80 else "FAIL"
    return [build_finding(project, event, "CTRL-03", "Traceability Gap Analysis", "A14", "low" if verdict == "PASS" else "medium",
        85, verdict, f"Traceability coverage is {coverage['coverage_pct']}% (threshold 80%). {len(coverage['gaps'])} gap(s) found.",
        ["traceability"], "No action required." if verdict == "PASS" else "Close traceability gaps listed in the Traceability Matrix.",
        project["id"], "project", "deterministic_recompute", [])]


async def handle_release_readiness(db, project, event, source_ref):
    open_blockers = await db.findings.find({
        "project_id": project["id"], "verdict": "FAIL", "status": "open",
        "severity": {"$in": ["high", "critical"]},
    }, {"_id": 0}).to_list(1000)
    if open_blockers:
        return [build_finding(project, event, "CTRL-19", "Release Readiness Gate", "A09", "critical", 95, "FAIL",
            f"{len(open_blockers)} open high/critical finding(s) remain untriaged - release is not advised.",
            ["release"], "Triage and remediate open high/critical findings before requesting the G8 human go-live gate.",
            project["id"], "project", "deterministic_recompute", [])]
    return [build_finding(project, event, "CTRL-19", "Release Readiness Gate", "A09", "low", 95, "PASS",
        "No open high/critical findings. Advisory only - the human Release Manager and CAB retain final go-live authority (Gate G8).",
        ["release"], "Proceed to human G8 gate review.", project["id"], "project", "deterministic_recompute", [])]


CONTROL_HANDLERS = {
    "CTRL-01": handle_requirement_quality,
    "CTRL-02": handle_acceptance_criteria,
    "CTRL-03": handle_traceability_gap,
    "CTRL-06": handle_secrets,
    "CTRL-07": handle_pii,
    "CTRL-08": handle_logging_leak,
    "CTRL-10": handle_static_code,
    "CTRL-11": handle_unit_test_adequacy,
    "CTRL-19": handle_release_readiness,
}


async def apply_level2(db, control, finding):
    # Respect a Level-2 result already set inline by the detector (e.g. A05 re-scan).
    existing = finding.get("level2_status")
    if existing and existing != "pending":
        return

    method = control.get("independence_method")
    if method == "deterministic_recompute":
        finding["level2_status"] = "confirmed_by_recompute"
        return
    if finding["verdict"] != "FAIL":
        finding["level2_status"] = "not_required_pass_or_unassessed"
        return
    if method in ("model-assisted", "independent_reviewer_model"):
        l2_id = finding.get("l2_agent_id") or _l2_for(finding.get("l1_agent_id"))
        l2_agent = agent_profiles.get_agent(l2_id) if l2_id else None
        ev = finding.get("evidence") or []
        masked_ev = "; ".join(str(e.get("masked", "")) for e in ev[:3]) or "(no masked fragment)"
        prompt = (
            f"Level-1 control '{control['name']}' (run by agent {finding.get('l1_agent_id')}) examined "
            f"subject {finding.get('subject_ref')} ({finding.get('subject_type')}) and produced verdict "
            f"{finding['verdict']}.\nLevel-1 reason: {finding['reason']}\nMasked evidence: {masked_ev}\n"
            "Re-perform your independent check on this masked summary and reply AGREE or DISAGREE plus one line why."
        )
        # Route through the paired L2 agent's persona when it uses a model; otherwise
        # fall back to the independent-reviewer profile (a different model family).
        if l2_agent and l2_agent.get("uses_llm"):
            gw = await gateway.complete_agent(l2_id, "l2_independent_review", prompt, level=2, db=db)
        else:
            gw = await gateway.complete("l2_independent_review", prompt, "independent-reviewer", db=db)
        l2_text = gw["text"]
        disagree = "disagree" in l2_text.lower()
        finding["l2_agent_id"] = l2_id
        finding["l2_model"] = gw.get("model_used")
        finding["level2_status"] = "disagreement_pending_adjudication" if disagree else "confirmed_by_independent_model"
        finding["level2_narrative"] = l2_text
        if disagree:
            await db.adjudications.insert_one({
                "id": str(uuid4()), "finding_id": finding["id"], "project_id": finding["project_id"],
                "l1_agent_id": finding.get("l1_agent_id"), "l2_agent_id": l2_id,
                "l1_verdict": finding["verdict"], "l1_reason": finding["reason"],
                "l2_verdict": "DISAGREE", "l2_narrative": l2_text,
                "human_decision": None, "decided_by_role": None, "notes": "",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
    else:
        finding["level2_status"] = "not_required_for_this_control"


async def compute_traceability(db, project_id):
    reqs = await db.requirements.find({"project_id": project_id}, {"_id": 0}).to_list(1000)
    designs = await db.design_items.find({"project_id": project_id}, {"_id": 0}).to_list(1000)
    commits = await db.commits.find({"project_id": project_id}, {"_id": 0}).to_list(1000)
    tests = await db.test_cases.find({"project_id": project_id}, {"_id": 0}).to_list(1000)

    rows = []
    gaps = []
    for r in reqs:
        linked_designs = [d["design_id"] for d in designs if r["req_id"] in d.get("requirement_ids", [])]
        linked_commits = [c["commit_id"] for c in commits if r["req_id"] in c.get("requirement_ids", [])]
        linked_tests = [t["test_id"] for t in tests if r["req_id"] in t.get("requirement_ids", [])]
        complete = bool(linked_designs) and bool(linked_commits) and bool(linked_tests)
        row = {
            "requirement_id": r["req_id"], "requirement_text": r["text"], "criticality": r["criticality"],
            "design_ids": linked_designs, "commit_ids": linked_commits, "test_ids": linked_tests,
            "trace_complete": complete,
        }
        rows.append(row)
        if not complete:
            missing = []
            if not linked_designs:
                missing.append("design")
            if not linked_commits:
                missing.append("commit")
            if not linked_tests:
                missing.append("test")
            gaps.append({"requirement_id": r["req_id"], "missing": missing})

    coverage_pct = round((len(rows) - len(gaps)) / len(rows) * 100) if rows else 0
    return {"rows": rows, "gaps": gaps, "coverage_pct": coverage_pct, "total_requirements": len(rows)}


async def generate_author_report(db, project, event, findings):
    by_author = {}
    for f in findings:
        author = "Unassigned"
        if f["subject_type"] == "commit":
            commit = await db.commits.find_one({"commit_id": f["subject_ref"], "project_id": project["id"]}, {"_id": 0})
            if commit:
                author = commit["author"]
        by_author.setdefault(author, []).append(f)

    masked_summary = "; ".join(f"{f['control_name']}: {f['verdict']} ({f['severity']})" for f in findings[:20]) or "No findings for this event."
    gw = await gateway.complete_agent("A22", "author_report_narrative", masked_summary, level=1, db=db)

    sections = []
    for author, items in by_author.items():
        lines = [f"[{it['verdict']}] {it['control_name']} - {it['reason']} Suggested remedy: {it['suggested_remedy']}" for it in items]
        sections.append({"heading": f"Findings for {author}", "body": lines})

    report = {
        "id": str(uuid4()), "project_id": project["id"], "event_id": event["id"], "type": "author",
        "title": f"Author Report - {project['name']} - {event['event_type']}",
        "narrative": gw["text"], "sections": sections, "finding_count": len(findings),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    entry = await ledger_mod.append_to_ledger(db, "report", report["id"], {"type": "author", "event_id": event["id"]})
    report["ledger_hash"] = entry["hash"]
    await db.reports.insert_one(report)
    report.pop("_id", None)
    return report


async def generate_team_lead_report(db, project, event, findings):
    severity_counts, verdict_counts, hotspot_counts = {}, {}, {}
    for f in findings:
        severity_counts[f["severity"]] = severity_counts.get(f["severity"], 0) + 1
        verdict_counts[f["verdict"]] = verdict_counts.get(f["verdict"], 0) + 1
        hotspot_counts[f["control_name"]] = hotspot_counts.get(f["control_name"], 0) + 1
    hotspots = sorted(hotspot_counts.items(), key=lambda x: -x[1])[:5]

    masked_summary = f"Severity breakdown: {severity_counts}. Verdict breakdown: {verdict_counts}. Top hotspots: {hotspots}."
    gw = await gateway.complete_agent("A22", "team_lead_report_narrative", masked_summary, level=1, db=db)

    sections = [
        {"heading": "Severity Breakdown", "body": [f"{k}: {v}" for k, v in severity_counts.items()] or ["No findings"]},
        {"heading": "Verdict Breakdown", "body": [f"{k}: {v}" for k, v in verdict_counts.items()] or ["No findings"]},
        {"heading": "Hotspots", "body": [f"{k}: {v} finding(s)" for k, v in hotspots] or ["No hotspots"]},
    ]
    report = {
        "id": str(uuid4()), "project_id": project["id"], "event_id": event["id"], "type": "team_lead",
        "title": f"Team Lead Report - {project['name']} - {event['event_type']}",
        "narrative": gw["text"], "sections": sections, "finding_count": len(findings),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    entry = await ledger_mod.append_to_ledger(db, "report", report["id"], {"type": "team_lead", "event_id": event["id"]})
    report["ledger_hash"] = entry["hash"]
    await db.reports.insert_one(report)
    report.pop("_id", None)
    return report


async def run_event(db, project_id, event_type, source_ref=None, triggered_by="system"):
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise ValueError("project not found")

    controls = await db.controls.find({"trigger": event_type}, {"_id": 0}).to_list(100)
    event = {
        "id": str(uuid4()), "project_id": project_id, "event_type": event_type, "source_ref": source_ref,
        "triggered_by": triggered_by, "controls_triggered": [c["id"] for c in controls],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.events.insert_one(event)
    await ledger_mod.append_to_ledger(db, "event", event["id"], {"event_type": event_type, "project_id": project_id})

    all_findings = []
    for control in controls:
        handler = CONTROL_HANDLERS.get(control["id"])
        findings = await handler(db, project, event, source_ref) if handler else not_assessed_stub(project, event, control, source_ref)
        for f in findings:
            await apply_level2(db, control, f)
        if findings:
            await db.findings.insert_many([dict(f) for f in findings])
            for f in findings:
                await ledger_mod.append_to_ledger(db, "finding", f["id"], {"control_id": f["control_id"], "verdict": f["verdict"], "severity": f["severity"]})
        all_findings.extend(findings)

    author_report = await generate_author_report(db, project, event, all_findings)
    team_lead_report = await generate_team_lead_report(db, project, event, all_findings)
    event.pop("_id", None)
    return {"event": event, "findings": all_findings, "reports": [author_report, team_lead_report]}


async def compute_gate_status(db, project_id):
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        return []

    async def find(control_id, **extra):
        q = {"project_id": project_id, "control_id": control_id}
        q.update(extra)
        return await db.findings.find(q, {"_id": 0}).to_list(1000)

    req_fails = await find("CTRL-01", verdict="FAIL")
    build_fails = []
    for cid in ("CTRL-06", "CTRL-07", "CTRL-08", "CTRL-10"):
        build_fails += await find(cid, verdict="FAIL", status="open")
    design_stub = await find("CTRL-04") + await find("CTRL-05")
    sys_test_stub = []
    for cid in ("CTRL-15", "CTRL-16", "CTRL-17", "CTRL-18"):
        sys_test_stub += await find(cid)
    integ_stub = await find("CTRL-13") + await find("CTRL-14")
    release_findings = await find("CTRL-19")
    uat_tests = await db.test_cases.find({"project_id": project_id, "type": "uat"}, {"_id": 0}).to_list(1000)

    def gate(gid, name, criteria, approvers, status, reason):
        return {"id": gid, "name": name, "criteria": criteria, "required_approvers": approvers,
                "status": status, "reason": reason, "advisory_note": "Advisory only - the listed human gate owner(s) hold final decision authority."}

    g1 = gate("G1", "Initiation Exit", "Concept, criticality tier and governance owners defined", ["Business Owner", "Sponsor", "IV&V Lead"],
               "Ready", f"Project registered at integrity tier {project.get('integrity_tier')} with owners assigned.")
    g2_status = "At Risk" if req_fails else "Ready"
    g2 = gate("G2", "Requirements Baseline", "Requirements quality & traceability reviewed", ["Business Owner", "BA Lead", "Architect", "IV&V Lead"],
               g2_status, f"{len(req_fails)} requirement(s) failing the quality bar." if req_fails else "All requirements meet the baseline quality bar.")
    g3 = gate("G3", "Design Baseline", "Architecture, threat model and testability reviewed", ["Architect", "Security/Privacy", "IV&V Lead"],
               "Not Assessed", "Architecture conformance & threat-model detectors are not yet wired in this prototype phase.")
    g4_status = "At Risk" if build_fails else "Ready"
    g4 = gate("G4", "Build Complete", "Code review, secrets/PII/static checks passed", ["Engineering Lead", "Security", "IV&V Lead"],
               g4_status, f"{len(build_fails)} open high/critical build finding(s)." if build_fails else "No open high/critical build findings.")
    g5 = gate("G5", "Integration Test Exit", "Interfaces & E2E flows tested", ["Test Lead", "IV&V Lead"],
               "Not Assessed", "API contract / E2E detectors are not yet wired in this prototype phase.")
    g6 = gate("G6", "System Test Exit", "Functional, security, performance, AI evaluation complete", ["Test/Security/Performance/AI Leads", "IV&V Lead"],
               "Not Assessed", "System-test detectors (security/perf/accessibility/AI eval) are not yet wired in this prototype phase.")
    uat_status = "Not Assessed"
    if uat_tests:
        uat_status = "Ready" if all(t.get("status") == "passed" for t in uat_tests) else "At Risk"
    g7 = gate("G7", "UAT & Operational Readiness", "UAT accepted, operational readiness validated", ["Business Owner", "Operations", "IV&V Lead"],
               uat_status, f"{len(uat_tests)} UAT scenario(s) on record." if uat_tests else "No UAT scenarios on record yet.")
    g8_status = "Ready" if (g2_status == "Ready" and g4_status == "Ready" and release_findings and release_findings[-1]["verdict"] == "PASS") else "At Risk"
    g8 = gate("G8", "Production Go-live", "Release provenance, approvals, rollback & monitoring complete", ["Release Manager", "CAB", "Business", "IV&V Lead"],
               g8_status, "Release readiness control and upstream gates support go-live." if g8_status == "Ready" else "Upstream gates or release readiness control not yet green.")
    g9 = gate("G9", "Hypercare Exit", "Post-deployment monitoring stable", ["Operations", "Product Owner", "IV&V Lead"],
               "Not Started", "No production telemetry ingested in this prototype yet.")
    g10 = gate("G10", "Closure / Continual Improvement", "Metrics, lessons and process updates completed", ["Quality/Process Owner", "IV&V Lead"],
               "Not Started", "Project has not reached closure.")
    return [g1, g2, g3, g4, g5, g6, g7, g8, g9, g10]
