import hashlib
import hmac
import json
import os
import re
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response, Depends

from database import db
from models import RepoAuditRequest, RuntimeAnalyzeRequest, EdgeClientSimulateRequest, EdgeClientBundleRequest
from pydantic import BaseModel, Field
from detectors import scan_secrets, scan_pii, mask_sensitive_text, get_project_key
import engine
import repo_ingest
import evidence_pack
import ledger as ledger_mod
import auth

router = APIRouter()


@router.get("/ledger")
async def get_ledger():
    return await db.ledger.find({}, {"_id": 0}).sort([('timestamp', 1), ('id', 1)]).to_list(200000)


@router.get("/ledger/verify")
async def verify_ledger():
    return await ledger_mod.verify_integrity(db)


@router.post("/ledger/rebuild")
async def rebuild_ledger(user=Depends(auth.get_current_user)):
    await auth.require_any_global_role(user, {auth.ADMIN_ROLE})
    raise HTTPException(410, 'In-place rebuilding is disabled. Use /ledger/baseline to acknowledge preserved historical evidence.')


class BaselineReview(BaseModel):
    reason: str = Field(min_length=20, max_length=2000)
    acknowledge_historical_failure: bool = False


@router.post('/ledger/baseline')
async def review_baseline(payload: BaselineReview, user=Depends(auth.get_current_user)):
    await auth.require_any_global_role(user, {auth.ADMIN_ROLE})
    if not payload.acknowledge_historical_failure:
        raise HTTPException(400, 'Explicitly acknowledge that historical failures remain visible.')
    try:
        return await ledger_mod.acknowledge_legacy(db, user['id'], mask_sensitive_text(payload.reason)[0])
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/edge-clients")
async def list_edge_clients():
    return await db.edge_clients.find({}, {"_id": 0}).to_list(100)


@router.get("/edge-clients/contributions")
async def list_edge_contributions(project_id: str = None):
    q = {"project_id": project_id} if project_id else {}
    items = await db.edge_contributions.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    attributed = [c for c in items if c.get("status") != "unattributed"]
    unattributed = [c for c in items if c.get("status") == "unattributed"]
    return {
        "contributions": items,
        "attributed_count": len(attributed),
        "unattributed_count": len(unattributed),
        "counted_in_evidence": len(attributed),  # unattributed are excluded from evidence counts
    }


