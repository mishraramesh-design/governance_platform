"""Governance Studio intake and deterministic, evidence-linked run planning.

This endpoint does not probe target URLs. Active testing requires a separate
authorized execution adapter and an approved target scope.
"""
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import asyncio
import logging
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from io import BytesIO
import zipfile
from pydantic import ValidationError

from database import db
from models import GovernanceStudioRunRequest
from web_security_scan import execute_zap_baseline, validate_public_target
from studio_planning import build_run_plan, extract_candidate_requirements, sha256_text, summarize_runtime_logs
import repo_ingest
import auth
import ledger as ledger_mod

router = APIRouter(prefix="/studio", tags=["Governance Studio"])
logger = logging.getLogger(__name__)
_web_scan_lock = asyncio.Lock()
_web_scan_enqueue_lock = asyncio.Lock()
_web_scan_tasks = set()


def _zap_enabled():
    return bool(os.environ.get("ZAP_API_URL") and os.environ.get("ZAP_API_KEY"))


async def _create_studio_run(payload: GovernanceStudioRunRequest, user):
    await auth.require_any_global_role(user, auth.GOVERNANCE_ROLES)
    if payload.target_url and not payload.authorization_confirmed:
        raise HTTPException(400, "Confirm written authorization before adding a web target.")
    if payload.target_url and not all(str(value or "").strip() for value in (payload.authorization_scope, payload.authorization_owner, payload.authorization_reference)):
        raise HTTPException(400, "Provide scope/exclusions, the authorizing owner's name, and an approval/ticket reference.")

    requirements = extract_candidate_requirements(payload.frs_text)
    run_id = str(uuid4())
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "id": run_id,
        "name": payload.name,
        "status": "planned",
        "created_at": now,
        "created_by_user_id": user["id"],
        "source": {"github_url": payload.github_url, "target_url": payload.target_url,
                   "authorization_confirmed": payload.authorization_confirmed,
                   "authorization_owner": payload.authorization_owner,
                   "authorization_reference": payload.authorization_reference,
                   "authorization_scope": payload.authorization_scope,
                   "duration_hours": payload.duration_hours,
                   "frs_filename": payload.frs_filename,
                   "window_starts_at": now,
                   "window_expires_at": (datetime.now(timezone.utc) + timedelta(hours=payload.duration_hours)).isoformat()},
        "inputs": {"frs_sha256": sha256_text(payload.frs_text), "runtime_logs_sha256": sha256_text(payload.runtime_logs),
                   "frs_raw_retained": False, "runtime_logs_raw_retained": False},
        "requirements": requirements,
        "requirements_candidate_count": len(requirements),
        "runtime_summary": summarize_runtime_logs(payload.runtime_logs),
        "plan": build_run_plan(bool(payload.github_url), bool(payload.frs_text), bool(payload.target_url), bool(payload.runtime_logs), payload.authorization_confirmed),
        "policy": {"active_web_testing_executed": False, "destructive_testing": False,
                   "credential_use": False, "cross_scope_requests": False,
                   "cmmi_level_claim": False,
                   "cmmi_note": "Readiness evidence only; formal maturity is determined by an authorized organizational appraisal."},
        "limitations": ["The URL is recorded but not contacted by this planning endpoint.",
                        "No dynamic or load test has run; execution requires a separately approved scanner adapter and bounded environment.",
                        "Extracted requirements are candidates and need accountable human review."],
    }
    if payload.target_url and _zap_enabled():
        for step in record["plan"]:
            if step["id"] == "WEB-01":
                step.update({"executor": "OWASP ZAP baseline (passive rules)", "state": "planned_execution_available",
                             "evidence": "bounded crawl, passive alert evidence, scanner version and ledger reference"})
    await db.studio_runs.insert_one(dict(record))
    ledger_entry = await ledger_mod.append_to_ledger(db, "governance_studio_run_created", run_id, {
        "name": payload.name, "github_url": payload.github_url, "target_url": payload.target_url,
        "authorization_confirmed": payload.authorization_confirmed, "duration_hours": payload.duration_hours,
        "authorization_owner": payload.authorization_owner,
        "authorization_reference": payload.authorization_reference,
        "authorization_scope": payload.authorization_scope,
        "frs_sha256": record["inputs"]["frs_sha256"], "runtime_logs_sha256": record["inputs"]["runtime_logs_sha256"],
        "requirements_candidate_count": len(requirements),
    })
    record["ledger"] = {"seq": ledger_entry["seq"], "hash": ledger_entry["hash"], "entry_id": ledger_entry["id"]}
    await db.studio_runs.update_one({"id": run_id}, {"$set": {"ledger": record["ledger"]}})
    return record


