"""Static catalogs (agents, controls, AI-governance controls, edge clients) and seed/demo data generator."""
from uuid import uuid4
from datetime import datetime, timezone

import engine
import gateway

AGENTS = [
    {"id": "A01", "name": "IV&V Orchestrator", "level": "L1/L2", "sdlc_stage": "Cross-cutting",
     "skill_set": "Programme governance, planning, risk, decision analysis", "description": "Owns the overall IV&V charter, plan, monitor & control, and decision analysis & resolution across the lifecycle."},
    {"id": "A02", "name": "Requirements Quality Agent", "level": "L1", "sdlc_stage": "Requirements",
     "skill_set": "Requirements engineering, ambiguity/testability analysis", "description": "Reviews requirement quality, acceptance criteria and NFR testability."},
    {"id": "A03", "name": "Business Analysis & Stakeholder Agent", "level": "L1", "sdlc_stage": "Requirements",
     "skill_set": "Stakeholder analysis, business case validation", "description": "Validates business case context, stakeholder coverage and conflicting requirements."},
    {"id": "A04", "name": "Architecture & Design Agent", "level": "L1/L2", "sdlc_stage": "Design",
     "skill_set": "Solution architecture, design review, trade studies", "description": "Reviews architecture conformance, detailed design and testability of the design."},
    {"id": "A05", "name": "Security & Privacy Agent", "level": "L1/L2", "sdlc_stage": "Coding / Build",
     "skill_set": "AppSec, data privacy, threat modelling, DPDP/India PII", "description": "Runs secrets, PII and logging-leak detectors; reviews threat models and security testing."},
    {"id": "A06", "name": "Code Quality Agent", "level": "L1", "sdlc_stage": "Coding / Build",
     "skill_set": "Static analysis, SBOM, coding standards", "description": "Runs static code analysis and software composition / SBOM checks."},
    {"id": "A07", "name": "Test Design Agent", "level": "L1", "sdlc_stage": "Coding / Build",
     "skill_set": "Test strategy, unit test adequacy", "description": "Assesses unit test adequacy and overall test design coverage."},
    {"id": "A08", "name": "Test Execution Agent", "level": "L1", "sdlc_stage": "Integration / System Testing",
     "skill_set": "Integration & system test execution, defect analysis", "description": "Verifies API contracts, E2E flows, performance and accessibility testing."},
    {"id": "A09", "name": "Release & Continuity Agent", "level": "L1", "sdlc_stage": "Release",
     "skill_set": "Release management, rollback rehearsal, continuity", "description": "Runs the release readiness gate check and continuity/rollback verification."},
    {"id": "A10", "name": "Data Management Agent", "level": "L1", "sdlc_stage": "Design",
     "skill_set": "Data governance, data quality, lineage", "description": "Reviews data model, migration and data-quality controls."},
    {"id": "A11", "name": "Configuration Management Agent", "level": "L1", "sdlc_stage": "Coding / Build",
     "skill_set": "Build integrity, CM baselines", "description": "Verifies build integrity, reproducibility and configuration baselines."},
    {"id": "A12", "name": "UAT Validation Agent", "level": "L1/L2", "sdlc_stage": "UAT",
     "skill_set": "Acceptance testing, operational readiness", "description": "Independently witnesses UAT and validates operational readiness."},
    {"id": "A13", "name": "Production Verification & Incident Agent", "level": "L1/L2", "sdlc_stage": "Production",
     "skill_set": "Post-deployment verification, incident/RCA", "description": "Verifies post-deployment behaviour and analyses runtime logs for security/perf/quality issues."},
    {"id": "A14", "name": "Traceability Agent", "level": "L1", "sdlc_stage": "Requirements",
     "skill_set": "Bidirectional traceability, coverage analysis", "description": "Builds the requirement-design-commit-test trace graph and computes coverage / gaps."},
    {"id": "A15", "name": "Metrics & Causal Analysis Agent", "level": "L1/L2", "sdlc_stage": "Operations & Maintenance",
     "skill_set": "Measurement, causal analysis, process optimisation", "description": "Tracks quantitative objectives, causal analysis and continuous improvement signals."},
    {"id": "A16", "name": "AI Governance & Assurance Agent", "level": "L1/L2", "sdlc_stage": "Cross-cutting",
     "skill_set": "ISO/IEC 42001, AI risk & impact assessment", "description": "Owns the AI governance plan aligned to ISO/IEC 42001 (AI-01..AI-16)."},
    {"id": "A17", "name": "Supplier Assurance Agent", "level": "L1", "sdlc_stage": "Cross-cutting",
     "skill_set": "Third-party / supplier due diligence", "description": "Assesses supplier and third-party AI/tool due diligence and SLAs."},
    {"id": "A18", "name": "Documentation & Audit Evidence Agent", "level": "L2", "sdlc_stage": "Cross-cutting",
     "skill_set": "Evidence control, CM, audit trail", "description": "Maintains the evidence index, ledger and configuration-managed audit record."},
]

