from fastapi import APIRouter, HTTPException, Query, Depends, Response
from typing import Optional
from uuid import uuid4
from datetime import datetime, timezone

from database import db
from models import EventSimulateRequest, TriageDecisionRequest, AdjudicationDecisionRequest
import engine
import ledger as ledger_mod
import auth
from pagination import paged

router = APIRouter()


@router.get("/events")
async def list_events(response: Response, project_id: str = Query(...), page: int = 1, page_size: int = 200):
    return await paged(db.events, {"project_id": project_id}, [("created_at", -1)], response, page, page_size)


@router.post("/events/simulate")
async def simulate_event(payload: EventSimulateRequest, user=Depends(auth.get_current_user)):
    await auth.require_project_role(user, payload.project_id, payload.role)
    try:
        result = await engine.run_event(db, payload.project_id, payload.event_type,
                                        payload.source_ref, triggered_by=user["name"])
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/findings")
async def list_findings(response: Response, project_id: str = Query(...), control_id: Optional[str] = None,
                         severity: Optional[str] = None, verdict: Optional[str] = None,
                         tag: Optional[str] = None, status: Optional[str] = None,
                         module: Optional[str] = None, zone: Optional[str] = None, search: Optional[str] = None,
                         page: int = 1, page_size: int = 200):
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
    if module:
        q["module"] = module
    if zone:
        q["zone"] = zone
    if search:
        import re as _re
        rx = {"$regex": _re.escape(search), "$options": "i"}
        q["$or"] = [{"reason": rx}, {"subject_ref": rx}, {"control_name": rx}]
    return await paged(db.findings, q, [("created_at", -1)], response, page, page_size)


@router.get("/findings/{finding_id}")
async def get_finding(finding_id: str):
    f = await db.findings.find_one({"id": finding_id}, {"_id": 0})
    if not f:
        raise HTTPException(404, "finding not found")
    return f


@router.post("/findings/{finding_id}/triage")
async def triage_finding(finding_id: str, payload: TriageDecisionRequest,
                         user=Depends(auth.get_current_user)):
    finding = await db.findings.find_one({"id": finding_id}, {"_id": 0})
    if not finding:
        raise HTTPException(404, "finding not found")
    await auth.require_project_role(user, finding["project_id"], payload.role)
    await auth.enforce_segregation(user, finding)
    new_status = {"accept": "triaged_accepted", "dismiss": "triaged_dismissed",
                  "escalate": "escalated", "defer": "triaged_deferred"}[payload.decision]
    await db.findings.update_one({"id": finding_id}, {"$set": {"status": new_status}})
    decision = {
        "id": str(uuid4()), "finding_id": finding_id, "project_id": finding["project_id"],
        "decision": payload.decision, "role": payload.role, "decided_by_role": payload.role,
        "decided_by_user_id": user["id"], "decided_by_user_name": user["name"],
        "reason": payload.reason or "", "notes": payload.notes or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.triage_decisions.insert_one(dict(decision))
    await ledger_mod.append_to_ledger(db, "triage_decision", decision["id"],
                                      {"finding_id": finding_id, "decision": payload.decision,
                                       "user_id": user["id"], "role": payload.role})
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
async def list_adjudications(response: Response, project_id: str = Query(...), page: int = 1, page_size: int = 200):
    return await paged(db.adjudications, {"project_id": project_id}, [("created_at", -1)], response, page, page_size)


@router.post("/adjudications/{adjudication_id}/decide")
async def decide_adjudication(adjudication_id: str, payload: AdjudicationDecisionRequest,
                              user=Depends(auth.get_current_user)):
    adj = await db.adjudications.find_one({"id": adjudication_id}, {"_id": 0})
    if not adj:
        raise HTTPException(404, "adjudication not found")
    await auth.require_project_role(user, adj["project_id"], payload.role)
    finding = await db.findings.find_one({"id": adj["finding_id"]}, {"_id": 0})
    if finding:
        await auth.enforce_segregation(user, finding)
    await db.adjudications.update_one({"id": adjudication_id}, {"$set": {
        "human_decision": payload.human_decision, "role": payload.role,
        "decided_by_role": payload.role, "decided_by_user_id": user["id"],
        "decided_by_user_name": user["name"], "notes": payload.notes or "",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }})
    final_status = {"agree_l1": "resolved_agree_l1", "agree_l2": "resolved_agree_l2",
                    "override": "resolved_human_override"}.get(payload.human_decision, "resolved")
    await db.findings.update_one({"id": adj["finding_id"]}, {"$set": {"level2_status": final_status}})
    await ledger_mod.append_to_ledger(db, "adjudication", adjudication_id,
                                      {"finding_id": adj["finding_id"], "human_decision": payload.human_decision,
                                       "user_id": user["id"], "role": payload.role})
    return await db.adjudications.find_one({"id": adjudication_id}, {"_id": 0})
