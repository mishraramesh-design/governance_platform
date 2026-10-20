"""Deterministic Harness API: agent personas, four-role capability model
(maker/checker/security/verifier), on-prem/custom endpoints, Zero-LLM toggle,
a live sandbox, the agent-flow graph and the llm_calls audit log."""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from database import db
import gateway
import agent_profiles
import auth

router = APIRouter(prefix="/harness")

_SECRET = "__stored__"  # placeholder returned instead of a real key


class ConfigUpdate(BaseModel):
    capability_profiles: dict
    project_id: str | None = None
    zero_llm_mode: bool = False
    max_llm_calls_per_run: int = Field(default=2, ge=0, le=100)
    sovereignty: dict | None = None


class SandboxRun(BaseModel):
    agent_id: str
    masked_input: str
    project_id: str | None = None
    level: int = 1
    tier: str | None = None


@router.get("/agents")
async def list_agents():
    by_class, by_role = {}, {}
    for a in agent_profiles.AGENT_LIST:
        by_class[a["agent_class"]] = by_class.get(a["agent_class"], 0) + 1
        by_role[a["harness_role"]] = by_role.get(a["harness_role"], 0) + 1
    return {
        "agents": agent_profiles.AGENT_LIST,
        "roles": agent_profiles.HARNESS_ROLES,
        "summary": {
            "total": len(agent_profiles.AGENT_LIST), "by_class": by_class, "by_role": by_role,
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
        rows.append({**row, "l1_name": l1["name"] if l1 else row["l1"],
                     "l2_name": l2["name"] if l2 else row["l2"],
                     "l1_role": l1["harness_role"] if l1 else None,
                     "l2_role": l2["harness_role"] if l2 else None})
    return rows


@router.get("/flow")
async def agent_flow(project_id: str | None = Query(None)):
    """Agent-flow graph: event triggers -> L1 agents (by role) -> L2 reviewers -> human gates."""
    cfg = await gateway.get_config(db, project_id)
    role_model = {r: (p and f"{p['provider']}/{p['model']}") for r, p in cfg["capability_profiles"].items()}
    nodes = []
    for a in agent_profiles.AGENT_LIST:
        nodes.append({
            "id": a["id"], "name": a["name"], "stage": a["stage"],
            "role": a["harness_role"], "uses_llm": a["uses_llm"],
            "l2_agent_id": a["l2_agent_id"], "model": role_model.get(a["harness_role"]),
        })
    edges = [{"from": a["id"], "to": a["l2_agent_id"]} for a in agent_profiles.AGENT_LIST if a["l2_agent_id"]]
    return {"nodes": nodes, "edges": edges, "roles": agent_profiles.HARNESS_ROLES,
            "role_model": role_model, "project_id": project_id,
            "max_llm_calls_per_run": cfg["max_llm_calls_per_run"]}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = agent_profiles.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "agent not found")
    return agent


def _public_profile(prof):
    if not prof:
        return None
    p = dict(prof)
    has_key = bool(p.get("api_key"))
    p["api_key"] = _SECRET if has_key else ""
    p["api_key_set"] = has_key
    return p


@router.get("/config")
async def get_config(project_id: str | None = Query(None)):
    cfg = await gateway.get_config(db, project_id)
    profiles = {k: _public_profile(v) for k, v in cfg["capability_profiles"].items()}
    return {
        "capability_profiles": profiles,
        "zero_llm_mode": cfg["zero_llm_mode"],
        "max_llm_calls_per_run": cfg["max_llm_calls_per_run"],
        "project_id": project_id,
        "sovereignty": cfg["sovereignty"],
        "available_models": gateway.AVAILABLE_MODELS,
        "providers": list(gateway.AVAILABLE_MODELS.keys()),
        "roles": agent_profiles.HARNESS_ROLES,
        "emergent_key_available": bool(gateway.EMERGENT_LLM_KEY),
    }


@router.put("/config")
async def put_config(body: ConfigUpdate):
    current = await gateway.get_config(db, body.project_id)
    incoming = dict(body.capability_profiles or {})
    result = {}
    for name in agent_profiles.HARNESS_ROLES:
        prof = incoming.get(name)
        if prof is None:
            result[name] = current["capability_profiles"].get(name)
            continue
        provider = prof.get("provider")
        model = (prof.get("model") or "").strip()
        if provider not in gateway.AVAILABLE_MODELS:
            raise HTTPException(400, f"unknown provider '{provider}' for role '{name}'")
        if provider == "custom":
            if not (prof.get("base_url") or "").strip():
                raise HTTPException(400, f"role '{name}': custom provider needs a base_url")
            if not model:
                raise HTTPException(400, f"role '{name}': custom provider needs a model name")
        elif model not in gateway.AVAILABLE_MODELS[provider]:
            raise HTTPException(400, f"model '{model}' not available for provider '{provider}'")
        # key: '__clear__' wipes the stored key (revert to Emergent); '' or placeholder keeps it
        incoming_key = prof.get("api_key") or ""
        old = current["capability_profiles"].get(name) or {}
        if incoming_key == "__clear__":
            key = ""
        elif incoming_key in ("", _SECRET):
            key = old.get("api_key", "")
        else:
            key = incoming_key
        result[name] = {
            "provider": provider, "model": model, "api_key": key,
            "base_url": (prof.get("base_url") or "").strip(),
            "local_only": bool(prof.get("local_only", False)),
        }
    result["none"] = None
    saved = await gateway.save_config(db, result, body.zero_llm_mode, body.sovereignty,
                                      body.max_llm_calls_per_run, project_id=body.project_id)
    return {"capability_profiles": {k: _public_profile(v) for k, v in saved["capability_profiles"].items()},
            "zero_llm_mode": saved["zero_llm_mode"], "max_llm_calls_per_run": saved["max_llm_calls_per_run"],
            "sovereignty": saved["sovereignty"], "project_id": body.project_id}


@router.post("/sandbox")
async def sandbox(body: SandboxRun):
    if body.level not in (1, 2):
        raise HTTPException(400, "level must be 1 or 2")
    return await gateway.complete_agent(body.agent_id, "sandbox_assessment", body.masked_input, body.level,
                                        db=db, tier=body.tier, project_id=body.project_id)


@router.get("/llm-calls")
async def llm_calls(limit: int = 50, project_id: str | None = Query(None)):
    q = {"project_id": project_id} if project_id else {}
    calls = await db.llm_calls.find(q, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    total = await db.llm_calls.count_documents(q)
    return {"calls": calls, "total": total}
