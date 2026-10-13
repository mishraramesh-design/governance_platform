from uuid import uuid4
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Depends, Response
from fastapi.responses import HTMLResponse

from database import db
from models import ArtifactGenerateRequest
import engine
import ledger as ledger_mod
import auth
from pagination import paged

router = APIRouter()


def render_html(title: str, subtitle: str, sections, ledger_hash: str = None, timestamp: str = None):
    body = f"<h1 style='font-family:Chivo,sans-serif;color:#111'>{title}</h1>"
    body += f"<p style='color:#555'>{subtitle}</p>"
    if timestamp:
        body += f"<p style='font-size:12px;color:#888'>Generated: {timestamp}</p>"
    if ledger_hash:
        body += f"<p style='font-family:monospace;font-size:12px;background:#111;color:#FFE600;padding:6px 10px;display:inline-block'>Ledger Hash: {ledger_hash}</p>"
    body += "<div style='display:inline-flex;gap:6px;align-items:center;background:#111;color:#FFE600;padding:4px 10px;border-radius:999px;font-size:11px;font-weight:bold;text-transform:uppercase;margin:12px 0'>Read-only &middot; Advisory</div>"
    for s in sections:
        body += f"<h3 style='font-family:Chivo,sans-serif;border-bottom:1px solid #E2E2E6;padding-bottom:4px'>{s['heading']}</h3>"
        body += "<ul style='font-family:IBM Plex Sans,sans-serif;font-size:14px;color:#222'>"
        for line in s.get("body", []):
            body += f"<li style='margin-bottom:4px'>{line}</li>"
        body += "</ul>"
    return f"<html><head><meta charset='utf-8'><title>{title}</title></head><body style='padding:32px;max-width:860px;margin:0 auto'>{body}</body></html>"


@router.get("/reports")
async def list_reports(response: Response, project_id: str = Query(...), type: str = None, page: int = 1, page_size: int = 100):
    q = {"project_id": project_id}
    if type:
        q["type"] = type
    return await paged(db.reports, q, [("created_at", -1)], response, page, page_size)


@router.get("/reports/{report_id}")
async def get_report(report_id: str):
    r = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not r:
        raise HTTPException(404, "report not found")
    return r


@router.get("/reports/{report_id}/download")
async def download_report(report_id: str):
    r = await db.reports.find_one({"id": report_id}, {"_id": 0})
    if not r:
        raise HTTPException(404, "report not found")
    sections = [{"heading": "Narrative Summary", "body": [r["narrative"]]}] + r["sections"]
    html = render_html(r["title"], f"Type: {r['type']} &middot; Findings covered: {r['finding_count']}", sections, r.get("ledger_hash"), r["created_at"])
    return HTMLResponse(content=html, headers={"Content-Disposition": f"attachment; filename=report_{report_id}.html"})


@router.get("/traceability")
async def get_traceability(project_id: str = Query(...)):
    return await engine.compute_traceability(db, project_id)


ARTIFACT_TITLES = {
    "rtm": "Requirements Traceability Matrix",
    "verification_summary": "Verification Summary",
    "defect_log": "Defect / Finding Log",
    "gate_readiness": "Gate Readiness Assessment",
    "data_protection_summary": "Data Protection Findings Summary",
    "metrics_summary": "Metrics Summary",
}


@router.post("/artifacts/generate")
async def generate_artifact(payload: ArtifactGenerateRequest, user=Depends(auth.get_current_user)):
    project = await db.projects.find_one({"id": payload.project_id}, {"_id": 0})
    if not project:
        raise HTTPException(404, "project not found")
    await auth.require_member(user, payload.project_id)
    artifact_type = payload.artifact_type
    if artifact_type not in ARTIFACT_TITLES:
        raise HTTPException(400, "unknown artifact_type")

    sections = []
    if artifact_type == "rtm":
        trace = await engine.compute_traceability(db, payload.project_id)
        sections.append({"heading": f"Coverage: {trace['coverage_pct']}%", "body": [
            f"{r['requirement_id']}: design={r['design_ids']} commit={r['commit_ids']} test={r['test_ids']} complete={r['trace_complete']}" for r in trace["rows"]
        ]})
    elif artifact_type == "verification_summary":
        findings = await db.findings.find({"project_id": payload.project_id}, {"_id": 0}).to_list(None)
        counts = {}
        for f in findings:
            counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1
        sections.append({"heading": "Verdict Totals", "body": [f"{k}: {v}" for k, v in counts.items()]})
    elif artifact_type == "defect_log":
        findings = await db.findings.find({"project_id": payload.project_id, "verdict": "FAIL"}, {"_id": 0}).to_list(None)
        sections.append({"heading": "Open / Historical FAIL Findings", "body": [f"[{f['severity']}] {f['control_name']}: {f['reason']}" for f in findings]})
    elif artifact_type == "gate_readiness":
        gates = await engine.compute_gate_status(db, payload.project_id)
        sections.append({"heading": "Gate Status", "body": [f"{g['id']} {g['name']}: {g['status']} - {g['reason']}" for g in gates]})
    elif artifact_type == "data_protection_summary":
        findings = await db.findings.find({"project_id": payload.project_id, "tags": "privacy"}, {"_id": 0}).to_list(None)
        sections.append({"heading": "Privacy / DPDP-tagged Findings", "body": [f"[{f['verdict']}] {f['control_name']}: {f['reason']}" for f in findings] or ["No privacy findings recorded."]})
    elif artifact_type == "metrics_summary":
        total_findings = await db.findings.count_documents({"project_id": payload.project_id})
        open_fail = await db.findings.count_documents({"project_id": payload.project_id, "verdict": "FAIL", "status": "open"})
        trace = await engine.compute_traceability(db, payload.project_id)
        sections.append({"heading": "Key Metrics", "body": [
            f"Total findings: {total_findings}", f"Open FAIL findings: {open_fail}", f"Traceability coverage: {trace['coverage_pct']}%",
        ]})

    artifact = {
        "id": str(uuid4()), "project_id": payload.project_id, "type": artifact_type,
        "title": f"{ARTIFACT_TITLES[artifact_type]} - {project['name']}", "sections": sections,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    entry = await ledger_mod.append_to_ledger(db, "artifact", artifact["id"], {"artifact_type": artifact_type, "project_id": payload.project_id})
    artifact["ledger_hash"] = entry["hash"]
    await db.artifacts.insert_one(dict(artifact))
    artifact.pop("_id", None)
    return artifact


@router.get("/artifacts")
async def list_artifacts(response: Response, project_id: str = Query(...), page: int = 1, page_size: int = 100):
    return await paged(db.artifacts, {"project_id": project_id}, [("created_at", -1)], response, page, page_size)


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(artifact_id: str):
    a = await db.artifacts.find_one({"id": artifact_id}, {"_id": 0})
    if not a:
        raise HTTPException(404, "artifact not found")
    html = render_html(a["title"], "CMMI-style governance artifact, generated from live evidence.", a["sections"], a.get("ledger_hash"), a["created_at"])
    return HTMLResponse(content=html, headers={"Content-Disposition": f"attachment; filename=artifact_{artifact_id}.html"})