@router.post("/edge-clients/simulate")
async def simulate_edge_client(payload: EdgeClientSimulateRequest,
                               user=Depends(auth.get_optional_user)):
    client = await db.edge_clients.find_one({"id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "unknown edge client")
    project = await db.projects.find_one({"id": payload.project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "project not found")

    if client["id"] in ("EC-01", "EC-02"):
        # Unverified client path accepts anonymous input. A missing/revoked token is
        # recorded as 'unattributed' and excluded from evidence counts/gates/reports.
        if user and payload.role:
            await auth.require_project_role(user, payload.project_id, payload.role)
        status = "attributed" if user else "unattributed"
        contribution = {
            "id": str(uuid4()), "client_id": client["id"], "client_name": client["name"],
            "project_id": payload.project_id, "note": payload.note or "",
            "trust_class": "Client-generated, unverified", "may_set_verdict": False,
            "provenance": "client_model_unverified", "status": status,
            "submitted_by_user_id": user["id"] if user else None,
            "submitted_by_user_name": user["name"] if user else None,
            "acting_role": payload.role if user else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.edge_contributions.insert_one(dict(contribution))
        await ledger_mod.append_to_ledger(db, "edge_contribution", contribution["id"],
                                          {"client_id": client["id"], "project_id": payload.project_id,
                                           "status": status, "user_id": user["id"] if user else None})
        contribution.pop("_id", None)
        return {"mode": "unverified_contribution", "contribution": contribution}

    # Platform-routed clients may set a verdict -> require a valid token + assigned role.
    if not user:
        raise HTTPException(401, "Valid bearer token required to route a platform event",
                            headers={"WWW-Authenticate": "Bearer"})
    if not payload.role:
        raise HTTPException(422, "role is required to route a platform event")
    await auth.require_project_role(user, payload.project_id, payload.role)
    event_type = payload.event_type or "commit_pushed"
    result = await engine.run_event(db, payload.project_id, event_type, payload.source_ref,
                                    triggered_by=f"{client['id']}:{user['name']}")
    return {"mode": "platform_routed_event", "client": client, "result": result}


# ---------------------------------------------------------------------------
# Edge-client signed bundles (EC-01 Copilot, EC-02 Droid). These are client-generated
# and UNVERIFIED: they can never create/change/remove a PASS/FAIL verdict. Each bundle
# is hashed (SHA-256 over canonical JSON), HMAC-signed with a per-user key derived from
# a server secret, and anchored in the tamper-evident ledger.
# ---------------------------------------------------------------------------
UNVERIFIED_CLIENTS = ("EC-01", "EC-02")


def _edge_secret() -> bytes:
    s = os.environ.get("EDGE_SIGNING_SECRET")
    if not s:
        raise HTTPException(500, "EDGE_SIGNING_SECRET is not configured")
    return s.encode()


def _edge_user_key(user_id: str) -> bytes:
    # Per-user signing key derived from the server secret; never stored, never returned.
    return hmac.new(_edge_secret(), user_id.encode(), hashlib.sha256).digest()


def _edge_sign(user_id: str, bundle_hash: str) -> str:
    return hmac.new(_edge_user_key(user_id), bundle_hash.encode(), hashlib.sha256).hexdigest()


def _canonical_bundle(doc: dict) -> str:
    core = {
        "client_id": doc["client_id"],
        "project_id": doc["project_id"],
        "prompt_hash": doc["prompt_hash"],
        "tool_calls": doc["tool_calls"],
        "input_hashes": doc["input_hashes"],
        "output_text": doc["output_text"],
        "role": doc["role"],
        "submitted_by_user_id": doc["submitted_by_user_id"],
    }
    return json.dumps(core, sort_keys=True, separators=(",", ":"), default=str)


def _bundle_hash(doc: dict) -> str:
    return hashlib.sha256(_canonical_bundle(doc).encode()).hexdigest()


@router.post("/edge-clients/submit")
async def submit_edge_bundle(payload: EdgeClientBundleRequest, user=Depends(auth.get_current_user)):
    if payload.client_id not in UNVERIFIED_CLIENTS:
        raise HTTPException(422, "submit accepts only unverified client models: EC-01 (Copilot), EC-02 (Droid)")
    client = await db.edge_clients.find_one({"id": payload.client_id}, {"_id": 0})
    if not client:
        raise HTTPException(404, "unknown edge client")
    project = await db.projects.find_one({"id": payload.project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "project not found")
    await auth.require_project_role(user, payload.project_id, payload.role)

    key = await get_project_key(db, payload.project_id)
    masked_output, detections = mask_sensitive_text(payload.output_text, key)

    doc = {
        "id": str(uuid4()),
        "client_id": client["id"], "client_name": client["name"],
        "project_id": payload.project_id,
        "prompt_hash": payload.prompt_hash,          # stored; prompt text is never stored
        "tool_calls": payload.tool_calls,
        "input_hashes": payload.input_hashes,
        "output_text": masked_output,                # stored only after masking
        "role": payload.role,
        "submitted_by_user_id": user["id"],
        "submitted_by_user_name": user["name"],
        "trust_class": "Client-generated, unverified",
        "may_set_verdict": False,
        "provenance": "client_model_unverified",
        "masked_values": len(detections),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    bundle_hash = _bundle_hash(doc)
    signature = _edge_sign(user["id"], bundle_hash)
    doc["bundle_hash"] = bundle_hash
    doc["signature"] = signature

    await db.edge_bundles.insert_one(dict(doc))
    entry = await ledger_mod.append_to_ledger(
        db, "edge_bundle", doc["id"],
        {"client_id": doc["client_id"], "project_id": doc["project_id"],
         "bundle_hash": bundle_hash, "signature": signature, "user_id": user["id"]})
    doc.pop("_id", None)
    return {"bundle": doc, "ledger_seq": entry["seq"]}


@router.get("/edge-clients/bundles")
async def list_edge_bundles(project_id: str = None):
    q = {"project_id": project_id} if project_id else {}
    return await db.edge_bundles.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.get("/edge-clients/bundles/{bundle_id}/verify")
async def verify_edge_bundle(bundle_id: str):
    doc = await db.edge_bundles.find_one({"id": bundle_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "bundle not found")
    recomputed = _bundle_hash(doc)
    hash_ok = recomputed == doc.get("bundle_hash")
    expected_sig = _edge_sign(doc["submitted_by_user_id"], recomputed)
    sig_ok = hmac.compare_digest(expected_sig, doc.get("signature", ""))
    valid = hash_ok and sig_ok
    return {
        "bundle_id": bundle_id,
        "valid": valid,
        "status": "valid" if valid else "tampered",
        "stored_hash": doc.get("bundle_hash"),
        "recomputed_hash": recomputed,
        "hash_match": hash_ok,
        "signature_valid": sig_ok,
    }



@router.post("/repo-audit/ingest")
async def ingest_repo_audit(payload: RepoAuditRequest, user=Depends(auth.get_current_user)):
    await auth.require_any_global_role(user, auth.GOVERNANCE_ROLES)
    try:
        result = await repo_ingest.ingest_repo(db, payload.github_url, payload.name, payload.git_token, actor=user)
        pid = (result.get("project") or {}).get("id")
        if pid:
            await auth.ensure_project_assignments(pid, user)
        return result
    except repo_ingest.AuditAlreadyRunning as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@router.get("/repo-audit/{project_id}/evidence-pack")
async def evidence_pack_endpoint(project_id: str, format: str = "pdf"):
    fmt = "docx" if format.lower() == "docx" else "pdf"
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "project not found")
    audit = await db.repo_audits.find_one({"project_id": project_id}, {"_id": 0}, sort=[("created_at", -1)])
    findings = await db.findings.find({"project_id": project_id}, {"_id": 0}).to_list(5000)
    reports = await db.reports.find({"project_id": project_id}, {"_id": 0}).to_list(50)
    gates = await engine.compute_gate_status(db, project_id)
    verify = await ledger_mod.verify_integrity(db)
    refs = {project_id} | {f["id"] for f in findings} | {r["id"] for r in reports}
    if audit:
        refs.add(audit["id"])
    led = await db.ledger.find({"payload_ref": {"$in": list(refs)}}, {"_id": 0}).sort("seq", 1).to_list(5000)
    data = {
        "project": project, "profile": _audit_profile(audit),
        "audit": audit or {}, "findings": findings, "reports": reports, "gates": gates,
        "endpoints": (audit or {}).get("endpoints", []),
        "ledger_entries": led, "ledger_verify": verify,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    content, mime, ext = evidence_pack.build(data, fmt)
    fname = f"evidence_pack_{project['name']}.{ext}".replace(" ", "_")
    return Response(content=content, media_type=mime,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get('/repo-audit/{project_id}/history')
async def audit_versions(project_id: str):
    return await db.repo_audit_versions.find({'project_id': project_id},
        {'_id': 0, 'records': 0}).sort('archived_at', -1).to_list(200)


@router.get('/repo-audit/{project_id}/history/{version_id}')
async def audit_version(project_id: str, version_id: str):
    version = await db.repo_audit_versions.find_one({'id': version_id, 'project_id': project_id}, {'_id': 0})
    if not version:
        raise HTTPException(404, 'Audit version not found.')
    from audit_history import historical_record, record_hash
    records = []
    for item in version['records']:
        record = await historical_record(db, item['collection'], item['record_id'])
        if not record or record_hash(record) != item['sha256']:
            raise HTTPException(409, 'Historical audit content failed its hash check.')
        records.append({'collection': item['collection'], 'record': record, 'sha256': item['sha256']})
    return {'version': version, 'records': records}


def _audit_profile(audit):
    audit = audit or {}
    return {"languages": {l: 1 for l in audit.get("detected_languages", [])},
            "frameworks": audit.get("frameworks", []),
            "code_files_scanned": audit.get("code_files_scanned", 0),
            "approx_loc": audit.get("approx_loc", 0)}


@router.post("/repo-audit/simulate")
async def simulate_repo_audit(payload: RepoAuditRequest):
    project = await db.projects.find_one({"id": payload.project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "project not found")

    digest = hashlib.sha256(payload.github_url.encode()).hexdigest()
    seed_val = int(digest[:8], 16)
    languages_pool = ["Python", "TypeScript", "Java", "Go", "JavaScript", "C#"]
    languages = [languages_pool[seed_val % len(languages_pool)], languages_pool[(seed_val // 7) % len(languages_pool)]]
    suggested_tier = ["T1", "T2", "T3", "T4"][seed_val % 4]
    folder_map = ["/src", "/tests", "/infra", "/docs"] if seed_val % 2 == 0 else ["/app", "/services", "/pipelines"]

    audit = {
        "id": str(uuid4()), "project_id": payload.project_id, "github_url": payload.github_url,
        "detected_languages": sorted(set(languages)), "suggested_integrity_tier": suggested_tier,
        "folder_map": folder_map, "note": "Simulated - no live repository was accessed in this prototype.",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.repo_audits.insert_one(dict(audit))
    await ledger_mod.append_to_ledger(db, "repo_audit", audit["id"], {"project_id": payload.project_id, "github_url": payload.github_url})
    audit.pop("_id", None)
    return audit


@router.post("/runtime/analyze")
async def analyze_runtime_log(payload: RuntimeAnalyzeRequest, user=Depends(auth.get_current_user)):
    project = await db.projects.find_one({"id": payload.project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "project not found")

    log_text = payload.log_text
    secret_hits = scan_secrets(log_text)
    pii_hits = scan_pii(log_text)
    security_findings = secret_hits + pii_hits

    quality_issues = len(re.findall(r"ERROR|Exception|Traceback", log_text, re.IGNORECASE))
    perf_issues = re.findall(r"took\s+(\d+)\s*ms", log_text, re.IGNORECASE)
    slow_calls = [int(p) for p in perf_issues if int(p) > 1000]

    traced = []
    for hit in security_findings:
        matching = await db.findings.find_one({"evidence.hash": hit["hash"]}, {"_id": 0})
        if matching:
            traced.append({"log_hash": hit["hash"], "traced_to_finding_id": matching["id"], "control_name": matching["control_name"]})

    report = {
        "id": str(uuid4()), "project_id": payload.project_id,
        "security": {"verdict": "FAIL" if security_findings else "PASS", "findings": security_findings},
        "performance": {"verdict": "FAIL" if slow_calls else "PASS", "slow_calls_over_1000ms": slow_calls},
        "quality": {"verdict": "FAIL" if quality_issues > 0 else "PASS", "error_line_count": quality_issues},
        "log_to_source_tracing": traced,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.runtime_reports.insert_one(dict(report))
    await ledger_mod.append_to_ledger(db, "runtime_report", report["id"], {"project_id": payload.project_id, 'actor_user_id': user['id']})
    report.pop("_id", None)
    return report
