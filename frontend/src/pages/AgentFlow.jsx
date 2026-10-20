import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import { useProject } from "../context/ProjectContext";

const ROLE_COLOR = {
  maker: "border-l-[#FFE600] bg-[#FFFBe6]",
  checker: "border-l-black bg-gray-50",
  security: "border-l-red-600 bg-red-50",
  verifier: "border-l-gray-500 bg-gray-50",
};
const ROLE_CHIP = {
  maker: "bg-[#FFE600] text-black",
  checker: "bg-black text-[#FFE600]",
  security: "bg-red-600 text-white",
  verifier: "bg-gray-600 text-white",
};

function Arrow({ label }) {
  return (
    <div className="flex flex-col items-center justify-center px-1 shrink-0">
      <svg width="34" height="14" viewBox="0 0 34 14" className="text-gray-400">
        <line x1="0" y1="7" x2="28" y2="7" stroke="currentColor" strokeWidth="1.5" />
        <polygon points="28,2 34,7 28,12" fill="currentColor" />
      </svg>
      {label && <span className="text-[9px] uppercase tracking-wider text-gray-400 mt-0.5">{label}</span>}
    </div>
  );
}

function AgentCard({ id, name, role, model, uses_llm, sub }) {
  return (
    <div className={`border border-gray-200 border-l-4 ${ROLE_COLOR[role] || "border-l-gray-300"} p-2.5 w-[200px] shrink-0`} data-testid={`flow-node-${id}`}>
      <div className="flex items-center justify-between mb-1">
        <span className="font-mono text-[11px] font-bold">{id}</span>
        <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 ${ROLE_CHIP[role] || "bg-gray-200"}`}>{role}</span>
      </div>
      <div className="text-xs font-bold leading-tight mb-1">{name}</div>
      {sub && <div className="text-[10px] text-gray-400 mb-1">{sub}</div>}
      <div className="text-[10px] font-mono text-gray-500 truncate">
        {uses_llm ? (model || "—") : "deterministic · no LLM"}
      </div>
    </div>
  );
}

export default function AgentFlow() {
  const [stageFilter, setStageFilter] = useState("");
  const { projectId } = useProject();
  const { data: flow } = useQuery({ queryKey: ["agent-flow", projectId], queryFn: () => api.get("/harness/flow", { params: { project_id: projectId || undefined } }).then((r) => r.data) });
  const { data: twoLevel } = useQuery({ queryKey: ["two-level"], queryFn: () => api.get("/harness/two-level-model").then((r) => r.data) });

  const nodeById = {};
  (flow?.nodes || []).forEach((n) => { nodeById[n.id] = n; });
  const roleModel = flow?.role_model || {};

  const rows = (twoLevel || []).filter((r) => !stageFilter || r.phase === stageFilter);
  const phases = [...new Set((twoLevel || []).map((r) => r.phase))];

  return (
    <div data-testid="agent-flow-page">
      <PageHeader
        title="Agent Flow"
        subtitle="The deterministic two-level assurance flow: every event routes to a Level-1 agent, whose work is independently re-performed by a Level-2 reviewer, before a human owner decides. Each node shows the capability role and the model it currently runs on."
      />

      <div className="flex items-center gap-4 mb-5 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap" data-testid="flow-role-legend">
          {(flow?.roles || []).map((r) => (
            <div key={r} className="flex items-center gap-1.5 border border-gray-200 pl-1.5 pr-2 py-1">
              <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 ${ROLE_CHIP[r]}`}>{r}</span>
              <span className="text-[11px] font-mono text-gray-500">{roleModel[r] || "—"}</span>
            </div>
          ))}
        </div>
        <select data-testid="flow-stage-filter" value={stageFilter} onChange={(e) => setStageFilter(e.target.value)}
          className="ml-auto border border-gray-300 px-2 py-1.5 text-xs">
          <option value="">All SDLC phases</option>
          {phases.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>

      <div className="space-y-3">
        {rows.map((row) => {
          const l1 = nodeById[row.l1] || {};
          const l2 = nodeById[row.l2] || {};
          return (
            <div key={row.phase} data-testid={`flow-row-${row.l1}`} className="border border-gray-200 p-3">
              <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500 mb-2">{row.phase}</div>
              <div className="flex items-stretch gap-1 overflow-x-auto pb-1">
                <div className="flex items-center justify-center border border-dashed border-gray-300 px-3 w-[120px] shrink-0 text-[10px] uppercase tracking-wider text-gray-400 text-center">
                  Event / Evidence
                </div>
                <Arrow label="L1" />
                <AgentCard id={row.l1} name={row.l1_name} role={row.l1_role} model={roleModel[row.l1_role]} uses_llm={l1.uses_llm} sub="Level 1 · performs" />
                <Arrow label="re-perform" />
                <AgentCard id={row.l2} name={row.l2_name} role={row.l2_role} model={roleModel[row.l2_role]} uses_llm={l2.uses_llm} sub="Level 2 · independent" />
                <Arrow label="decide" />
                <div className="flex flex-col justify-center border border-gray-200 bg-black text-white p-2.5 w-[200px] shrink-0">
                  <div className="text-[9px] font-bold uppercase tracking-wider text-[#FFE600] mb-1">Human gate</div>
                  <div className="text-[11px] leading-tight">{row.human_approval}</div>
                </div>
              </div>
              <div className="text-[10px] text-gray-400 mt-2">L2 coverage: {row.coverage}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
