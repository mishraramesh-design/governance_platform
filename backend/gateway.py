"""Model-agnostic LLM gateway for the Deterministic Harness.

Capability roles (maker / checker / security / verifier) are configurable per
deployment and may each point at a cloud provider (OpenAI / Anthropic / Gemini,
via the Emergent universal key or a user-supplied key) OR an on-prem,
OpenAI-COMPATIBLE endpoint (custom base_url + key). Each role also carries a
"local_only" flag that forbids any external call.

Every agent is mapped to one role; L1 runs through the agent's role, L2 runs
through the paired reviewer agent's role. Only MASKED input is ever sent, and
every call is logged to `llm_calls` (hashes + latency, never raw text).
"""
import os
import time
import hashlib
import logging
from uuid import uuid4
from datetime import datetime, timezone
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from dotenv import load_dotenv
from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone
from openai import AsyncOpenAI

import agent_profiles

load_dotenv()
logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Set True by the seeder so bulk demo generation stays fast and free (deterministic).
FORCE_ZERO_LLM = False

CLOUD_PROVIDERS = ("openai", "anthropic", "gemini")

AVAILABLE_MODELS = {
    "openai": ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-4.1"],
    "anthropic": ["claude-sonnet-5-5", "claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5-20251001"],
    "gemini": ["gemini-3.1-pro-preview", "gemini-3-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
    "custom": [],  # on-prem / OpenAI-compatible: model name is free text
}

# Default four-role config. Each role is a distinct family for separation of duties.
def _prof(provider, model):
    return {"provider": provider, "model": model, "api_key": "", "base_url": "", "local_only": False}

DEFAULT_CONFIG = {
    "capability_profiles": {
        "maker": _prof("openai", "gpt-5.6-terra"),
        "checker": _prof("anthropic", "claude-sonnet-5-5"),
        "security": _prof("gemini", "gemini-3.1-pro-preview"),
        "verifier": _prof("openai", "gpt-5.4"),
        "none": None,
    },
    "zero_llm_mode": False,
    # A run-level call ceiling is a predictable cost guard. Deterministic controls
    # remain available after the ceiling is reached; model-only work becomes unassessed.
    "max_llm_calls_per_run": 2,
    # Data-sovereignty: tiers mapped True must stay on-prem (custom provider only).
    "sovereignty": {"T0": True, "T1": True, "T2": False, "T3": False, "T4": False},
}

SYSTEM_PROMPTS = {
    "requirement_rewrite": (
        "You are the Requirements Quality Agent inside an SDLC governance & assurance platform. "
        "You OBSERVE and ADVISE only. Given a masked requirement and its ambiguity issues, suggest one "
        "crisp rewritten requirement that is testable and measurable. 2-3 sentences, no preamble."
    ),
    "author_report_narrative": (
        "You write the opening narrative of an AUTHOR REPORT in an SDLC governance platform. Plain, "
        "constructive, advisory-only. You OBSERVE and ADVISE. 2-3 sentences max."
    ),
    "team_lead_report_narrative": (
        "You write the executive summary of a TEAM LEAD REPORT. Concise, factual, trend-aware, "
        "advisory-only. Humans decide. 3-4 sentences max."
    ),
    "l2_independent_review": (
        "You are an INDEPENDENT Level-2 reviewer using a different model family than Level-1. Given a "
        "Level-1 finding summary, reply AGREE or DISAGREE plus a one-line justification. Be skeptical."
    ),
}

_ZERO_LLM_TASK_TEXT = {
    "requirement_rewrite": "Zero-LLM mode (rule-based): restate as 'The system shall <action> <object> within <measurable condition>.' Remove ambiguous terms; add a measurable acceptance threshold.",
    "author_report_narrative": "Zero-LLM mode: deterministic, rule-generated summary of findings attributed to your work. Review and remediate as advised. Advisory only.",
    "team_lead_report_narrative": "Zero-LLM mode: deterministic team-level summary. See severity/verdict breakdown for prioritisation. Advisory only.",
    "l2_independent_review": "NOT ASSESSED: no independent reviewer model was available and deterministic recomputation was not performed.",
}


def _config_id(project_id=None):
    return f"project:{project_id}" if project_id else "default"


async def get_config(db=None, project_id: str = None) -> dict:
    if db is None:
        return DEFAULT_CONFIG
    doc = await db.harness_config.find_one({"id": _config_id(project_id)}, {"_id": 0})
    if not doc and project_id:
        doc = await db.harness_config.find_one({"id": "default"}, {"_id": 0})
    if not doc:
        return DEFAULT_CONFIG
    profiles = {**DEFAULT_CONFIG["capability_profiles"], **(doc.get("capability_profiles") or {})}
    sovereignty = {**DEFAULT_CONFIG["sovereignty"], **(doc.get("sovereignty") or {})}
    return {"capability_profiles": profiles, "zero_llm_mode": bool(doc.get("zero_llm_mode", False)),
            "max_llm_calls_per_run": max(0, min(100, int(doc.get("max_llm_calls_per_run", DEFAULT_CONFIG["max_llm_calls_per_run"])))),
            "sovereignty": sovereignty}


async def save_config(db, capability_profiles: dict, zero_llm_mode: bool, sovereignty: dict = None,
                      max_llm_calls_per_run: int = None, project_id: str = None) -> dict:
    config_id = _config_id(project_id)
    current = await get_config(db, project_id)
    doc = {"id": config_id, "project_id": project_id, "capability_profiles": capability_profiles,
           "zero_llm_mode": bool(zero_llm_mode),
           "max_llm_calls_per_run": (max(0, min(100, int(max_llm_calls_per_run)))
                                     if max_llm_calls_per_run is not None
                                     else current["max_llm_calls_per_run"]),
           "sovereignty": sovereignty if sovereignty is not None else current["sovereignty"],
           "updated_at": datetime.now(timezone.utc).isoformat()}
    await db.harness_config.update_one({"id": config_id}, {"$set": doc}, upsert=True)
    return doc


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


async def _log_call(db, record: dict):
    if db is not None:
        try:
            await db.llm_calls.insert_one(dict(record))
        except Exception as e:
            logger.error(f"llm_calls logging failed: {e}")


async def _reserve_run_call(db, run_id: str, limit: int) -> bool:
    """Atomically reserve model-call budget so parallel agents cannot overspend it."""
    if limit <= 0:
        return False
    try:
        reservation = await db.llm_run_budgets.find_one_and_update(
            {"_id": run_id, "calls_reserved": {"$lt": limit}},
            {"$inc": {"calls_reserved": 1},
             "$setOnInsert": {"run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return reservation is not None
    except DuplicateKeyError:
        # The existing budget document reached its cap between the query and upsert.
        return False


def _runnable(profile: dict):
    """Return (ok, mode_if_not_ok, key, reason). Decides whether a real call can run."""
    if profile is None:
        return False, "zero-llm", None, "profile 'none'"
    provider = profile.get("provider")
    if profile.get("local_only") and provider in CLOUD_PROVIDERS:
        return False, "local-only-blocked", None, "local-only forbids external cloud calls"
    if provider == "custom":
        if not profile.get("base_url"):
            return False, "zero-llm", None, "custom provider missing base_url"
        return True, None, profile.get("api_key") or "sk-local", None
    # cloud provider
    key = profile.get("api_key") or EMERGENT_LLM_KEY or (OPENAI_API_KEY if provider == "openai" else None)
    if not key:
        return False, "zero-llm", None, "no api key"
    return True, None, key, None


async def _run_llm(system_message: str, masked_input: str, profile: dict, key: str, session_tag: str) -> str:
    provider = profile["provider"]
    model = profile["model"]
    if provider == "custom":
        client = AsyncOpenAI(base_url=profile["base_url"], api_key=key)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_message}, {"role": "user", "content": masked_input or ""}],
            temperature=0,
        )
        return (resp.choices[0].message.content or "").strip()
    chat = LlmChat(api_key=key, session_id=f"govplat-{session_tag}-{int(time.time()*1000)}",
                   system_message=system_message).with_model(provider, model)
    full = ""
    async for ev in chat.stream_message(UserMessage(text=masked_input or "")):
        if isinstance(ev, TextDelta):
            full += ev.content
        elif isinstance(ev, StreamDone):
            break
    return full.strip()


async def _dispatch(system, masked_input, profile, task, base_record, db, zero_text,
                    max_llm_calls_per_run=None):
    """Shared run+log path. Returns result dict."""
    ok, mode, key, reason = _runnable(profile)
    if FORCE_ZERO_LLM:
        ok, mode, reason = False, "zero-llm", "seed mode"
    run_id = base_record.get("run_id")
    if ok and db is not None and run_id and max_llm_calls_per_run is not None:
        if not await _reserve_run_call(db, run_id, max_llm_calls_per_run):
            rec = {**base_record, "provider": "none", "model_used": "deterministic-budget-fallback",
                   "mode": "budget-exhausted", "output_hash": _hash(zero_text), "latency_ms": 0,
                   "note": f"Per-run model-call limit ({max_llm_calls_per_run}) reached"}
            await _log_call(db, rec)
            return {"text": zero_text, "model_used": rec["model_used"],
                    "mode": "budget-exhausted", "latency_ms": 0}
    if not ok:
        rec = {**base_record, "provider": (profile or {}).get("provider", "none"),
               "model_used": "zero-llm-deterministic" if mode == "zero-llm" else mode,
               "mode": mode, "output_hash": _hash(zero_text), "latency_ms": 0, "note": reason}
        await _log_call(db, rec)
        return {"text": zero_text, "model_used": rec["model_used"], "mode": mode, "latency_ms": 0}
    t0 = time.time()
    try:
        text = await _run_llm(system, masked_input, profile, key, task) or zero_text
        latency = round((time.time() - t0) * 1000)
        rec = {**base_record, "provider": profile["provider"], "model_used": profile["model"],
               "mode": "llm", "output_hash": _hash(text), "latency_ms": latency}
        await _log_call(db, rec)
        return {"text": text, "model_used": profile["model"], "mode": "llm", "latency_ms": latency}
    except Exception as e:
        logger.error(f"gateway error task={task}: {e}")
        latency = round((time.time() - t0) * 1000)
        rec = {**base_record, "provider": "none", "model_used": "zero-llm-fallback",
               "mode": "zero-llm-error-fallback", "error": str(e), "output_hash": _hash(zero_text), "latency_ms": latency}
        await _log_call(db, rec)
        return {"text": zero_text, "model_used": "zero-llm-fallback", "mode": "zero-llm-error-fallback", "latency_ms": latency}


async def complete(task: str, masked_input: str, capability_profile: str, db=None,
                   run_id: str = None, project_id: str = None) -> dict:
    cfg = await get_config(db, project_id)
    profile = cfg["capability_profiles"].get(capability_profile)
    base = {"id": str(uuid4()), "task": task, "agent_id": None, "level": None,
            "capability_profile": capability_profile, "masked_input_hash": _hash(masked_input),
            "timestamp": datetime.now(timezone.utc).isoformat(), "run_id": run_id, "project_id": project_id}
    zero = _ZERO_LLM_TASK_TEXT.get(task, "Zero-LLM mode: deterministic output, no LLM call was made.")
    system = SYSTEM_PROMPTS.get(task, "You are an SDLC governance assistant. OBSERVE and ADVISE only.")
    if cfg["zero_llm_mode"]:
        await _log_call(db, {**base, "provider": "none", "model_used": "zero-llm-deterministic",
                             "mode": "zero-llm", "output_hash": _hash(zero), "latency_ms": 0})
        return {"text": zero, "model_used": "zero-llm-deterministic", "mode": "zero-llm"}
    return await _dispatch(system, masked_input, profile, task, base, db, zero,
                           cfg["max_llm_calls_per_run"] if run_id else None)


async def complete_agent(agent_id: str, task: str, masked_input: str, level: int = 1, db=None,
                         tier: str = None, run_id: str = None, project_id: str = None) -> dict:
    agent = agent_profiles.get_agent(agent_id)
    if not agent:
        return {"text": "Unknown agent.", "model_used": "none", "mode": "error", "latency_ms": 0}

    cfg = await get_config(db, project_id)
    role = agent.get("harness_role", "maker")
    profile = cfg["capability_profiles"].get(role)
    base = {"id": str(uuid4()), "task": task or "agent_assessment", "agent_id": agent_id, "level": int(level),
            "capability_profile": role, "tier": tier, "masked_input_hash": _hash(masked_input),
            "timestamp": datetime.now(timezone.utc).isoformat(), "run_id": run_id, "project_id": project_id}

    # Deterministic agents never invoke a model.
    if not agent["uses_llm"]:
        text = (f"[Deterministic agent - no LLM call] {agent['name']} ({agent_id}) assesses via tooling: "
                f"{agent['deterministic_tools']}. Output: {agent['outputs']}. Verdicts use PASS / FAIL / NOT ASSESSED.")
        await _log_call(db, {**base, "provider": "none", "model_used": "deterministic-agent",
                             "mode": "deterministic", "output_hash": _hash(text), "latency_ms": 0})
        return {"text": text, "model_used": "deterministic-agent", "mode": "deterministic", "latency_ms": 0,
                "capability_profile": role}

    # Data-sovereignty: a regulated tier must stay on-prem (custom provider only).
    requires_local = bool(tier and cfg.get("sovereignty", {}).get(tier))
    if requires_local and (profile is None or profile.get("provider") in CLOUD_PROVIDERS):
        text = (f"[Sovereignty block] {tier} data must stay on-prem. Role '{role}' is mapped to a cloud "
                f"provider ('{(profile or {}).get('provider')}'), so no external call was made. Point this role "
                f"at a local OpenAI-compatible endpoint to process {tier} data. Deterministic advisory only.")
        await _log_call(db, {**base, "provider": "none", "model_used": "sovereignty-blocked",
                             "mode": "sovereignty-blocked", "output_hash": _hash(text), "latency_ms": 0})
        return {"text": text, "model_used": "sovereignty-blocked", "mode": "sovereignty-blocked",
                "latency_ms": 0, "capability_profile": role}

    zero = (f"Zero-LLM mode: {agent['name']} ({agent_id}, role={role}) would assess the masked input and return "
            f"an advisory finding with a PASS / FAIL / NOT ASSESSED verdict and cited evidence. No model was called.")
    if cfg["zero_llm_mode"]:
        await _log_call(db, {**base, "provider": "none", "model_used": "zero-llm-deterministic",
                             "mode": "zero-llm", "output_hash": _hash(zero), "latency_ms": 0})
        return {"text": zero, "model_used": "zero-llm-deterministic", "mode": "zero-llm", "latency_ms": 0, "capability_profile": role}

    system = agent["system_prompt"]
    if int(level) == 2:
        system += ("\n\nYou are acting as the INDEPENDENT LEVEL-2 reviewer using a different model family than "
                   "Level-1. Re-perform the check, then reply AGREE or DISAGREE with the Level-1 conclusion and a "
                   "one-line justification.")
    res = await _dispatch(system, masked_input, profile, task or "agent_assessment", base, db, zero,
                          cfg["max_llm_calls_per_run"] if run_id else None)
    res["capability_profile"] = role
    return res
