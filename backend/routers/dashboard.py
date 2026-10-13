from fastapi import APIRouter, Query
from typing import Optional

from database import db
import engine
import ledger as ledger_mod

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard(project_id: Optional[str] = Query(None)):
    q = {"project_id": project_id} if project_id else {}
    async def group(field):
        return {d["_id"]: d["n"] async for d in db.findings.aggregate(
            [{"$match": q}, {"$group": {"_id": "$" + field, "n": {"$sum": 1}}}]) if d["_id"] is not None}

    severity_counts, verdict_counts = await group("severity"), await group("verdict")
    total_findings = await db.findings.count_documents(q)
    trend = {}
    async for d in db.events.aggregate([{"$match": q}, {"$group": {"_id": {"$substr": ["$created_at", 0, 10]}, "n": {"$sum": 1}}}]):
        trend[d["_id"]] = d["n"]
    trend_series = [{"date": k, "events": v} for k, v in sorted(trend.items())]

    triage_queue_count = await db.findings.count_documents({**q, "status": "open", "verdict": "FAIL"})
    ledger_status = await ledger_mod.verify_cached(db)

    coverage_pct = None
    if project_id:
        trace = await engine.compute_traceability(db, project_id)
        coverage_pct = trace["coverage_pct"]
    else:
        projects = await db.projects.find({}, {"_id": 0}).to_list(5000)
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
        "total_findings": total_findings,
    }
