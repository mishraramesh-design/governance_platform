import { useQuery } from "@tanstack/react-query";
import api from "../lib/api";
import { PageHeader } from "../components/PageHeader";

const STATUS_STYLE = {
  Implemented: "bg-green-100 text-green-800",
  "In Progress": "bg-[#FFE600] text-black",
  Planned: "bg-gray-100 text-gray-600",
};

export default function AIGovernance() {
  const { data, isLoading } = useQuery({ queryKey: ["ai-governance"], queryFn: () => api.get("/ai-governance").then((r) => r.data) });

  return (
    <div data-testid="ai-governance-page">
      <PageHeader title="AI Governance (ISO/IEC 42001)" subtitle="AI-01 through AI-16 control plan for AI used inside this platform. All platform-model outputs are narrative-only and Level-2 checked." />

      {data && (
        <div className="flex gap-4 mb-6">
          <div className="border border-gray-200 px-4 py-2">
            <span className="text-[10px] uppercase tracking-wider text-gray-500">LLM calls logged</span>
            <div className="text-xl font-black">{data.llm_calls_count}</div>
          </div>
          <div className="border border-gray-200 px-4 py-2">
            <span className="text-[10px] uppercase tracking-wider text-gray-500">AI model-eval findings</span>
            <div className="text-xl font-black">{data.model_eval_findings_count}</div>
          </div>
        </div>
      )}

      {isLoading && <div className="text-sm text-gray-400">Loading…</div>}

      <div className="space-y-2">
        {data?.controls.map((c) => (
          <div key={c.id} data-testid={`ai-control-row-${c.id}`} className="border border-gray-200 p-4">
            <div className="flex items-start justify-between gap-3 mb-1">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-bold">{c.id}</span>
                <span className="font-[Chivo] font-bold text-sm">{c.control_theme}</span>
              </div>
              <span className={`text-[10px] font-bold uppercase px-2 py-0.5 ${STATUS_STYLE[c.status]}`}>{c.status}</span>
            </div>
            <p className="text-sm text-gray-600 mb-1">{c.requirement}</p>
            <div className="text-xs text-gray-500">Evidence: {c.minimum_evidence}</div>
            <div className="text-[10px] text-gray-400 mt-1">Owner/Agent: {c.owner_agent} · Frequency: {c.frequency}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
