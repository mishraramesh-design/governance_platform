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
from detectors import scan_secrets, scan_pii, mask_sensitive_text, get_project_key
import engine
import repo_ingest
import evidence_pack
import ledger as ledger_mod
import auth

router = APIRouter()


@router.get("/ledger")
async def get_ledger(response: Response, project_id: str = None, page: int = 1, page_size: int = 200):
    """Paginated. project_id selects that project's chain; omit for the platform chain.
    Total is returned in the X-Total-Count header (never silently truncated)."""
    page, page_size = max(1, page), min(max(1, page_size), 1000)
    q = {"chain": project_id or ledger_mod.GLOBAL}
    response.headers["X-Total-Count"] = str(await db.ledger.count_documents(q))
    return await db.ledger.find(q, {"_id": 0}).sort("seq", 1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)


@router.get("/ledger/chains")
async def ledger_chains():
    out = []
    for c in await ledger_mod.chains(db):
        out.append({"chain": c, "entries": await db.ledger.count_documents({"chain": c})})
    return out


@router.get("/ledger/verify")
async def verify_ledger(project_id: str = None):
    ledger_mod._cache["val"] = None
    return await ledger_mod.verify_integrity(db, project_id)


@router.post("/ledger/rebuild")
async def rebuild_ledger(chain: str = ledger_mod.GLOBAL, user=Depends(auth.get_current_user)):
    await auth.require_any_global_role(user, {auth.ADMIN_ROLE})
    return await ledger_mod.rebuild_chain(db, chain)


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



_TASKS: set = set()


def _params(payload):
    return dict(git_url=payload.github_url, name=payload.name, git_token=payload.git_token,
                branch=(payload.branch or None), integrity_level=payload.integrity_level,
                data_sensitivity=payload.data_sensitivity or "unknown",
                folder_map=[e.model_dump() for e in payload.folder_map], languages=payload.languages)


@router.post("/repo-audit/ingest")
async def ingest_repo_audit(payload: RepoAuditRequest, sync: bool = False, user=Depends(auth.get_current_user)):
    await auth.require_any_global_role(user, auth.GOVERNANCE_ROLES)
    params = _params(payload)
    try:
        if sync:
            result = await repo_ingest.ingest_repo(db, started_by=user["name"], **params)
            pid = (result.get("project") or {}).get("id")
            if pid:
                await auth.ensure_project_assignments(pid)
            return result
        # validate cheaply before queueing
        import re as _re
        if not _re.match(r"^https://github\.com/[\w.\-]+/[\w.\-]+/?$", payload.github_url.strip()):
            raise ValueError("Please provide a valid GitHub repository URL, e.g. https://github.com/org/repo")
        if payload.branch and not repo_ingest.BRANCH_RE.match(payload.branch):
            raise ValueError("Invalid branch name")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    import asyncio
    from uuid import uuid4
    from datetime import datetime, timezone
    job_id = str(uuid4())
    await db.repo_jobs.insert_one({
        "id": job_id, "status": "queued", "github_url": payload.github_url.strip(), "branch": payload.branch,
        "requested_by": user["id"], "requested_by_name": user["name"],
        "created_at": datetime.now(timezone.utc).isoformat()})

    async def _go():
        result = await repo_ingest.run_job(db, job_id, params, user["name"])
        if result:
            await auth.ensure_project_assignments(result["project"]["id"])
    t = asyncio.create_task(_go())
    _TASKS.add(t)
    t.add_done_callback(_TASKS.discard)
    return {"job_id": job_id, "status": "queued"}


def _job_view(j):
    live = repo_ingest.JOB_STATE.get(j["id"])
    if live and j.get("status") not in ("done", "failed", "cancelled"):
        j = {**j, **{k: v for k, v in live.items() if k != "status"}, "status": live.get("status", j["status"])}
    return j


@router.get("/repo-audit/jobs")
async def list_repo_jobs(limit: int = 30, _u=Depends(auth.require_read_access)):
    rows = await db.repo_jobs.find({}, {"_id": 0}).sort("created_at", -1).to_list(min(limit, 200))
    return [_job_view(j) for j in rows]