async def _run_zap_for_record(run_id: str, record: dict, user_id: str):
    """Run a serialized, bounded ZAP baseline and retain normalized findings."""
    async with _web_scan_lock:
        await db.studio_runs.update_one({"id": run_id}, {"$set": {"web_security_scan.status": "running",
                                                                    "web_security_scan.started_at": datetime.now(timezone.utc).isoformat()}})
        try:
            expires_at = datetime.fromisoformat(record["source"]["window_expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= expires_at:
                raise RuntimeError("authorization_window_expired")
            target = record["source"]["target_url"]
            findings, metadata = await execute_zap_baseline(target, run_id, expires_at)
            completed_at = datetime.now(timezone.utc).isoformat()
            result = {
                "status": "completed", "mode": "unauthenticated_passive_baseline",
                "started_by_user_id": user_id, "completed_at": completed_at,
                "target_url": target, "scope": record["source"]["authorization_scope"],
                "authorization_reference": record["source"]["authorization_reference"],
                "scanner": metadata, "finding_count": len(findings), "findings": findings,
                "limitations": ["Passive ZAP rules only; no exploit payloads, authentication, database access, or load testing were used.",
                                "This is automated evidence, not proof that the application is secure.",
                                "Review each alert and reproduce only within the approved scope."],
            }
            entry = await ledger_mod.append_to_ledger(db, "governance_studio_web_security_scan_completed", run_id, {
                "target_url": target, "scan_mode": result["mode"], "scanner": metadata,
                "finding_count": len(findings), "authorization_reference": record["source"]["authorization_reference"],
            })
            result["ledger"] = {"seq": entry["seq"], "hash": entry["hash"], "entry_id": entry["id"]}
            await db.studio_runs.update_one(
                {"id": run_id},
                {"$set": {"web_security_scan": result, "status": "partially_assessed",
                          "plan.$[step].state": "completed_passive_scan",
                          "plan.$[step].evidence": f"{len(findings)} OWASP ZAP passive alerts; ledger {entry['seq']}"}},
                array_filters=[{"step.id": "WEB-01"}],
            )
        except Exception as exc:
            logger.error("ZAP baseline failed for studio run %s (%s)", run_id, type(exc).__name__)
            failure = {"status": "failed", "queued_at": (record.get("web_security_scan") or {}).get("queued_at"),
                       "failed_at": datetime.now(timezone.utc).isoformat(),
                       "error": "Scanner request failed. Check scanner availability and backend logs.",
                       "error_code": type(exc).__name__, "mode": "unauthenticated_passive_baseline"}
            await db.studio_runs.update_one(
                {"id": run_id},
                {"$set": {"web_security_scan": failure,
                          "plan.$[step].state": "scanner_execution_failed",
                          "plan.$[step].evidence": "No scan findings recorded; inspect scanner availability before retrying."}},
                array_filters=[{"step.id": "WEB-01"}],
            )


def _track_web_scan_task(task):
    _web_scan_tasks.add(task)
    task.add_done_callback(_web_scan_tasks.discard)


@router.post("/runs/{run_id}/web-security-scan", status_code=202)
async def start_web_security_scan(run_id: str, user=Depends(auth.get_current_user)):
    """Queue a bounded, unauthenticated passive DAST crawl for an approved scope."""
    await auth.require_any_global_role(user, auth.GOVERNANCE_ROLES)
    if not _zap_enabled():
        raise HTTPException(503, "OWASP ZAP scanner is not configured for this deployment.")
    record = await db.studio_runs.find_one({"id": run_id}, {"_id": 0})
    if not record:
        raise HTTPException(404, "studio run not found")
    source = record.get("source") or {}
    if not source.get("target_url"):
        raise HTTPException(400, "Add a deployed application URL to this assessment first.")
    if not source.get("authorization_confirmed") or not all(str(source.get(k) or "").strip() for k in ("authorization_owner", "authorization_reference", "authorization_scope")):
        raise HTTPException(403, "Written authorization, owner, approval reference, and exact scope are required.")
    expires_at = datetime.fromisoformat(source["window_expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= expires_at:
        raise HTTPException(403, "The authorized assessment window has expired.")
    try:
        await validate_public_target(source["target_url"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    async with _web_scan_enqueue_lock:
        active = await db.studio_runs.find_one({"web_security_scan.status": {"$in": ["queued", "running"]}}, {"_id": 0, "id": 1})
        if active:
            raise HTTPException(409, "Another web security scan is already queued or running. Try again after it completes.")
        record = await db.studio_runs.find_one({"id": run_id}, {"_id": 0})
        previous = (record or {}).get("web_security_scan") or {}
        if previous.get("status") in ("queued", "running"):
            raise HTTPException(409, "A web security scan is already queued or running for this assessment.")
        last_scan = previous.get("completed_at") or previous.get("failed_at") or previous.get("queued_at")
        if last_scan:
            try:
                last_scan_at = datetime.fromisoformat(last_scan)
                if datetime.now(timezone.utc) - last_scan_at < timedelta(minutes=10):
                    raise HTTPException(429, "Wait ten minutes between repeated scans of the same assessment.")
            except ValueError:
                pass
        queued = {"status": "queued", "mode": "unauthenticated_passive_baseline",
                  "queued_at": datetime.now(timezone.utc).isoformat(), "started_by_user_id": user["id"]}
        await db.studio_runs.update_one({"id": run_id}, {"$set": {"web_security_scan": queued}})
    _track_web_scan_task(asyncio.create_task(_run_zap_for_record(run_id, record, user["id"])))
    return {"id": run_id, "web_security_scan": queued}


@router.post("/runs")
async def create_studio_run(payload: GovernanceStudioRunRequest, user=Depends(auth.get_current_user)):
    return await _create_studio_run(payload, user)


@router.post("/runs/upload")
async def create_studio_run_from_upload(
    name: str = Form(...),
    frs_file: UploadFile = File(...),
    github_url: str = Form(None),
    target_url: str = Form(None),
    authorization_confirmed: bool = Form(False),
    authorization_owner: str = Form(None),
    authorization_reference: str = Form(None),
    authorization_scope: str = Form(None),
    duration_hours: int = Form(2),
    runtime_logs: str = Form(None),
    user=Depends(auth.get_current_user),
):
    content = await frs_file.read(2_000_001)
    if len(content) > 2_000_000:
        raise HTTPException(413, "FRS upload is limited to 2 MB.")
    filename = (frs_file.filename or "").strip()
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    try:
        if extension in ("txt", "md"):
            frs_text = content.decode("utf-8-sig")
        elif extension == "docx":
            with zipfile.ZipFile(BytesIO(content)) as archive:
                if len(archive.infolist()) > 1000 or sum(item.file_size for item in archive.infolist()) > 20_000_000:
                    raise HTTPException(413, "Expanded DOCX content exceeds the 20 MB safety limit.")
            from docx import Document
            document = Document(BytesIO(content))
            parts = [paragraph.text for paragraph in document.paragraphs]
            parts.extend(" | ".join(cell.text for cell in row.cells) for table in document.tables for row in table.rows)
            frs_text = "\n".join(part for part in parts if part.strip())
        elif extension == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(content))
            if len(reader.pages) > 200:
                raise HTTPException(413, "PDF uploads are limited to 200 pages.")
            frs_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            raise HTTPException(415, "Upload an FRS in .txt, .md, .docx, or .pdf format.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Could not read the uploaded FRS: {type(exc).__name__}")
    if len(frs_text) > 2_000_000:
        raise HTTPException(413, "Extracted FRS text exceeds the 2 MB processing limit.")
    try:
        payload = GovernanceStudioRunRequest(
            name=name, github_url=github_url, target_url=target_url,
            authorization_confirmed=authorization_confirmed, authorization_owner=authorization_owner,
            authorization_reference=authorization_reference, authorization_scope=authorization_scope,
            duration_hours=duration_hours, frs_text=frs_text, frs_filename=filename, runtime_logs=runtime_logs,
        )
    except ValidationError as exc:
        raise HTTPException(422, detail="Invalid studio intake fields.") from exc
    return await _create_studio_run(payload, user)


@router.get("/runs")
async def list_studio_runs(user=Depends(auth.get_current_user)):
    await auth.require_any_global_role(user, auth.GOVERNANCE_ROLES)
    return await db.studio_runs.find({}, {"_id": 0, "requirements.text": 0}).sort("created_at", -1).to_list(100)


@router.get("/runs/{run_id}")
async def get_studio_run(run_id: str, user=Depends(auth.get_current_user)):
    await auth.require_any_global_role(user, auth.GOVERNANCE_ROLES)
    record = await db.studio_runs.find_one({"id": run_id}, {"_id": 0})
    if not record:
        raise HTTPException(404, "studio run not found")
    return record


@router.post("/runs/{run_id}/repository-audit")
async def run_studio_repository_audit(run_id: str, user=Depends(auth.get_current_user)):
    """Run the existing read-only deterministic source audit from a studio run."""
    await auth.require_any_global_role(user, auth.GOVERNANCE_ROLES)
    record = await db.studio_runs.find_one({"id": run_id}, {"_id": 0})
    if not record:
        raise HTTPException(404, "studio run not found")
    github_url = (record.get("source") or {}).get("github_url")
    if not github_url:
        raise HTTPException(400, "This studio run has no GitHub repository URL.")
    try:
        result = await repo_ingest.ingest_repo(db, github_url)
        project = result["project"]
        await auth.ensure_project_assignments(project["id"])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))

    audit = {
        "project_id": project["id"],
        "project_name": project.get("name"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "finding_summary": result.get("finding_summary"),
        "profile": {key: (result.get("profile") or {}).get(key) for key in ("languages", "frameworks", "code_files_scanned", "approx_loc")},
        "endpoint_count": (result.get("audit") or {}).get("endpoint_count", 0),
        "report_ids": [report.get("id") for report in result.get("reports", [])],
        "gate_summary": [{"id": gate.get("id"), "status": gate.get("status")} for gate in result.get("gates", [])],
        "execution": "read-only repository source scan; target runtime was not tested",
    }
    for step in record["plan"]:
        if step["id"] == "SEC-01":
            step["state"] = "completed_source_scan"
    ledger_entry = await ledger_mod.append_to_ledger(db, "governance_studio_repository_audit", run_id, {
        "project_id": audit["project_id"], "finding_count": (audit.get("finding_summary") or {}).get("total", 0),
        "source": github_url,
    })
    audit["ledger"] = {"seq": ledger_entry["seq"], "hash": ledger_entry["hash"], "entry_id": ledger_entry["id"]}
    await db.studio_runs.update_one({"id": run_id}, {"$set": {"repository_audit": audit, "plan": record["plan"], "status": "partially_assessed"}})
    record["repository_audit"] = audit
    record["status"] = "partially_assessed"
    return record