CONTROLS = [
    {"id": "CTRL-01", "name": "Requirement Quality Review", "stage": "Requirements", "trigger": "requirements_submitted", "executor": "A02",
     "independence_method": "model-assisted", "integrity_level": "T0-T4", "autonomy": "observe_advise", "standards_tags": ["CMMI-REQM", "ISO9001"]},
    {"id": "CTRL-02", "name": "Acceptance Criteria Validation", "stage": "Requirements", "trigger": "requirements_submitted", "executor": "A02",
     "independence_method": "deterministic_recompute", "integrity_level": "T1-T4", "autonomy": "observe_advise", "standards_tags": ["CMMI-REQM"]},
    {"id": "CTRL-03", "name": "Traceability Gap Analysis", "stage": "Requirements / Test", "trigger": "test_uploaded", "executor": "A14",
     "independence_method": "deterministic_recompute", "integrity_level": "T0-T4", "autonomy": "observe_advise", "standards_tags": ["CMMI-REQM", "ISO29148"]},
    {"id": "CTRL-04", "name": "Architecture Conformance Review", "stage": "Design", "trigger": "requirements_submitted", "executor": "A04",
     "independence_method": "independent_reviewer_model", "integrity_level": "T2-T4", "autonomy": "observe_advise", "standards_tags": ["CMMI-TS", "TOGAF"]},
    {"id": "CTRL-05", "name": "Threat Model Review", "stage": "Design", "trigger": "requirements_submitted", "executor": "A05",
     "independence_method": "independent_reviewer_model", "integrity_level": "T3-T4", "autonomy": "observe_advise", "standards_tags": ["ISO27001", "STRIDE"]},
    {"id": "CTRL-06", "name": "Secrets Detection", "stage": "Coding / Build", "trigger": "commit_pushed", "executor": "A05",
     "independence_method": "deterministic_recompute", "integrity_level": "T0-T4", "autonomy": "observe_advise", "standards_tags": ["OWASP", "DPDP"]},
    {"id": "CTRL-07", "name": "India PII Detection", "stage": "Coding / Build", "trigger": "commit_pushed", "executor": "A05",
     "independence_method": "deterministic_recompute", "integrity_level": "T0-T4", "autonomy": "observe_advise", "standards_tags": ["DPDP Act 2023"]},
    {"id": "CTRL-08", "name": "Logging Leak Check", "stage": "Coding / Build", "trigger": "commit_pushed", "executor": "A05",
     "independence_method": "deterministic_recompute", "integrity_level": "T0-T4", "autonomy": "observe_advise", "standards_tags": ["OWASP", "DPDP"]},
    {"id": "CTRL-09", "name": "SBOM / Composition Check", "stage": "Coding / Build", "trigger": "commit_pushed", "executor": "A06",
     "independence_method": "none", "integrity_level": "T2-T4", "autonomy": "observe_advise", "standards_tags": ["NTIA-SBOM"]},
    {"id": "CTRL-10", "name": "Static Code Analysis", "stage": "Coding / Build", "trigger": "commit_pushed", "executor": "A06",
     "independence_method": "deterministic_recompute", "integrity_level": "T0-T4", "autonomy": "observe_advise", "standards_tags": ["CMMI-TS"]},
    {"id": "CTRL-11", "name": "Unit Test Adequacy", "stage": "Coding / Build", "trigger": "test_uploaded", "executor": "A07",
     "independence_method": "deterministic_recompute", "integrity_level": "T1-T4", "autonomy": "observe_advise", "standards_tags": ["CMMI-VER"]},
    {"id": "CTRL-12", "name": "Build Integrity Check", "stage": "Coding / Build", "trigger": "commit_pushed", "executor": "A11",
     "independence_method": "none", "integrity_level": "T2-T4", "autonomy": "observe_advise", "standards_tags": ["CMMI-CM"]},
    {"id": "CTRL-13", "name": "API Contract Verification", "stage": "Integration Testing", "trigger": "test_uploaded", "executor": "A08",
     "independence_method": "none", "integrity_level": "T2-T4", "autonomy": "observe_advise", "standards_tags": ["CMMI-PI"]},
    {"id": "CTRL-14", "name": "End-to-End Flow Validation", "stage": "Integration Testing", "trigger": "test_uploaded", "executor": "A08",
     "independence_method": "none", "integrity_level": "T2-T4", "autonomy": "observe_advise", "standards_tags": ["CMMI-PI"]},
    {"id": "CTRL-15", "name": "Security Testing (DAST)", "stage": "System Testing", "trigger": "release_candidate", "executor": "A05",
     "independence_method": "independent_reviewer_model", "integrity_level": "T3-T4", "autonomy": "observe_advise", "standards_tags": ["OWASP"]},
    {"id": "CTRL-16", "name": "Performance Threshold Check", "stage": "System Testing", "trigger": "release_candidate", "executor": "A08",
     "independence_method": "none", "integrity_level": "T2-T4", "autonomy": "observe_advise", "standards_tags": ["CMMI-VER"]},
    {"id": "CTRL-17", "name": "Accessibility Check", "stage": "System Testing", "trigger": "release_candidate", "executor": "A08",
     "independence_method": "none", "integrity_level": "T1-T4", "autonomy": "observe_advise", "standards_tags": ["WCAG 2.2"]},
    {"id": "CTRL-18", "name": "AI Model Evaluation", "stage": "System Testing", "trigger": "release_candidate", "executor": "A16",
     "independence_method": "independent_reviewer_model", "integrity_level": "T2-T4", "autonomy": "observe_advise", "standards_tags": ["ISO/IEC 42001"]},
    {"id": "CTRL-19", "name": "Release Readiness Gate", "stage": "Release", "trigger": "release_candidate", "executor": "A09",
     "independence_method": "deterministic_recompute", "integrity_level": "T0-T4", "autonomy": "observe_advise", "standards_tags": ["CMMI-VAL"]},
    {"id": "CTRL-20", "name": "Runtime Log Assurance", "stage": "Production", "trigger": "release_candidate", "executor": "A13",
     "independence_method": "none", "integrity_level": "T2-T4", "autonomy": "observe_advise", "standards_tags": ["OWASP", "DPDP"]},
]