@router.get("/repo-audit/jobs/{job_id}")
async def get_repo_job(job_id: str, _u=Depends(auth.require_read_access)):
    j = await db.repo_jobs.find_one({"id": job_id}, {"_id": 0})
    if not j:
        raise HTTPException(404, "job not found")
    return _job_view(j)


@router.post("/repo-audit/jobs/{job_id}/cancel")
async def cancel_repo_job(job_id: str, user=Depends(auth.get_current_user)):
    await auth.require_any_global_role(user, auth.GOVERNANCE_ROLES)
    j = await db.repo_jobs.find_one({"id": job_id}, {"_id": 0})
    if not j:
        raise HTTPException(404, "job not found")
    ev = repo_ingest.JOB_CANCEL.get(job_id)
    if not ev:
        raise HTTPException(409, f"job is not running (status {j['status']})")
    ev.set()
    return {"job_id": job_id, "cancelling": True}


@router.get("/repo-audit/{project_id}/evidence-pack")
async def evidence_pack_endpoint(project_id: str, format: str = "pdf"):
    fmt = "docx" if format.lower() == "docx" else "pdf"
    project = await db.projects.find_one({"id": project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "project not found")
    audit = await db.repo_audits.find_one({"project_id": project_id}, {"_id": 0}, sort=[("created_at", -1)])
    findings = await db.findings.find({"project_id": project_id}, {"_id": 0}).to_list(None)
    reports = await db.reports.find({"project_id": project_id}, {"_id": 0}).to_list(50)
    gates = await engine.compute_gate_status(db, project_id)
    verify = await ledger_mod.verify_integrity(db, project_id)
    refs = {project_id} | {f["id"] for f in findings} | {r["id"] for r in reports}
    if audit:
        refs.add(audit["id"])
    led = await db.ledger.find({"chain": project_id, "payload_ref": {"$in": list(refs)}}, {"_id": 0}).sort("seq", 1).to_list(None)
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


def _audit_profile(audit):
    audit = audit or {}
    return {"languages": {l: 1 for l in audit.get("detected_languages", [])},
            "frameworks": audit.get("frameworks", []),
            "code_files_scanned": audit.get("code_files_scanned", 0),
            "approx_loc": audit.get("approx_loc", 0)}


@router.post("/repo-audit/simulate")
async def simulate_repo_audit(payload: RepoAuditRequest, user=Depends(auth.get_current_user)):
    project = await db.projects.find_one({"id": payload.project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "project not found")
    await auth.require_member(user, payload.project_id)

    digest = hashlib.sha256(payload.github_url.encode()).hexdigest()
    seed_val = int(digest[:8], 16)
    languages_pool = ["Python", "TypeScript", "Java", "Go", "JavaScript", "C#"]
    languages = [languages_pool[seed_val % len(languages_pool)], languages_pool[(seed_val // 7) % len(languages_pool)]]
    suggested_tier = [4, 3, 2, 1][seed_val % 4]
    folder_map = ["/src", "/tests", "/infra", "/docs"] if seed_val % 2 == 0 else ["/app", "/services", "/pipelines"]

    audit = {
        "id": str(uuid4()), "project_id": payload.project_id, "github_url": payload.github_url,
        "detected_languages": sorted(set(languages)), "suggested_integrity_level": suggested_tier,
        "folder_map": folder_map, "note": "Simulated - no live repository was accessed in this prototype.",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.repo_audits.insert_one(dict(audit))
    await ledger_mod.append_to_ledger(db, "repo_audit", audit["id"], {"project_id": payload.project_id, "github_url": payload.github_url})
    audit.pop("_id", None)
    return audit


@router.post("/runtime/analyze")
async def analyze_runtime_log(payload: RuntimeAnalyzeRequest, user=Depends(auth.get_current_user)):
    await auth.require_member(user, payload.project_id)
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
    await ledger_mod.append_to_ledger(db, "runtime_report", report["id"], {"project_id": payload.project_id})
    report.pop("_id", None)
    return report
