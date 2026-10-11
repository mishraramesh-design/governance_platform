# PRD — SDLC Governance & Assurance Platform (IV&V) Prototype

## Original problem statement
Clickable, data-backed prototype of an SDLC Governance & Assurance Platform for a systems
integrator. OBSERVE · collect EVIDENCE · ADVISE only (read-only toward client systems).
Faithful to `Emergent_Prototype_Prompt.md` + `IVV_Governance_Platform_Design_Workbook_1.xlsx`.
EY theme (white/black/grey + #FFE600). Stack: React + Tailwind + Shadcn / FastAPI / MongoDB.
LLM via Emergent universal key. User explicitly wants an ENTERPRISE build, not a thin POC.

## Key reference sheets in the workbook
02_Agent_Catalog, 02A_Two_Level_Model, 16_Agent_Reclass (22 agents A01–A22),
15_Control_Catalog, 22_Learning_Harness, 20_Reports_Routing, 18_Data_Protection,
19_Runtime_Assurance, 21_CMMI_Artifacts.

## Architecture
- backend: server.py, database.py, engine.py, gateway.py, agent_profiles.py, ledger.py,
  detectors.py, models.py, seed_data.py, routers/ (catalog, projects, events, reports,
  assurance, dashboard, harness)
- frontend: src/pages/*, components/AppShell, context/{Role,Project}, lib/api

## Implemented (dates)
- (prior) M1 skeleton: nav, data model, seed data, ledger w/ integrity, role/project switch,
  control catalog, 18+ pages, EY theme.
- (prior) Detectors (secrets, India PII w/ Verhoeff/Luhn/PAN, logging leak), findings+triage,
  traceability, event→two reports, L2 adjudication, gates, artifacts, runtime, edge clients.
- **2026-06-11 — Deterministic Harness (P0, user-flagged gap). DONE + verified E2E:**
  - `agent_profiles.py`: 22 agents (A01–A22) each with a DISTINCT deterministic system prompt
    (mandate, skills, inputs/outputs, guardrails, L1→L2 pairing, observe-advise + masking +
    tri-state discipline). Plus the 18-row Two-Level assurance model.
  - `gateway.py` rewritten into a true model gateway: configurable capability profiles
    (primary / independent-reviewer / none) stored in `harness_config`; multi-provider routing
    via Emergent universal key (verified: L1=OpenAI gpt-5.6-terra, L2=Anthropic claude-sonnet-5-5
    — different families); global Zero-LLM mode; Service agents stay deterministic (no LLM);
    every call logged to `llm_calls` (hashes + latency, never raw text).
  - `routers/harness.py`: GET /harness/agents, /agents/{id}, /two-level-model, /config,
    PUT /config (validates provider/model), POST /sandbox, GET /llm-calls.
  - Frontend: `AgentHarness.jsx` (/harness) — 22 agents grouped by class, prompt viewer +
    live L1/L2 sandbox; `ModelSettings.jsx` (/model-settings) — profile editors, same-family
    independence warning, Zero-LLM switch, live audit log. Nav + routes wired.

## Verified
- 22 agents served w/ prompts; config shows key_mode=emergent_universal.
- Live sandbox: A02 L1→OpenAI, L2→Anthropic; A08 Service→deterministic (no LLM).
- Config PUT round-trips; invalid model → 400; Zero-LLM mode disables generation.
- Both pages render (EY theme), audit log populates.

## Backlog / next
- P1: Deep-dive stages — wire real detectors/controls for Requirements, Security & Privacy,
  Traceability, Release Readiness beyond current heuristics; replace NOT_ASSESSED stubs.
- P1: Route engine.apply_level2 & report narratives through `complete_agent` per the two-level
  pairing (currently uses task-level `complete`).
- P2: Learning Harness UI (22_Learning_Harness signals/loops/metrics), routing matrix page,
  Repo onboarding/Stack Profiler (A21), dynamic Edge Clients & Repo Audit bindings.
- P2: Multi-model expansion when user supplies more keys.

## Notes
- Emergent universal key in backend/.env as EMERGENT_LLM_KEY. User's OpenAI key retained as fallback.
- No auth in prototype (role switcher is demo-only). test_credentials.md: n/a.