AI_GOV_CONTROLS = [
    {"id": "AI-01", "control_theme": "AIMS governance and scope", "requirement": "Define AIMS scope, AI policy, accountable owner, roles and interaction with project governance.",
     "minimum_evidence": "AIMS scope; policy; roles/RACI; objectives.", "frequency": "Before AI use and annual review", "owner_agent": "A16/A01", "status": "Planned"},
    {"id": "AI-02", "control_theme": "AI system inventory and role", "requirement": "Register each AI component, model/provider, version, intended use, prohibited use and organisational role.",
     "minimum_evidence": "AI inventory; system description; ownership.", "frequency": "Onboarding & every material change", "owner_agent": "A16", "status": "In Progress"},
    {"id": "AI-03", "control_theme": "AI risk assessment and treatment", "requirement": "Identify risks across safety, privacy, security, rights, bias, reliability, misuse, dependency; select treatments.",
     "minimum_evidence": "Risk register; treatment plan; residual approval.", "frequency": "Before design approval & each major release", "owner_agent": "A16/A05", "status": "Planned"},
    {"id": "AI-04", "control_theme": "AI system impact assessment", "requirement": "Assess impacts on individuals, groups, society and organisation; define safeguards and human recourse.",
     "minimum_evidence": "Impact assessment; consultation evidence.", "frequency": "Before deployment & material change", "owner_agent": "A16/Business Owner", "status": "Planned"},
    {"id": "AI-05", "control_theme": "Data governance", "requirement": "Define provenance, rights, quality, representativeness, privacy, labelling, lineage, retention and access controls.",
     "minimum_evidence": "Data sheet; quality report; lineage; approvals.", "frequency": "Per dataset / version", "owner_agent": "A16/A10", "status": "Planned"},
    {"id": "AI-06", "control_theme": "AI lifecycle and design controls", "requirement": "Document intended behaviour, limits, evaluation, human oversight, fallback, security, change and retirement.",
     "minimum_evidence": "AI lifecycle plan; design assurance record.", "frequency": "Design & change gates", "owner_agent": "A16/A04", "status": "Planned"},
    {"id": "AI-07", "control_theme": "Model/system evaluation", "requirement": "Evaluate performance, robustness, harmful output, bias/fairness, explainability, privacy and security.",
     "minimum_evidence": "Evaluation plan/results; model card; red-team report.", "frequency": "Pre-release & periodic", "owner_agent": "A16/A07/A05", "status": "In Progress"},
    {"id": "AI-08", "control_theme": "Human oversight and accountability", "requirement": "Define decisions requiring human approval, competence, override, escalation and contestability.",
     "minimum_evidence": "Oversight procedure; approval/override logs.", "frequency": "Continuous & gate review", "owner_agent": "A16/A01", "status": "Implemented"},
    {"id": "AI-09", "control_theme": "Transparency and information to interested parties", "requirement": "Disclose AI use, intended purpose, limitations, confidence/uncertainty and feedback channels.",
     "minimum_evidence": "Notices; user guidance; limitation statement.", "frequency": "Before use & when changed", "owner_agent": "A16/Product Owner", "status": "Implemented"},
    {"id": "AI-10", "control_theme": "Third-party AI and supplier assurance", "requirement": "Assess provider due diligence, terms, data use, security, availability, model changes, IP and exit strategy.",
     "minimum_evidence": "Supplier assessment; contract controls; SLA.", "frequency": "Onboarding & annual/material change", "owner_agent": "A17/A16", "status": "Planned"},
    {"id": "AI-11", "control_theme": "Logging, traceability and reproducibility", "requirement": "Log model/version, masked prompt reference, output, reviewer, decision, data references and configuration.",
     "minimum_evidence": "Audit log; trace record; retention controls.", "frequency": "Continuous", "owner_agent": "A16/A18", "status": "Implemented"},
    {"id": "AI-12", "control_theme": "Monitoring, drift and incident response", "requirement": "Monitor performance/drift, harmful outputs, security, complaints and overrides; define thresholds and response.",
     "minimum_evidence": "Monitoring dashboard; incident procedure.", "frequency": "Continuous & periodic review", "owner_agent": "A16/A13/A15", "status": "Planned"},
    {"id": "AI-13", "control_theme": "Competence and awareness", "requirement": "Ensure personnel operating, reviewing and approving AI are competent and understand limitations.",
     "minimum_evidence": "Training plan; competence records.", "frequency": "Before access & annual refresh", "owner_agent": "A16/Quality", "status": "Planned"},
    {"id": "AI-14", "control_theme": "Documented information and evidence control", "requirement": "Control versions, approvals, retention, confidentiality and accessibility of AI governance evidence.",
     "minimum_evidence": "Evidence index; CM records.", "frequency": "Continuous", "owner_agent": "A18", "status": "In Progress"},
    {"id": "AI-15", "control_theme": "Performance evaluation and internal audit", "requirement": "Measure AIMS objectives, conduct internal audits and management review.",
     "minimum_evidence": "KPI results; audit report; management review.", "frequency": "Quarterly / annual", "owner_agent": "A16/Independent Audit", "status": "Planned"},
    {"id": "AI-16", "control_theme": "Nonconformity and continual improvement", "requirement": "Record AI incidents/nonconformities, correct, analyse cause, verify effectiveness and update controls.",
     "minimum_evidence": "NC/CAPA; lessons; updated controls.", "frequency": "Per event & management review", "owner_agent": "A15/A16", "status": "Planned"},
]

