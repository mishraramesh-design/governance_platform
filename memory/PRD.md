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
- **2026-06-11 — MLOps layer + clear-key + sovereignty. DONE + verified:**
  - **MLOps / Learning Harness** (`/mlops`, `routers/mlops.py` + `evaluator.py`): governed
    registry (30 entries — 22 prompt packs, 4 model bindings, 4 detector rule-packs) with
    versions + states (candidate/shadow/promoted/retired); evaluation harness with labelled
    golden sets + seeded canaries → precision/recall/F1 + canary recall + drift vs baseline;
    **promotion gate** (rule-pack F1 ≥ 0.8, else 400); live governance metrics (zero-LLM share,
    not-assessed rate, L1/L2 disagreement, noise ratio). Every evaluate/promote appended to ledger.
  - **Clear-key control**: `__clear__` sentinel wipes a stored key (reverts to Emergent key);
    UI button per role. Verified.
  - **Sovereignty routing**: config `sovereignty` {T0..T4}; `complete_agent(tier=...)` blocks a
    regulated tier on a cloud provider (mode `sovereignty-blocked`) unless the role is on a local
    custom endpoint. Engine passes finding tier into L2 model review. UI section in Model Settings
    + tier selector in Harness sandbox. Verified (T1 blocked on gemini, T2 allowed).

- P1: Deep-dive remaining stages; replace NOT_ASSESSED control stubs with real detectors.
- P2: routing matrix page; Stack Profiler onboarding; shadow-mode A/B for registry candidates.
- **2026-06-11 — Four-role gateway + on-prem + Agent Flow. DONE + verified:**
  - Replaced primary/independent-reviewer with four capability roles **Maker / Checker /
    Security / Verifier** (agent_profiles `_AGENT_ROLE`: Maker 9, Checker 4, Security 5,
    Verifier 4). Each agent routes through its role; L1 uses the agent's role, L2 uses the
    paired reviewer agent's role.
  - Gateway supports **on-prem / custom OpenAI-compatible endpoints** (openai SDK + base_url)
    alongside cloud (OpenAI/Anthropic/Gemini). Per-role **BYOK key + base_url + local_only**
    flag (local_only blocks external cloud calls). Keys stored in DB (plain — prototype note
    shown in UI), masked as `__stored__` on GET, preserved on blank save.
    Verified: config CRUD, custom-missing-base_url→400, key preservation, live role routing
    (A02 Maker→OpenAI, A05 Security→Gemini), Zero-LLM mode.
  - New **Agent Flow** page (`/agent-flow`): in-app visual two-level flow (Event → L1 agent →
    re-perform → L2 reviewer → Human gate) with role legend + live model-per-role. No external
    Langflow (deliberate — keeps determinism/auditability; user agreed).
  - Model Settings rewritten for the four roles + on-prem fields. Harness cards show role chips.

- P1 (NEXT): MLOps / Learning Harness platform (workbook sheet 22) — model/prompt/rule-pack
  registry with versions + promotion gates, evaluation harness runs (golden sets/canaries),
  precision/recall & drift metrics, observability of every agent run.
- P1: Deep-dive remaining stages; replace NOT_ASSESSED control stubs with real detectors.
- P2: "Clear key" affordance in Model Settings; routing matrix page; Stack Profiler onboarding.
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
