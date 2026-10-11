import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { useRole } from "../context/RoleContext";
import { PageHeader } from "../components/PageHeader";

export default function Adjudication() {
  const { projectId } = useProject();
  const { role } = useRole();
  const qc = useQueryClient();

  const { data: adjudications, isLoading } = useQuery({
    queryKey: ["adjudications", projectId],
    queryFn: () => api.get("/adjudications", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });

  const { data: agentsData } = useQuery({
    queryKey: ["harness-agents-map"],
    queryFn: () => api.get("/harness/agents").then((r) => r.data),
  });
  const agentName = (id) => agentsData?.agents?.find((a) => a.id === id)?.name || id || "—";

  const decide = useMutation({
    mutationFn: ({ id, human_decision }) => api.post(`/adjudications/${id}/decide`, { human_decision, decided_by_role: role }),
    onSuccess: () => {
      toast.success("Adjudication decision recorded");
      qc.invalidateQueries({ queryKey: ["adjudications"] });
    },
  });

  const pending = (adjudications || []).filter((a) => !a.human_decision);
  const resolved = (adjudications || []).filter((a) => a.human_decision);

  return (
    <div data-testid="adjudication-page">
      <PageHeader title="Level-2 Adjudication" subtitle="Whenever the independent Level-2 reviewer (a different model family) disagrees with Level 1, a human must adjudicate. Only a human decides here." />

      {isLoading && <div className="text-sm text-gray-400">Loading…</div>}

      <div className="mb-8">
        <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Pending ({pending.length})</div>
        <div className="space-y-3">
          {pending.map((a) => (
            <div key={a.id} data-testid={`adjudication-row-${a.id}`} className="border border-black p-4 bg-gray-50">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-3 text-sm">
                <div className="border border-gray-200 p-3 bg-white">
                  <div className="text-[10px] font-bold uppercase text-gray-500 mb-1">Level 1 · {a.l1_agent_id} {agentName(a.l1_agent_id)}</div>
                  <div className="font-bold mb-1">{a.l1_verdict}</div>
                  <div className="text-xs text-gray-600">{a.l1_reason}</div>
                </div>
                <div className="border border-gray-200 p-3 bg-white">
                  <div className="text-[10px] font-bold uppercase text-gray-500 mb-1">Level 2 · {a.l2_agent_id} {agentName(a.l2_agent_id)}</div>
                  <div className="font-bold mb-1 text-red-700">{a.l2_verdict}</div>
                  <div className="text-xs text-gray-600">{a.l2_narrative}</div>
                </div>
              </div>
              <div className="flex gap-2">
                <button data-testid={`agree-l1-btn-${a.id}`} onClick={() => decide.mutate({ id: a.id, human_decision: "agree_l1" })} className="flex-1 border border-black text-xs font-bold uppercase py-2 hover:bg-black hover:text-[#FFE600] transition-colors duration-100">Agree with L1</button>
                <button data-testid={`agree-l2-btn-${a.id}`} onClick={() => decide.mutate({ id: a.id, human_decision: "agree_l2" })} className="flex-1 border border-black text-xs font-bold uppercase py-2 hover:bg-black hover:text-[#FFE600] transition-colors duration-100">Agree with L2</button>
                <button data-testid={`override-btn-${a.id}`} onClick={() => decide.mutate({ id: a.id, human_decision: "override" })} className="flex-1 border border-gray-400 text-xs font-bold uppercase py-2 hover:bg-gray-100 transition-colors duration-100">Human Override</button>
              </div>
            </div>
          ))}
          {!pending.length && <div className="text-sm text-gray-400 italic">No disagreements awaiting adjudication.</div>}
        </div>
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Resolved ({resolved.length})</div>
        <div className="space-y-2">
          {resolved.map((a) => (
            <div key={a.id} className="text-sm border border-gray-200 px-3 py-2 flex items-center justify-between">
              <span>{a.l1_verdict} vs {a.l2_verdict}</span>
              <span className="text-xs font-bold uppercase text-gray-600">{a.human_decision.replaceAll("_", " ")} · {a.decided_by_role}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