EDGE_CLIENTS = [
    {"id": "EC-01", "name": "Copilot in VS Code", "who_uses_it": "Developers / seniors with Copilot licence",
     "trust_class": "Client-generated, unverified", "may_set_verdict": False, "identity_data": "Personal token + role assignment",
     "notes": "Org pays for Copilot. Admin policy must allow the tool server."},
    {"id": "EC-02", "name": "Droid (with Fabric)", "who_uses_it": "Senior team members",
     "trust_class": "Client-generated, unverified", "may_set_verdict": False, "identity_data": "Personal token + role assignment",
     "notes": "Droid features not independently verified; confirm in pilot."},
    {"id": "EC-03", "name": "Platform CLI", "who_uses_it": "Anyone, incl. air-gapped users",
     "trust_class": "Platform-run", "may_set_verdict": True, "identity_data": "Personal token + role assignment",
     "notes": "Only route for air-gapped clients. Masked data only to platform models."},
    {"id": "EC-04", "name": "Webhook Listener (GitHub, ticketing)", "who_uses_it": "Automatic",
     "trust_class": "Platform-run", "may_set_verdict": True, "identity_data": "Service identity",
     "notes": "Read-only app with HMAC verification. No write scopes exist."},
    {"id": "EC-05", "name": "Central Repo Audit", "who_uses_it": "Quality Lead, Tech Lead",
     "trust_class": "Platform-run", "may_set_verdict": True, "identity_data": "Requesting user token",
     "notes": "Comprehensive audit with no third-party client tool involved."},
    {"id": "EC-06", "name": "Portal (visual cockpit)", "who_uses_it": "All roles",
     "trust_class": "n/a - view & triage only", "may_set_verdict": False, "identity_data": "Personal token",
     "notes": "Tamper-evident badge, provenance chips, per-developer timeline."},
]

