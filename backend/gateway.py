"""Model-agnostic LLM gateway for the Deterministic Harness.

Capability roles (maker / checker / security / verifier) are configurable per
deployment and may each point at a cloud provider (OpenAI / Anthropic / Gemini,
via provider API keys from the environment or a per-role key) OR an on-prem,
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

from dotenv import load_dotenv
import httpx
from openai import AsyncOpenAI

import agent_profiles

load_dotenv()
logger = logging.getLogger(__name__)

# Provider keys come from the environment (or a per-role key saved in Model Settings).
PROVIDER_KEY_ENV = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}


def env_key(provider: str):
    return os.environ.get(PROVIDER_KEY_ENV.get(provider, ""), "") or None


def any_env_key_available() -> bool:
    return any(env_key(p) for p in PROVIDER_KEY_ENV)

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
    "l2_independent_review": "Zero-LLM mode: independent narrative review unavailable; relying on deterministic recomputation. AGREE (recomputation-based).",
}


async def get_config(db=None) -> dict:
    if db is None:
        return DEFAULT_CONFIG
    doc = await db.harness_config.find_one({"id": "default"}, {"_id": 0})
    if not doc:
        return DEFAULT_CONFIG
    profiles = {**DEFAULT_CONFIG["capability_profiles"], **(doc.get("capability_profiles") or {})}
    sovereignty = {**DEFAULT_CONFIG["sovereignty"], **(doc.get("sovereignty") or {})}
    return {"capability_profiles": profiles, "zero_llm_mode": bool(doc.get("zero_llm_mode", False)),
            "sovereignty": sovereignty}


async def save_config(db, capability_profiles: dict, zero_llm_mode: bool, sovereignty: dict = None) -> dict:
    current = await get_config(db)
    doc = {"id": "default", "capability_profiles": capability_profiles,
           "zero_llm_mode": bool(zero_llm_mode),
           "sovereignty": sovereignty if sovereignty is not None else current["sovereignty"],
           "updated_at": datetime.now(timezone.utc).isoformat()}
    await db.harness_config.update_one({"id": "default"}, {"$set": doc}, upsert=True)
    return doc


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


async def _log_call(db, record: dict):
    if db is not None:
        try:
            await db.llm_calls.insert_one(dict(record))
        except Exception as e:
            logger.error(f"llm_calls logging failed: {e}")


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
    key = profile.get("api_key") or env_key(provider)
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
    timeout = float(os.environ.get("LLM_TIMEOUT", "60"))
    if provider == "openai":
        client = AsyncOpenAI(api_key=key, timeout=timeout)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_message}, {"role": "user", "content": masked_input or ""}],
        )
        return (resp.choices[0].message.content or "").strip()
    async with httpx.AsyncClient(timeout=timeout) as http:
        if provider == "anthropic":
            r = await http.post("https://api.anthropic.com/v1/messages",
                                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                                json={"model": model, "max_tokens": 1024, "system": system_message,
                                      "messages": [{"role": "user", "content": masked_input or ""}]})
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json().get("content", [])).strip()
        if provider == "gemini":
            r = await http.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                headers={"x-goog-api-key": key},
                                json={"systemInstruction": {"parts": [{"text": system_message}]},
                                      "contents": [{"role": "user", "parts": [{"text": masked_input or ""}]}]})
            r.raise_for_status()
            parts = (r.json().get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts).strip()
    raise ValueError(f"unsupported provider '{provider}'")


async def _dispatch(system, masked_input, profile, task, base_record, db, zero_text):
    """Shared run+log path. Returns result dict."""
    ok, mode, key, reason = _runnable(profile)
    if FORCE_ZERO_LLM:
        ok, mode, reason = False, "zero-llm", "seed mode"
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


async def complete(task: str, masked_input: str, capability_profile: str, db=None) -> dict:
    cfg = await get_config(db)
    profile = cfg["capability_profiles"].get(capability_profile)
    base = {"id": str(uuid4()), "task": task, "agent_id": None, "level": None,
            "capability_profile": capability_profile, "masked_input_hash": _hash(masked_input),
            "timestamp": datetime.now(timezone.utc).isoformat()}
    zero = _ZERO_LLM_TASK_TEXT.get(task, "Zero-LLM mode: deterministic output, no LLM call was made.")
    system = SYSTEM_PROMPTS.get(task, "You are an SDLC governance assistant. OBSERVE and ADVISE only.")
    if cfg["zero_llm_mode"]:
        await _log_call(db, {**base, "provider": "none", "model_used": "zero-llm-deterministic",
                             "mode": "zero-llm", "output_hash": _hash(zero), "latency_ms": 0})
        return {"text": zero, "model_used": "zero-llm-deterministic", "mode": "zero-llm"}
    return await _dispatch(system, masked_input, profile, task, base, db, zero)


async def complete_agent(agent_id: str, task: str, masked_input: str, level: int = 1, db=None, tier: str = None) -> dict:
    agent = agent_profiles.get_agent(agent_id)
    if not agent:
        return {"text": "Unknown agent.", "model_used": "none", "mode": "error", "latency_ms": 0}

    cfg = await get_config(db)
    role = agent.get("harness_role", "maker")
    profile = cfg["capability_profiles"].get(role)
    base = {"id": str(uuid4()), "task": task or "agent_assessment", "agent_id": agent_id, "level": int(level),
            "capability_profile": role, "tier": tier, "masked_input_hash": _hash(masked_input),
            "timestamp": datetime.now(timezone.utc).isoformat()}

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
    res = await _dispatch(system, masked_input, profile, task or "agent_assessment", base, db, zero)
    res["capability_profile"] = role
    return res
