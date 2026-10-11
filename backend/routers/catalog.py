from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from database import db
import engine

router = APIRouter()


@router.get("/agents")
async def list_agents():
    return await db.agents.find({}, {"_id": 0}).to_list(1000)


@router.get("/controls")
async def list_controls():
    return await db.controls.find({}, {"_id": 0}).to_list(1000)


@router.get("/gates")
async def get_gates(project_id: str = Query(...)):
    gates = await engine.compute_gate_status(db, project_id)
    if not gates:
        raise HTTPException(404, "project not found")
    return gates


@router.get("/ai-governance")
async def list_ai_governance():
    controls = await db.ai_governance.find({}, {"_id": 0}).to_list(1000)
    llm_calls_count = await db.llm_calls.count_documents({})
    model_eval_count = await db.findings.count_documents({"control_id": "CTRL-18"})
    return {"controls": controls, "llm_calls_count": llm_calls_count, "model_eval_findings_count": model_eval_count}
