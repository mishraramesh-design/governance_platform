"""Deterministic Harness API: agent personas, two-level model, capability
profiles, Zero-LLM toggle, a live sandbox and the llm_calls audit log."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from database import db
import gateway
import agent_profiles

router = APIRouter(prefix="/harness")


class ConfigUpdate(BaseModel):
    capability_profiles: dict
    zero_llm_mode: bool = False


class SandboxRun(BaseModel):
    agent_id: str
    masked_input: str
    level: int = 1


@router.get("/agents")
async def list_agents():
    classes = {}
    for a in agent_profiles.AGENT_LIST:
        classes[a["agent_class"]] = classes.get(a["agent_class"], 0) + 1
    return {
        "agents": agent_profiles.AGENT_LIST,
        "summary": {
            "total": len(agent_profiles.AGENT_LIST),
            "by_class": classes,
            "llm_agents": sum(1 for a in agent_profiles.AGENT_LIST if a["uses_llm"]),
            "deterministic_agents": sum(1 for a in agent_profiles.AGENT_LIST if not a["uses_llm"]),
        },
    }


@router.get("/two-level-model")
async def two_level_model():
    rows = []
    for row in agent_profiles.TWO_LEVEL_MODEL:
        l1 = agent_profiles.get_agent(row["l1"])
        l2 = agent_profiles.get_agent(row["l2"])
        rows.append({
            **row,
            "l1_name": l1["name"] if l1 else row["l1"],
            "l2_name": l2["name"] if l2 else row["l2"],
        })
    return rows


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = agent_profiles.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "agent not found")
    return agent


@router.get("/config")
async def get_config():
    cfg = await gateway.get_config(db)
    key_mode = "emergent_universal" if gateway.EMERGENT_LLM_KEY else ("openai_only" if gateway.OPENAI_API_KEY else "none")
    return {
        "capability_profiles": cfg["capability_profiles"],
        "zero_llm_mode": cfg["zero_llm_mode"],
        "available_models": gateway.AVAILABLE_MODELS,
        "key_mode": key_mode,
    }


@router.put("/config")
async def put_config(body: ConfigUpdate):
    profiles = dict(body.capability_profiles or {})
    for name, prof in profiles.items():
        if name == "none" or prof is None:
            profiles[name] = None
            continue
        provider = prof.get("provider")
        model = prof.get("model")
        if provider not in gateway.AVAILABLE_MODELS:
            raise HTTPException(400, f"unknown provider '{provider}' for profile '{name}'")
        if model not in gateway.AVAILABLE_MODELS[provider]:
            raise HTTPException(400, f"model '{model}' not available for provider '{provider}'")
        profiles[name] = {"provider": provider, "model": model}
    # keep the 'none' profile present
    profiles.setdefault("none", None)
    saved = await gateway.save_config(db, profiles, body.zero_llm_mode)
    return {"capability_profiles": saved["capability_profiles"], "zero_llm_mode": saved["zero_llm_mode"]}


@router.post("/sandbox")
async def sandbox(body: SandboxRun):
    if body.level not in (1, 2):
        raise HTTPException(400, "level must be 1 or 2")
    result = await gateway.complete_agent(body.agent_id, "sandbox_assessment", body.masked_input, body.level, db=db)
    return result


@router.get("/llm-calls")
async def llm_calls(limit: int = 50):
    calls = await db.llm_calls.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    total = await db.llm_calls.count_documents({})
    return {"calls": calls, "total": total}