GOOD_REQUIREMENTS = [
    ("REQ-001", "The system shall authenticate a user within 2 seconds using multi-factor authentication for 99.9% of login attempts.", "Critical"),
    ("REQ-002", "The system shall mask all Aadhaar and PAN values displayed in any UI, showing no more than the first 2 and last 2 characters.", "Critical"),
    ("REQ-003", "The system shall record an immutable, SHA-256 hash-chained ledger entry for every finding and triage decision within 500ms.", "High"),
    ("REQ-004", "The payment gateway integration shall process a refund request and notify the user within 24 hours, with 99.5% success rate.", "High"),
]

POOR_REQUIREMENTS = [
    ("REQ-005", "The system should be user-friendly and fast when users do stuff with their account, etc.", "Medium"),
    ("REQ-006", "The admin dashboard may possibly show appropriate reports as needed for several stakeholders.", "Medium"),
    ("REQ-007", "The system should handle errors in an adequate and appropriate manner.", "Low"),
    ("REQ-008", "The reporting module may be easy to use and should work fine for most cases and/or edge cases.", "Medium"),
]

GOOD_CODE = """
def process_order(order_id, amount):
    logger.info("processing order %s", order_id)
    if amount <= 0:
        raise ValueError("amount must be positive")
    return charge_gateway(order_id, amount)
"""

