"""Model-agnostic LLM gateway. complete(task, masked_input, capability_profile) -> dict.
Supports a Zero-LLM deterministic mode when no key is configured or a call fails.
Only ever receives MASKED input - never raw sensitive values."""
import os
import time
import hashlib
import logging
from uuid import uuid4
from datetime import datetime, timezone

from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

PROFILES = {
    "primary": {"provider": "openai", "model": "gpt-5.6-terra"},
    "independent-reviewer": {"provider": "openai", "model": "gpt-5.4-mini"},
    "none": None,
}

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


def _zero_llm_fallback(task: str, masked_input: str) -> str:
    fallback = {
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
    return fallback.get(task, "Zero-LLM mode: deterministic output, no LLM call was made.")


async def complete(task: str, masked_input: str, capability_profile: str, db=None) -> dict:
    profile = PROFILES.get(capability_profile)
    call_record = {
        "id": str(uuid4()),
        "task": task,
        "capability_profile": capability_profile,
        "masked_input_hash": hashlib.sha256((masked_input or "").encode()).hexdigest(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if profile is None or not OPENAI_API_KEY:
        text = _zero_llm_fallback(task, masked_input)
        call_record.update({"model_used": "zero-llm-deterministic", "mode": "zero-llm"})
        if db is not None:
            await db.llm_calls.insert_one(call_record)
        return {"text": text, "model_used": "zero-llm-deterministic", "mode": "zero-llm"}

    try:
        chat = LlmChat(
            api_key=OPENAI_API_KEY,
            session_id=f"govplat-{task}-{int(time.time()*1000)}",
            system_message=SYSTEM_PROMPTS.get(
                task, "You are an SDLC governance assistant. OBSERVE and ADVISE only."
            ),
        ).with_model(profile["provider"], profile["model"])

        full_text = ""
        async for event in chat.stream_message(UserMessage(text=masked_input)):
            if isinstance(event, TextDelta):
                full_text += event.content
            elif isinstance(event, StreamDone):
                break

        call_record.update({"model_used": profile["model"], "mode": "llm"})
        if db is not None:
            await db.llm_calls.insert_one(call_record)
        return {"text": full_text.strip() or _zero_llm_fallback(task, masked_input), "model_used": profile["model"], "mode": "llm"}
    except Exception as e:
        logger.error(f"LLM gateway error on task={task}: {e}")
        text = _zero_llm_fallback(task, masked_input)
        call_record.update({"model_used": "zero-llm-fallback", "mode": "zero-llm-error-fallback", "error": str(e)})
        if db is not None:
            await db.llm_calls.insert_one(call_record)
        return {"text": text, "model_used": "zero-llm-fallback", "mode": "zero-llm-error-fallback"}
