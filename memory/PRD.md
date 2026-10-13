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
- **2026-06-11 — Detector checksum/structural hardening (detectors.py only). DONE + QA-verified (iteration_4, 16/16):**
  - Aadhaar = 12 digits + first digit 2-9 + Verhoeff; Card = Luhn + len 13-19; PAN 4th char in
    [PCHFATBLJG]; GSTIN state 01-38 + check char; Mobile ignores longer runs & id/timestamp/epoch
    context; Logging-leak flags only sensitive VARIABLE/value args (not plain string literals).
  - Evaluator PII golden fixtures updated to checksum-valid specimens. Before→After: india_pii
    precision 0.857→1.0 (FP removed), recall 1.0, f1 0.923→1.0; secrets 1.0/0.667/0.8 unchanged;
    logging/static 1.0. Promotion threshold unchanged (0.8). Tests: `tests/test_detectors.py`.
  - NOTE (out of scope, flagged by QA): `/api/ledger/verify` reports the hash chain broken at
    seq 726 — pre-existing, unrelated to detectors; needs separate investigation.

- P1: investigate ledger chain break (seq 726); auto-refresh MLOps metrics after detector version bumps.
- **2026-06-11 — Repo-audit enhancements (broader secrets, re-audit-in-place, spec ingestion). DONE + QA-verified (iteration_3, 8/8):**
  - **Broader secrets** (`detectors.py`): new `sensitive_assignment_unquoted` pattern catches
    unquoted env/YAML secrets (docker-compose `DB_PASSWORD`, `JWT_SECRET: ${VAR:-default}`) while
    excluding pure env refs / placeholders. Shared with the MLOps evaluator — secrets F1 still 0.8
    (no regression).
  - **Re-audit in place** (`repo_ingest.py`): a repeat audit of the same repo URL reuses the same
    project (matches by repo_url+source, clears old findings/events/reports/repo_audits, keeps the
    append-only ledger). No duplicate projects.
  - **Spec ingestion**: `_clone_and_scan` now collects README/OpenAPI/test signals; ingest emits
    real-verdict findings for CTRL-01 (Requirements & API Spec), CTRL-11 (Unit Test Adequacy),
    CTRL-15/16/17 (Security/Perf/Accessibility test presence) and CTRL-18 (AI eval, when AI libs
    referenced). Gates **G2 (Requirements)** and **G6 (System Test)** now compute real status.
  - Verified on myauction-node: 83 findings incl 4 critical unquoted secrets; G2/G4/G6/G8 At Risk.

- P1: unit test asserting CTRL->gate mapping; pull OpenAPI endpoint list into Traceability (CTRL-03).
- P2: evidence-pack export (PDF/Docx), routing matrix page, drift alerts, private-repo token support.
- **2026-06-11 — Live GitHub repository audit. DONE + QA-verified (iteration_2):**
  - `repo_ingest.py` + `POST /api/repo-audit/ingest`: clones a PUBLIC repo read-only
    (shallow, 120s timeout, GIT_TERMINAL_PROMPT=0), profiles the stack (A21 — languages,
    frameworks, files/LOC), runs the deterministic detectors (secrets/PII/logging/static) over
    real source, records findings with two-level review, and generates the author + team-lead
    reports and the gate pack. Creates a project per audit; all events/findings/reports/audit
    appended to the ledger. Validation: 400 on bad URL, 502 on clone failure.
  - `/repo-audit` page rewritten to run the live audit and render stack profile, finding
    summary (severity chips), both reports (narrative + sections + ledger hash) and the 10-gate
    pack, then switches the active project and links to Findings/Gates. ProjectContext gained
    `refreshProjects`.
  - Verified on https://github.com/mishraramesh-design/myauction-node: 73 findings
    (66 static-code, 7 PII), React/Express/FastAPI/PostgreSQL, 100 files/~12.8k LOC, G4/G8 At Risk.
    Backend 11/11 pytest (`/app/backend/tests/test_repo_audit.py`), frontend flow 100%.
  - Known limitation: each audit creates a new project (no idempotency yet); framework detection
    is substring-based. Secrets detector needs quotes so unquoted env/yaml secrets are not flagged.

- P1: Repo-audit idempotency (re-audit updates the same project); run Design/System-Test and
  Requirements controls against real repo artifacts where present (docs/specs).
