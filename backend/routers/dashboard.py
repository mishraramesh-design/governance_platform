from fastapi import APIRouter, Query
from typing import Optional

from database import db
import engine
import ledger as ledger_mod

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard(project_id: Optional[str] = Query(None)):
    q = {"project_id": project_id} if project_id else {}
    findings = await db.findings.find(q, {"_id": 0}).to_list(5000)

    severity_counts, verdict_counts = {}, {}
    for f in findings:
        severity_counts[f["severity"]] = severity_counts.get(f["severity"], 0) + 1
        verdict_counts[f["verdict"]] = verdict_counts.get(f["verdict"], 0) + 1

    events = await db.events.find(q, {"_id": 0}).sort("created_at", 1).to_list(5000)
    trend = {}
    for e in events:
        day = e["created_at"][:10]
        trend[day] = trend.get(day, 0) + 1
    trend_series = [{"date": k, "events": v} for k, v in sorted(trend.items())]

    triage_queue_count = await db.findings.count_documents({**q, "status": "open", "verdict": "FAIL"})
    ledger_status = await ledger_mod.verify_integrity(db)

    coverage_pct = None
    if project_id:
        trace = await engine.compute_traceability(db, project_id)
        coverage_pct = trace["coverage_pct"]
    else:
        projects = await db.projects.find({}, {"_id": 0}).to_list(1000)
        if projects:
            total = 0
            for p in projects:
                trace = await engine.compute_traceability(db, p["id"])
                total += trace["coverage_pct"]
            coverage_pct = round(total / len(projects))

    total_projects = await db.projects.count_documents({})
    total_agents = await db.agents.count_documents({})
    total_controls = await db.controls.count_documents({})
    pending_adjudications = await db.adjudications.count_documents({**({"project_id": project_id} if project_id else {}), "human_decision": None})

    return {
        "severity_counts": severity_counts, "verdict_counts": verdict_counts, "trend": trend_series,
        "traceability_coverage_pct": coverage_pct, "triage_queue_count": triage_queue_count,
        "ledger_status": ledger_status, "total_projects": total_projects, "total_agents": total_agents,
        "total_controls": total_controls, "pending_adjudications": pending_adjudications,
        "total_findings": len(findings),
    }
