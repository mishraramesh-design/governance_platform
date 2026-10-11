import { useQuery } from "@tanstack/react-query";
import api from "../lib/api";
import { PageHeader } from "../components/PageHeader";

export default function Agents() {
  const { data: agents, isLoading } = useQuery({ queryKey: ["agents"], queryFn: () => api.get("/agents").then((r) => r.data) });

  const stages = [...new Set((agents || []).map((a) => a.sdlc_stage))];

  return (
    <div data-testid="agents-page">
      <PageHeader title="Agents & SDLC Stages" subtitle="18 governance agents (A01–A18) mapped to the SDLC stage they observe. Level 2 agents independently re-verify Level 1 work." />
      {isLoading && <div className="text-sm text-gray-400">Loading…</div>}
      {stages.map((stage) => (
        <div key={stage} className="mb-8">
          <div className="text-xs font-bold uppercase tracking-[0.2em] text-gray-500 mb-2 border-b border-gray-200 pb-1">{stage}</div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {agents.filter((a) => a.sdlc_stage === stage).map((a) => (
              <div key={a.id} data-testid={`agent-card-${a.id}`} className="border border-gray-200 p-4">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="font-mono text-xs font-bold text-black">{a.id}</span>
                  <span className="text-[10px] font-bold uppercase bg-gray-100 px-1.5 py-0.5 text-gray-600">{a.level}</span>
                </div>
                <div className="font-[Chivo] font-bold text-sm mb-1">{a.name}</div>
                <div className="text-xs text-gray-500 mb-2">{a.description}</div>
                <div className="text-[10px] text-gray-400 uppercase tracking-wide">Skills: {a.skill_set}</div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