- P2: broaden secret detector to unquoted env/yaml assignments; routing matrix; drift alerts.
- **2026-06-11 — Stage deep-dives + Shadow A/B + Ledger linkage + Full QA. DONE + QA-verified:**
  - **Design & System-Test detectors** (replaces NOT_ASSESSED stubs): CTRL-04 Architecture
    Conformance (design coverage of critical/high reqs + NFR allocation), CTRL-05 Threat Model
    (security-relevant reqs addressed by a security design item, STRIDE/DPDP), CTRL-15 Security
    DAST, CTRL-16 Performance threshold, CTRL-17 Accessibility (WCAG), CTRL-18 AI Model Eval
    (ISO/IEC 42001). Seeded system-test test_cases (security/performance/accessibility/ai_eval).
    Gates G3 (Design) and G6 (System Test) now compute real status (At Risk/Ready) instead of
    "Not Assessed".
  - **Shadow A/B** (`/mlops`): `POST /mlops/registry/{id}/shadow-compare` runs the candidate vs
    the promoted baseline, returns F1 delta + promote/hold recommendation; UI chip + button.
  - **Ledger linkage**: MLOps entries (mlops_registry_initialised, mlops_shadow_compare,
    registry_promotion, eval_run) render as clickable links in the Audit Ledger → navigate to /mlops.
  - **Full QA** via testing_agent (iteration_1): backend 15/15 pytest pass
    (`/app/backend/tests/test_new_features.py`), frontend 100% on critical flows, no functional
    defects. Added DialogDescription for a11y.

- P1: Integration-test detectors (CTRL-13 API contract, CTRL-14 E2E) + G5 gate.
- P2: routing matrix page; Stack Profiler onboarding; drift alert thresholds on the dashboard.
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
- Custom opaque Bearer-token auth added (no external IdP). See test_credentials.md for demo users/tokens.

## 2026-06 — Auth, RBAC, Segregation of Duties & Ledger Fix (DONE, tested 15/15)
- Custom opaque Bearer-token auth (SHA-256 hashed in DB); no external IdP. `backend/auth.py`.
- 8 demo users seeded (`seed_data.ensure_users_seeded`), admin/owner = mishraramesh@gmail.com (u-ramesh, Programme Manager). Per-project `role_assignments` + deterministic `api_tokens` (`gov-demo-<id>-token-2026`). Commit `author_user_id` backfilled.
- Routers mounted in server.py: `routers/auth.py` (/auth/users, /auth/demo-login, /auth/me), `routers/admin.py` (/admin/users, /admin/assignments, /admin/tokens[+revoke]).
- Write endpoints (events/triage/adjudicate, repo-audit ingest, edge simulate) require a valid token; project-scoped role enforced; segregation of duties blocks authors from triaging their own findings.
- Frontend: `AuthContext` (token in sessionStorage), Bearer axios interceptor, header user-switcher + acting-role switcher (scoped to assigned roles), Programme-Manager-gated `/admin` page.
- FIXED P1 ledger hash-chain bug: root cause was a race in `append_to_ledger` (concurrent appends forked the chain → 222 duplicate seqs). Added an `asyncio.Lock` to serialize appends + `rebuild_chain()` repair (admin `POST /api/ledger/rebuild`). `GET /api/ledger/verify` now valid=true and stays valid after writes.

## 2026-06 — Edge-Client Signed Bundles (DONE, tested: backend curl + frontend 6/6)
- `POST /api/edge-clients/submit` ({project_id, client_id EC-01/EC-02, prompt_hash, tool_calls[], input_hashes[], output_text, role}) requires a valid bearer token (401 without) + assigned project role (403 otherwise); rejects platform clients (422, only EC-01 Copilot / EC-02 Droid allowed).
- Server masks secrets/PII in output_text via `detectors.mask_sensitive_text` (raw never stored); stores prompt_hash only (never prompt text). Computes `bundle_hash` = SHA-256 over canonical JSON; HMAC-signs with a per-user key derived from `EDGE_SIGNING_SECRET` (env, never returned). Labels every bundle trust_class "Client-generated, unverified", may_set_verdict=false, provenance "client_model_unverified" — can never set a verdict. bundle_hash+signature anchored in the ledger.
- `GET /api/edge-clients/bundles` (list) and `GET /api/edge-clients/bundles/{id}/verify` (recomputes hash+signature → valid/tampered). Verified: one-char DB mutation of a stored bundle → status "tampered".
- Frontend `EdgeClients.jsx`: "Submit Signed Client Bundle" panel (sign-in + assigned role required) + "Signed Bundles" list with per-row "Verify" button showing Verified/Tampered badge + provenance chip.
- New env key: `EDGE_SIGNING_SECRET` in backend/.env. New collection: `edge_bundles`.

### P1/P2 backlog remaining
- P0 (carried over, not yet done): DB-driven routing matrix frontend — `GET /api/routing` backend ready; `RoleContext.jsx` still has hardcoded ROLES/ROUTING_MATRIX; read-only `Routing.jsx` page + nav link pending.
- P1: Deep-dive stages — real detectors/controls for Requirements, Security & Privacy, Traceability, Release Readiness; replace NOT_ASSESSED stubs.
- P1: Route engine.apply_level2 & report narratives through `complete_agent` per two-level pairing.
- P2: Learning Harness UI signals/loops/metrics, routing-matrix page, Repo onboarding/Stack Profiler (A21), dynamic Edge Clients & Repo Audit bindings, multi-model expansion.