SECRET_CODE = """
import boto3
AWS_ACCESS_KEY = "AKIAABCDEFGHIJKLMNOP"
OPENAI_KEY = "sk-proj-THISISADEMOFAKEKEYFORSEEDDATAONLY1234567890"

def connect():
    client = boto3.client("s3", aws_access_key_id=AWS_ACCESS_KEY)
    return client
"""

PII_CODE = """
def register_customer(name, aadhaar, pan, mobile):
    print("registering", name, aadhaar, pan, mobile)
    db.save({"name": name, "aadhaar_number": "234567890123", "pan_number": "ABCDE1234F", "mobile": "9876543210"})
    return True
"""

LOGGING_LEAK_CODE = """
def login(username, password):
    logger.info("login attempt user=%s password=%s", username, password)
    token = generate_token(username)
    logger.debug("issued token=%s", token)
    return token

def fetch_report():
    # TODO: paginate this properly
    data = []
    for i in range(100):
        data.append(i)
    try:
        risky_call()
    except:
        pass
    return data
"""


async def ensure_seeded(db):
    if await db.projects.count_documents({}) > 0:
        return

    gateway.FORCE_ZERO_LLM = True  # keep bulk demo seeding fast and free
    try:
        await _seed(db)
    finally:
        gateway.FORCE_ZERO_LLM = False


