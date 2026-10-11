from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from database import db
from models import EventSimulateRequest, TriageDecisionRequest, AdjudicationDecisionRequest
import engine
import ledger as ledger_mod

router = APIRouter()


@router.get("/events")
async def list_events(project_id: str = Query(...)):
    return await db.events.find({"project_id": project_id}, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.post("/events/simulate")
async def simulate_event(payload: EventSimulateRequest):
    try:
        result = await engine.run_event(db, payload.project_id, payload.event_type, payload.source_ref, payload.triggered_by or "system")
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/findings")
async def list_findings(project_id: str = Query(...), control_id: Optional[str] = None,
                         severity: Optional[str] = None, verdict: Optional[str] = None,
                         tag: Optional[str] = None, status: Optional[str] = None):
    q = {"project_id": project_id}
    if control_id:
        q["control_id"] = control_id
    if severity:
        q["severity"] = severity
    if verdict:
        q["verdict"] = verdict
    if tag:
        q["tags"] = tag
    if status:
        q["status"] = status
    return await db.findings.find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)


@router.get("/findings/{finding_id}")
async def get_finding(finding_id: str):
    f = await db.findings.find_one({"id": finding_id}, {"_id": 0})
    if not f:
        raise HTTPException(404, "finding not found")
    return f


@router.post("/findings/{finding_id}/triage")
async def triage_finding(finding_id: str, payload: TriageDecisionRequest):
    finding = await db.findings.find_one({"id": finding_id}, {"_id": 0})
    if not finding:
        raise HTTPException(404, "finding not found")
    new_status = {"accept": "triaged_accepted", "dismiss": "triaged_dismissed", "escalate": "escalated"}.get(payload.decision, "triaged")
    await db.findings.update_one({"id": finding_id}, {"$set": {"status": new_status}})
    from uuid import uuid4
    from datetime import datetime, timezone
    decision = {
        "id": str(uuid4()), "finding_id": finding_id, "decision": payload.decision,
        "decided_by_role": payload.decided_by_role, "notes": payload.notes or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.triage_decisions.insert_one(decision)
    await ledger_mod.append_to_ledger(db, "triage_decision", decision["id"], {"finding_id": finding_id, "decision": payload.decision})
    decision.pop("_id", None)
    return decision


@router.post("/findings/{finding_id}/evidence/{evidence_index}/fetch-live")
async def fetch_live_evidence(finding_id: str, evidence_index: int):
    finding = await db.findings.find_one({"id": finding_id}, {"_id": 0})
    if not finding:
        raise HTTPException(404, "finding not found")
    evidence = finding.get("evidence", [])
    if evidence_index < 0 or evidence_index >= len(evidence):
        raise HTTPException(404, "evidence item not found")
    return {
        "message": "Fetch live from source is disabled in this prototype. Displaying stored masked evidence only.",
        "masked_evidence": evidence[evidence_index],
    }


@router.get("/adjudications")
async def list_adjudications(project_id: str = Query(...)):
    return await db.adjudications.find({"project_id": project_id}, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/adjudications/{adjudication_id}/decide")
async def decide_adjudication(adjudication_id: str, payload: AdjudicationDecisionRequest):
    adj = await db.adjudications.find_one({"id": adjudication_id}, {"_id": 0})
    if not adj:
        raise HTTPException(404, "adjudication not found")
    await db.adjudications.update_one({"id": adjudication_id}, {"$set": {
        "human_decision": payload.human_decision, "decided_by_role": payload.decided_by_role, "notes": payload.notes or "",
    }})
    final_status = {"agree_l1": "resolved_agree_l1", "agree_l2": "resolved_agree_l2", "override": "resolved_human_override"}.get(payload.human_decision, "resolved")
    await db.findings.update_one({"id": adj["finding_id"]}, {"$set": {"level2_status": final_status}})
    await ledger_mod.append_to_ledger(db, "adjudication", adjudication_id, {"finding_id": adj["finding_id"], "human_decision": payload.human_decision})
    return await db.adjudications.find_one({"id": adjudication_id}, {"_id": 0})
