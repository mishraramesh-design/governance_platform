import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "../components/ui/dialog";
import { toast } from "sonner";

const CLASS_ORDER = ["LLM-core", "Hybrid", "Service"];
const CLASS_STYLE = {
  "LLM-core": "bg-black text-[#FFE600]",
  Hybrid: "bg-[#FFE600] text-black",
  Service: "bg-gray-200 text-gray-800",
};

function ClassChip({ value }) {
  return (
    <span className={`inline-block px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${CLASS_STYLE[value] || "bg-gray-100"}`}>
      {value}
    </span>
  );
}

function Sandbox({ agent }) {
  const [input, setInput] = useState(
    `Masked requirement: "The system shall authenticate a user within ** seconds for **.*% of attempts." Detected fragment: AB****34.`
  );
  const [level, setLevel] = useState(1);
  const [tier, setTier] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  const run = async () => {
    setRunning(true);
    setResult(null);
    try {
      const r = await api.post("/harness/sandbox", {
        agent_id: agent.id,
        masked_input: input,
        level,
        tier: tier || null,
      });
      setResult(r.data);
    } catch (e) {
      toast.error("Gateway call failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="border border-gray-200 mt-4" data-testid="agent-sandbox">
      <div className="bg-gray-50 border-b border-gray-200 px-3 py-2 text-[11px] font-bold uppercase tracking-[0.2em] text-gray-500">
        Harness Sandbox · masked input only
      </div>
      <div className="p-3 space-y-3">
        <textarea
          data-testid="sandbox-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          rows={3}
          className="w-full text-sm border border-gray-300 p-2 font-mono focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
        />
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1 border border-gray-300">
            {[1, 2].map((l) => (
              <button
                key={l}
                data-testid={`sandbox-level-${l}`}
                onClick={() => setLevel(l)}
                className={`px-3 py-1.5 text-xs font-bold transition-colors ${
                  level === l ? "bg-black text-white" : "bg-white text-gray-600 hover:bg-gray-50"
                }`}
              >
                Level {l} {l === 1 ? "(primary)" : "(independent)"}
              </button>
            ))}
          </div>
          <button
            data-testid="sandbox-run-btn"
            onClick={run}
            disabled={running}
            className="px-4 py-1.5 text-xs font-bold bg-[#FFE600] text-black border border-black hover:bg-black hover:text-[#FFE600] transition-colors disabled:opacity-50"
          >
            {running ? "Running…" : "Run through gateway"}
          </button>
          <select
            data-testid="sandbox-tier"
            value={tier}
            onChange={(e) => setTier(e.target.value)}
            className="text-xs border border-gray-300 px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
          >
            <option value="">No tier</option>
            {["T0", "T1", "T2", "T3", "T4"].map((t) => <option key={t} value={t}>Data tier {t}</option>)}
          </select>
        </div>
        {result && (
          <div className="border border-gray-200" data-testid="sandbox-result">
            <div className="flex items-center gap-2 bg-gray-50 border-b border-gray-200 px-3 py-1.5 text-[10px] uppercase tracking-wider text-gray-500">
              <span>Model: <span className="font-bold text-black">{result.model_used}</span></span>
              <span>· Mode: <span className="font-bold text-black">{result.mode}</span></span>
              <span>· Profile: <span className="font-bold text-black">{result.capability_profile}</span></span>
              <span>· {result.latency_ms ?? 0} ms</span>
            </div>
            <p className="p-3 text-sm text-gray-800 whitespace-pre-wrap">{result.text}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function AgentDetail({ agent }) {
  const Row = ({ label, children }) => (
    <div className="py-2 border-b border-gray-100">
      <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-400 mb-0.5">{label}</div>
      <div className="text-sm text-gray-800">{children}</div>
    </div>
  );
  return (
    <div data-testid={`agent-detail-${agent.id}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className="font-mono text-xs font-bold">{agent.id}</span>
        <ClassChip value={agent.agent_class} />
        <span className="text-[10px] uppercase tracking-wider text-gray-400">{agent.stage}</span>
      </div>
      <Row label="Capability role">{agent.harness_role} {agent.uses_llm ? "(model-backed)" : "(deterministic, no LLM)"}</Row>
      <Row label="Mandate">{agent.responsibilities}</Row>
      <Row label="Role of the LLM">{agent.role_of_llm}</Row>
      <Row label="Skills & Knowledge">{agent.skills}</Row>
      <Row label="Deterministic tooling">{agent.deterministic_tools}</Row>
      <Row label="Inputs (read-only)">{agent.inputs}</Row>
      <Row label="Outputs">{agent.outputs}</Row>
      <Row label="Guardrails & independence">{agent.guardrails}</Row>
      <Row label="Level-2 reviewer">{agent.l2_pairing}</Row>
      <Row label="Accountable human owner">{agent.accountable_owner}</Row>
      <Row label="Controls (L1 / L2) · Release slice">
        {agent.l1_controls} as Level-1 · {agent.l2_controls} as Level-2 · {agent.release_slice}
      </Row>

      <div className="mt-4">
        <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-400 mb-1">Deterministic system prompt</div>
        <pre
          data-testid={`agent-prompt-${agent.id}`}
          className="text-xs bg-gray-900 text-gray-100 p-3 whitespace-pre-wrap font-mono leading-relaxed max-h-72 overflow-y-auto"
        >
{agent.system_prompt}
        </pre>
      </div>

      <Sandbox agent={agent} />
    </div>
  );
}

export default function AgentHarness() {
  const [selected, setSelected] = useState(null);
  const { data, isLoading } = useQuery({
    queryKey: ["harness-agents"],
    queryFn: () => api.get("/harness/agents").then((r) => r.data),
  });

  const agents = data?.agents || [];
  const summary = data?.summary;

  return (
    <div data-testid="harness-page">
      <PageHeader
        title="Agent Harness"
        subtitle="22 deterministic assurance agents (A01–A22), each with a distinct persona prompt, read-only inputs, guardrails and a Level-2 reviewer. Open any agent to view its full prompt and run masked input through the model gateway."
      />

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
          {[
            ["Total agents", summary.total],
            ["LLM-core", summary.by_class["LLM-core"] || 0],
            ["Hybrid", summary.by_class["Hybrid"] || 0],
            ["Service", summary.by_class["Service"] || 0],
            ["Deterministic (no LLM)", summary.deterministic_agents],
          ].map(([label, val]) => (
            <div key={label} className="border border-gray-200 p-3" data-testid={`harness-stat-${label}`}>
              <div className="text-2xl font-[Chivo] font-black text-black">{val}</div>
              <div className="text-[10px] uppercase tracking-wider text-gray-400 mt-0.5">{label}</div>
            </div>
          ))}
        </div>
      )}

      {isLoading && <div className="text-sm text-gray-400">Loading…</div>}

      {CLASS_ORDER.map((cls) => {
        const group = agents.filter((a) => a.agent_class === cls);
        if (!group.length) return null;
        return (
          <div key={cls} className="mb-8">
            <div className="flex items-center gap-2 mb-2 border-b border-gray-200 pb-1">
              <ClassChip value={cls} />
              <span className="text-xs text-gray-400">{group.length} agents</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {group.map((a) => (
                <button
                  key={a.id}
                  data-testid={`harness-agent-${a.id}`}
                  onClick={() => setSelected(a)}
                  className="text-left border border-gray-200 p-4 hover:border-black hover:shadow-sm transition-all duration-150 group"
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="font-mono text-xs font-bold text-black">{a.id}</span>
                    <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 ${
                      { maker: "bg-[#FFE600] text-black", checker: "bg-black text-[#FFE600]", security: "bg-red-600 text-white", verifier: "bg-gray-600 text-white" }[a.harness_role] || "bg-gray-200"
                    }`}>{a.harness_role}</span>
                  </div>
                  <div className="font-[Chivo] font-bold text-sm mb-1">{a.name}</div>
                  <div className="text-xs text-gray-500 mb-2 line-clamp-2">{a.responsibilities}</div>
                  <div className="text-[10px] text-gray-400 uppercase tracking-wide">L2 → {a.l2_pairing}</div>
                </button>
              ))}
            </div>
          </div>
        );
      })}

      <Dialog open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle className="font-[Chivo] font-black text-xl">{selected.name}</DialogTitle>
              </DialogHeader>
              <AgentDetail agent={selected} />
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