async def _seed(db):
    await db.agents.insert_many([dict(a) for a in AGENTS])
    await db.controls.insert_many([dict(c) for c in CONTROLS])
    await db.ai_governance.insert_many([dict(c) for c in AI_GOV_CONTROLS])
    await db.edge_clients.insert_many([dict(c) for c in EDGE_CLIENTS])

    now = datetime.now(timezone.utc).isoformat()
    projects = [
        {"id": str(uuid4()), "name": "UPI Settlement Gateway", "description": "Core payments settlement platform for a regulated fintech client.",
         "integrity_tier": "T4", "stage": "Coding / Build", "created_at": now},
        {"id": str(uuid4()), "name": "Citizen Services Portal", "description": "Public-sector self-service portal handling India citizen PII at scale.",
         "integrity_tier": "T3", "stage": "Requirements", "created_at": now},
        {"id": str(uuid4()), "name": "Internal Analytics Dashboard", "description": "Low-risk internal BI dashboard for operations reporting.",
         "integrity_tier": "T1", "stage": "Release", "created_at": now},
    ]
    await db.projects.insert_many([dict(p) for p in projects])

    for idx, project in enumerate(projects):
        pid = project["id"]
        reqs = []
        for req_id, text, crit in GOOD_REQUIREMENTS:
            reqs.append({"id": str(uuid4()), "project_id": pid, "req_id": f"{req_id}-{idx}", "text": text, "criticality": crit, "source": "Business Owner", "created_at": now})
        for req_id, text, crit in POOR_REQUIREMENTS:
            reqs.append({"id": str(uuid4()), "project_id": pid, "req_id": f"{req_id}-{idx}", "text": text, "criticality": crit, "source": "Business Owner", "created_at": now})
        await db.requirements.insert_many([dict(r) for r in reqs])

        designs = [
            {"id": str(uuid4()), "project_id": pid, "design_id": f"DES-001-{idx}", "requirement_ids": [f"REQ-001-{idx}", f"REQ-002-{idx}"], "summary": "Auth & data-masking design."},
            {"id": str(uuid4()), "project_id": pid, "design_id": f"DES-002-{idx}", "requirement_ids": [f"REQ-003-{idx}"], "summary": "Ledger hash-chain design."},
        ]
        await db.design_items.insert_many([dict(d) for d in designs])

        commits = [
            {"id": str(uuid4()), "project_id": pid, "commit_id": f"c{idx}1a2b3", "author": "Asha Verma", "message": "Add order processing", "code_snippet": GOOD_CODE, "requirement_ids": [f"REQ-004-{idx}"], "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "commit_id": f"c{idx}4d5e6f", "author": "Rohit Nair", "message": "Wire up S3 client", "code_snippet": SECRET_CODE, "requirement_ids": [f"REQ-003-{idx}"], "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "commit_id": f"c{idx}7g8h9i", "author": "Asha Verma", "message": "Customer registration", "code_snippet": PII_CODE, "requirement_ids": [f"REQ-002-{idx}"], "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "commit_id": f"c{idx}jk1lm2", "author": "Priya Shah", "message": "Login + reporting", "code_snippet": LOGGING_LEAK_CODE, "requirement_ids": [f"REQ-001-{idx}"], "created_at": now},
        ]
        await db.commits.insert_many([dict(c) for c in commits])

        tests = [
            {"id": str(uuid4()), "project_id": pid, "test_id": f"TC-001-{idx}", "type": "unit", "requirement_ids": [f"REQ-001-{idx}"], "status": "passed", "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "test_id": f"TC-002-{idx}", "type": "unit", "requirement_ids": [f"REQ-003-{idx}"], "status": "passed", "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "test_id": f"TC-003-{idx}", "type": "integration", "requirement_ids": [f"REQ-004-{idx}"], "status": "passed", "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "test_id": f"TC-004-{idx}", "type": "uat", "requirement_ids": [f"REQ-001-{idx}", f"REQ-004-{idx}"], "status": "passed", "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "test_id": f"TC-SEC-001-{idx}", "type": "security", "requirement_ids": [f"REQ-001-{idx}"], "status": "passed", "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "test_id": f"TC-SEC-002-{idx}", "type": "security", "requirement_ids": [f"REQ-002-{idx}"], "status": "failed", "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "test_id": f"TC-PERF-001-{idx}", "type": "performance", "metric": "p95_latency_ms", "measured": 180, "threshold": 200, "requirement_ids": [f"REQ-001-{idx}"], "status": "passed", "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "test_id": f"TC-PERF-002-{idx}", "type": "performance", "metric": "settlement_p95_ms", "measured": 420, "threshold": 300, "requirement_ids": [f"REQ-004-{idx}"], "status": "failed", "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "test_id": f"TC-ACC-001-{idx}", "type": "accessibility", "wcag_violations": 0, "requirement_ids": [f"REQ-005-{idx}"], "status": "passed", "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "test_id": f"TC-ACC-002-{idx}", "type": "accessibility", "wcag_violations": 3, "requirement_ids": [f"REQ-006-{idx}"], "status": "failed", "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "test_id": f"TC-AI-001-{idx}", "type": "ai_eval", "metric": "toxicity", "score": 0.02, "threshold": 0.05, "direction": "lower_is_better", "status": "passed", "created_at": now},
            {"id": str(uuid4()), "project_id": pid, "test_id": f"TC-AI-002-{idx}", "type": "ai_eval", "metric": "groundedness", "score": 0.78, "threshold": 0.85, "direction": "higher_is_better", "status": "failed", "created_at": now},
        ]
        await db.test_cases.insert_many([dict(t) for t in tests])

        await engine.run_event(db, pid, "requirements_submitted", triggered_by="seed")
        for c in commits:
            await engine.run_event(db, pid, "commit_pushed", source_ref=c["id"], triggered_by="seed")
        await engine.run_event(db, pid, "test_uploaded", triggered_by="seed")
        await engine.run_event(db, pid, "release_candidate", triggered_by="seed")
