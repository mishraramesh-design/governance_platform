"""Model-agnostic LLM gateway for the Deterministic Harness.

Single interface: complete(task, masked_input, capability_profile) and
complete_agent(agent_id, task, masked_input, level) -> dict.

- Routes through configurable capability profiles (primary / independent-reviewer
  / none) stored in the `harness_config` collection. Profiles may map to DIFFERENT
  model families so Level-2 review is genuinely independent of Level-1.
- Supports a global Zero-LLM mode and per-agent determinism (Service agents with
  no model role never call an LLM).
- Only ever receives MASKED input. Logs every call (task, agent, profile, model,
  input/output HASHES, latency) to `llm_calls` - never raw text.
"""
import os
import time
import hashlib
import logging
from uuid import uuid4
from datetime import datetime, timezone

from dotenv import load_dotenv
from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

import agent_profiles

load_dotenv()
logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# Set True by the seeder so bulk demo generation stays fast and free (deterministic).
FORCE_ZERO_LLM = False

# Catalogue of models selectable per capability profile (mirrors the Emergent
# universal-key provider list). Exposed to the Model Settings UI.
AVAILABLE_MODELS = {
    "openai": ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-4.1"],
    "anthropic": ["claude-sonnet-5-5", "claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5-20251001"],
    "gemini": ["gemini-3.1-pro-preview", "gemini-3-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash"],
}

# Defaults: primary = OpenAI family, independent-reviewer = a DIFFERENT family
# (Anthropic) so L2 review satisfies the model-independence requirement.
DEFAULT_CONFIG = {
    "capability_profiles": {
        "primary": {"provider": "openai", "model": "gpt-5.6-terra"},
        "independent-reviewer": {"provider": "anthropic", "model": "claude-sonnet-5-5"},
        "none": None,
    },
    "zero_llm_mode": False,
}

# Task-level system prompts used by the deterministic engine (report narratives,
# requirement rewrites, L2 review). Agent personas live in agent_profiles.
SYSTEM_PROMPTS = {
    "requirement_rewrite": (
        "You are the Requirements Quality Agent inside an SDLC governance & assurance platform. "
        "You OBSERVE and ADVISE only - you never approve, reject or act. Given a masked requirement "
        "statement and its detected ambiguity issues, suggest one crisp rewritten requirement that is "
        "testable and measurable. Reply in 2-3 sentences max, plain language, no preamble."
    ),
    "author_report_narrative": (
        "You are writing the opening narrative of an AUTHOR REPORT for an individual contributor in an "
        "SDLC governance platform. Tone: plain language, constructive, advisory-only, never punitive. "
        "You OBSERVE and ADVISE, you do not approve/reject. 2-3 sentences max."
    ),
    "team_lead_report_narrative": (
        "You are writing the executive-summary narrative of a TEAM LEAD REPORT for an SDLC governance "
        "platform. Tone: concise, factual, trend-aware, advisory-only. You OBSERVE and ADVISE, you never "
        "approve/reject - humans decide. 3-4 sentences max."
    ),
    "l2_independent_review": (
        "You are an INDEPENDENT Level-2 reviewer in a two-level assurance model, using a different model "
        "family than the Level-1 check for independence. Given a Level-1 finding summary, reply with the "
        "single word AGREE or DISAGREE followed by a one-line justification. Be skeptical and precise."
    ),
}

_ZERO_LLM_TASK_TEXT = {
    "requirement_rewrite": (
        "Zero-LLM mode (rule-based): consider restating as 'The system shall <action> <object> "
        "within <measurable condition>.' Remove ambiguous terms and add a measurable acceptance threshold."
    ),
    "author_report_narrative": (
        "Zero-LLM mode: this is a deterministic, rule-generated summary of findings attributed to your "
        "recent work. Review each item below and remediate as advised. This is advisory only."
    ),
    "team_lead_report_narrative": (
        "Zero-LLM mode: deterministic team-level summary generated without LLM assistance. See the "
        "severity and verdict breakdown below for prioritisation. This is advisory only."
    ),
    "l2_independent_review": (
        "Zero-LLM mode: independent narrative review unavailable; relying on deterministic "
        "recomputation for Level-2 assurance on this finding. AGREE (recomputation-based)."
    ),
}


