import { PageHeader } from "../components/PageHeader";

const ASSUMPTIONS = [
  "This is a clickable, data-backed PROTOTYPE - not production software. No real external integrations, real authentication, or writes to external systems exist.",
  "Nine controls (requirement quality, acceptance criteria, traceability gaps, secrets, India PII, logging leaks, static code analysis, unit test adequacy, release readiness) are deeply implemented with real deterministic and/or model-assisted logic.",
  "The remaining eleven controls in the catalog are seeded with full metadata but return an honest NOT ASSESSED verdict with a stated reason - never a silent pass.",
  "Role switching is a simple client-side dropdown (no login) - this mirrors the prototype's explicit non-goal of real authentication.",
  "The LLM gateway is model-agnostic. Zero-LLM mode is the deterministic fallback used automatically if no key is configured or a call fails.",
  "All sensitive values (secrets, India PII) are masked and keyed-hashed before storage or display. Raw values are never persisted.",
  "'Fetch live from source' is intentionally mocked in this prototype - it always returns a disabled-in-prototype message plus the stored masked evidence.",
  "The ledger is a real SHA-256 hash chain recomputed on every verify call - not a static demo value.",
  "Edge clients EC-01/EC-02 (Copilot, Droid) only ever produce unverified contributions and never set a verdict. EC-03/04/05 (CLI, webhook, repo audit) route through the same central event pipeline as a normal platform event.",
  "Gate readiness (G1–G10) and artifacts are computed live from current evidence, not hardcoded.",
];

export default function About() {
  return (
    <div data-testid="about-page">
      <PageHeader title="About & Assumptions" subtitle="SDLC Governance & Assurance Platform - a prototype that observes, collects evidence, and advises. Nothing else." />
      <div className="space-y-3 max-w-2xl">
        {ASSUMPTIONS.map((a, i) => (
          <div key={i} data-testid={`assumption-${i}`} className="text-sm border-l-4 border-[#FFE600] bg-gray-50 px-4 py-2.5">{a}</div>
        ))}
      </div>
    </div>
  );
}