async def get_config(db=None) -> dict:
    """Load harness config from DB, falling back to defaults (and filling gaps)."""
    if db is None:
        return DEFAULT_CONFIG
    doc = await db.harness_config.find_one({"id": "default"}, {"_id": 0})
    if not doc:
        return DEFAULT_CONFIG
    cfg = {
        "capability_profiles": {**DEFAULT_CONFIG["capability_profiles"], **(doc.get("capability_profiles") or {})},
        "zero_llm_mode": bool(doc.get("zero_llm_mode", False)),
    }
    return cfg


async def save_config(db, capability_profiles: dict, zero_llm_mode: bool) -> dict:
    doc = {
        "id": "default",
        "capability_profiles": capability_profiles,
        "zero_llm_mode": bool(zero_llm_mode),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.harness_config.update_one({"id": "default"}, {"$set": doc}, upsert=True)
    return doc


def _resolve_key(provider: str):
    if EMERGENT_LLM_KEY:
        return EMERGENT_LLM_KEY
    if provider == "openai" and OPENAI_API_KEY:
        return OPENAI_API_KEY
    return None


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


async def _log_call(db, record: dict):
    if db is not None:
        try:
            await db.llm_calls.insert_one(dict(record))
        except Exception as e:
            logger.error(f"llm_calls logging failed: {e}")


async def _run_llm(system_message: str, masked_input: str, provider: str, model: str, session_tag: str) -> str:
    key = _resolve_key(provider)
    if not key:
        raise RuntimeError("no_api_key")
    chat = LlmChat(
        api_key=key,
        session_id=f"govplat-{session_tag}-{int(time.time()*1000)}",
        system_message=system_message,
    ).with_model(provider, model)
    full_text = ""
    async for event in chat.stream_message(UserMessage(text=masked_input or "")):
        if isinstance(event, TextDelta):
            full_text += event.content
        elif isinstance(event, StreamDone):
            break
    return full_text.strip()


async def complete(task: str, masked_input: str, capability_profile: str, db=None) -> dict:
    """Task-based completion used by the deterministic engine."""
    cfg = await get_config(db)
    profile = cfg["capability_profiles"].get(capability_profile)
    base = {
        "id": str(uuid4()), "task": task, "agent_id": None, "level": None,
        "capability_profile": capability_profile,
        "masked_input_hash": _hash(masked_input),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if cfg["zero_llm_mode"] or FORCE_ZERO_LLM or profile is None or not _resolve_key(profile.get("provider", "")):
        text = _ZERO_LLM_TASK_TEXT.get(task, "Zero-LLM mode: deterministic output, no LLM call was made.")
        rec = {**base, "provider": "none", "model_used": "zero-llm-deterministic",
               "mode": "zero-llm", "output_hash": _hash(text), "latency_ms": 0}
        await _log_call(db, rec)
        return {"text": text, "model_used": "zero-llm-deterministic", "mode": "zero-llm"}

    t0 = time.time()
    try:
        system = SYSTEM_PROMPTS.get(task, "You are an SDLC governance assistant. OBSERVE and ADVISE only.")
        text = await _run_llm(system, masked_input, profile["provider"], profile["model"], task)
        text = text or _ZERO_LLM_TASK_TEXT.get(task, "")
        rec = {**base, "provider": profile["provider"], "model_used": profile["model"],
               "mode": "llm", "output_hash": _hash(text), "latency_ms": round((time.time()-t0)*1000)}
        await _log_call(db, rec)
        return {"text": text, "model_used": profile["model"], "mode": "llm"}
    except Exception as e:
        logger.error(f"LLM gateway error task={task}: {e}")
        text = _ZERO_LLM_TASK_TEXT.get(task, "Zero-LLM fallback: deterministic output.")
        rec = {**base, "provider": "none", "model_used": "zero-llm-fallback",
               "mode": "zero-llm-error-fallback", "error": str(e),
               "output_hash": _hash(text), "latency_ms": round((time.time()-t0)*1000)}
        await _log_call(db, rec)
        return {"text": text, "model_used": "zero-llm-fallback", "mode": "zero-llm-error-fallback"}


async def complete_agent(agent_id: str, task: str, masked_input: str, level: int = 1, db=None) -> dict:
    """Run a specific agent persona through its capability profile.

    Level 1 uses the 'primary' profile; Level 2 uses 'independent-reviewer'.
    Service agents with no model role stay deterministic (never call an LLM).
    """
    agent = agent_profiles.get_agent(agent_id)
    if not agent:
        return {"text": "Unknown agent.", "model_used": "none", "mode": "error", "latency_ms": 0}

    cfg = await get_config(db)
    capability_profile = "independent-reviewer" if int(level) == 2 else "primary"
    profile = cfg["capability_profiles"].get(capability_profile)

    base = {
        "id": str(uuid4()), "task": task or "agent_assessment", "agent_id": agent_id, "level": int(level),
        "capability_profile": capability_profile, "masked_input_hash": _hash(masked_input),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Deterministic agents never invoke the model.
    if not agent["uses_llm"]:
        text = (
            f"[Deterministic agent - no LLM call] {agent['name']} ({agent_id}) is classed "
            f"'{agent['agent_class']}'. It assesses via tooling: {agent['deterministic_tools']}. "
            f"Expected output: {agent['outputs']}. Verdicts use PASS / FAIL / NOT ASSESSED with cited evidence."
        )
        rec = {**base, "provider": "none", "model_used": "deterministic-agent",
               "mode": "deterministic", "output_hash": _hash(text), "latency_ms": 0}
        await _log_call(db, rec)
        return {"text": text, "model_used": "deterministic-agent", "mode": "deterministic", "latency_ms": 0,
                "capability_profile": capability_profile}

    if cfg["zero_llm_mode"] or FORCE_ZERO_LLM or profile is None or not _resolve_key(profile.get("provider", "")):
        text = (
            f"Zero-LLM mode: {agent['name']} ({agent_id}) would assess the masked input and return an "
            f"advisory finding with a PASS / FAIL / NOT ASSESSED verdict and cited evidence. No model was called."
        )
        rec = {**base, "provider": "none", "model_used": "zero-llm-deterministic",
               "mode": "zero-llm", "output_hash": _hash(text), "latency_ms": 0}
        await _log_call(db, rec)
        return {"text": text, "model_used": "zero-llm-deterministic", "mode": "zero-llm", "latency_ms": 0,
                "capability_profile": capability_profile}

    t0 = time.time()
    try:
        system = agent["system_prompt"]
        if int(level) == 2:
            system += ("\n\nYou are acting as the INDEPENDENT LEVEL-2 reviewer using a different model family "
                       "than Level-1. Re-perform the check, then reply AGREE or DISAGREE with the Level-1 "
                       "conclusion and a one-line justification.")
        text = await _run_llm(system, masked_input, profile["provider"], profile["model"], f"{agent_id}-L{level}")
        latency = round((time.time()-t0)*1000)
        rec = {**base, "provider": profile["provider"], "model_used": profile["model"],
               "mode": "llm", "output_hash": _hash(text), "latency_ms": latency}
        await _log_call(db, rec)
        return {"text": text or "(empty response)", "model_used": profile["model"], "mode": "llm",
                "latency_ms": latency, "capability_profile": capability_profile}
    except Exception as e:
        logger.error(f"agent gateway error {agent_id} L{level}: {e}")
        latency = round((time.time()-t0)*1000)
        text = (f"Gateway error - falling back to deterministic advisory. {agent['name']} ({agent_id}) "
                f"could not reach the model. No verdict is implied. ({e})")
        rec = {**base, "provider": "none", "model_used": "zero-llm-fallback",
               "mode": "zero-llm-error-fallback", "error": str(e),
               "output_hash": _hash(text), "latency_ms": latency}
        await _log_call(db, rec)
        return {"text": text, "model_used": "zero-llm-fallback", "mode": "zero-llm-error-fallback",
                "latency_ms": latency, "capability_profile": capability_profile}
