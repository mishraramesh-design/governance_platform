import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { useRole, routingFor } from "../context/RoleContext";
import { PageHeader } from "../components/PageHeader";
import { VerdictPill, SeverityPill, ProvenancePill, RoutingPill } from "../components/StatusPill";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "../components/ui/sheet";

export default function Findings() {
  const { projectId } = useProject();
  const { role } = useRole();
  const qc = useQueryClient();
  const [filters, setFilters] = useState({ severity: "", verdict: "" });
  const [selected, setSelected] = useState(null);

  const { data: findings, isLoading } = useQuery({
    queryKey: ["findings", projectId, filters],
    queryFn: () =>
      api
        .get("/findings", { params: { project_id: projectId, ...(filters.severity && { severity: filters.severity }), ...(filters.verdict && { verdict: filters.verdict }) } })
        .then((r) => r.data),
    enabled: !!projectId,
  });

  const { data: agentsData } = useQuery({
    queryKey: ["harness-agents-map"],
    queryFn: () => api.get("/harness/agents").then((r) => r.data),
  });
  const agentName = (id) => agentsData?.agents?.find((a) => a.id === id)?.name || id || "—";

  const triage = useMutation({
    mutationFn: ({ id, decision }) => api.post(`/findings/${id}/triage`, { decision, decided_by_role: role }),
    onSuccess: () => {
      toast.success("Triage decision recorded");
      qc.invalidateQueries({ queryKey: ["findings"] });
    },
  });

  const fetchLive = useMutation({
    mutationFn: ({ findingId, idx }) => api.post(`/findings/${findingId}/evidence/${idx}/fetch-live`),
    onSuccess: (res) => toast.info(res.data.message),
  });

  return (
    <div data-testid="findings-page">
      <PageHeader title="Findings Explorer" subtitle="Every finding carries a tri-state verdict (PASS / FAIL / NOT ASSESSED), severity, confidence, evidence and a suggested remedy. Nothing here is a decision." />

      <div className="flex gap-3 mb-5">
        <select data-testid="filter-severity" value={filters.severity} onChange={(e) => setFilters((f) => ({ ...f, severity: e.target.value }))} className="border border-gray-300 px-2 py-1.5 text-xs">
          <option value="">All Severities</option>
          {["critical", "high", "medium", "low", "info"].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select data-testid="filter-verdict" value={filters.verdict} onChange={(e) => setFilters((f) => ({ ...f, verdict: e.target.value }))} className="border border-gray-300 px-2 py-1.5 text-xs">
          <option value="">All Verdicts</option>
          {["PASS", "FAIL", "NOT_ASSESSED"].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {isLoading && <div className="text-sm text-gray-400">Loading…</div>}

      <div className="space-y-2">
        {findings?.map((f) => {
          const routing = routingFor(f.tags, role);
          return (
            <div key={f.id} data-testid={`finding-row-${f.id}`} className="border border-gray-200 p-4 hover:border-black transition-colors duration-100 cursor-pointer" onClick={() => setSelected(f)}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span className="font-mono text-xs font-bold">{f.control_id}</span>
                    <span className="font-semibold text-sm">{f.control_name}</span>
                    <ProvenancePill provenance={f.provenance} />
                    {routing && <RoutingPill routing={routing} />}
                  </div>
                  <p className="text-sm text-gray-600 truncate">{f.reason}</p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <SeverityPill severity={f.severity} />
                  <VerdictPill verdict={f.verdict} />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <Sheet open={!!selected} onOpenChange={(o) => !o && setSelected(null)}>
        <SheetContent data-testid="finding-drawer" className="w-full sm:max-w-lg overflow-y-auto">
          {selected && (
            <>
              <SheetHeader>
                <SheetTitle className="font-[Chivo]">{selected.control_name}</SheetTitle>
              </SheetHeader>
              <div className="mt-4 space-y-4 text-sm">
                <div className="flex items-center gap-2">
                  <SeverityPill severity={selected.severity} />
                  <VerdictPill verdict={selected.verdict} />
                  <ProvenancePill provenance={selected.provenance} />
                  {selected.tier && <span data-testid="tier-chip" className="text-[10px] font-bold uppercase px-1.5 py-0.5 bg-black text-[#FFE600]">{selected.tier}</span>}
                </div>
                <div><span className="font-bold text-gray-600">Reason:</span> {selected.reason}</div>
                <div><span className="font-bold text-gray-600">Suggested remedy:</span> {selected.suggested_remedy}</div>
                <div><span className="font-bold text-gray-600">Confidence:</span> {selected.confidence}% · <span className="font-bold text-gray-600">Method:</span> {selected.method}</div>
                <div className="grid grid-cols-2 gap-2 border border-gray-200 p-2 bg-gray-50" data-testid="finding-attribution">
                  <div>
                    <div className="text-[10px] font-bold uppercase text-gray-400">Level-1 agent</div>
                    <div className="text-xs"><span className="font-mono font-bold">{selected.l1_agent_id}</span> {agentName(selected.l1_agent_id)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] font-bold uppercase text-gray-400">Level-2 reviewer</div>
                    <div className="text-xs"><span className="font-mono font-bold">{selected.l2_agent_id || "—"}</span> {selected.l2_agent_id ? agentName(selected.l2_agent_id) : ""}</div>
                    {selected.l2_model && <div className="text-[10px] text-gray-400 font-mono">{selected.l2_model}</div>}
                  </div>
                </div>
                <div><span className="font-bold text-gray-600">Level-2 status:</span> {selected.level2_status?.replaceAll("_", " ")}</div>
                {selected.level2_narrative && <div className="text-xs italic text-gray-500 border-l-2 border-gray-300 pl-2">{selected.level2_narrative}</div>}

                <div>
                  <div className="font-bold text-gray-600 mb-2">Evidence (masked)</div>
                  {selected.evidence?.length ? (
                    <div className="space-y-2">
                      {selected.evidence.map((e, idx) => (
                        <div key={idx} className="border border-gray-200 p-2 font-mono text-xs flex items-center justify-between gap-2">
                          <span>{e.type}: {e.masked}</span>
                          <button
                            data-testid={`fetch-live-btn-${idx}`}
                            onClick={() => fetchLive.mutate({ findingId: selected.id, idx })}
                            className="shrink-0 text-[10px] uppercase font-bold border border-gray-400 px-1.5 py-0.5 hover:border-black"
                          >
                            Fetch live from source
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs text-gray-400 italic">No evidence attached.</div>
                  )}
                </div>

                <div className="pt-3 border-t border-gray-200 flex gap-2">
                  <button data-testid="triage-accept-btn" onClick={() => triage.mutate({ id: selected.id, decision: "accept" })} className="flex-1 border border-black text-xs font-bold uppercase py-2 hover:bg-black hover:text-[#FFE600] transition-colors duration-100">Accept</button>
                  <button data-testid="triage-dismiss-btn" onClick={() => triage.mutate({ id: selected.id, decision: "dismiss" })} className="flex-1 border border-gray-400 text-xs font-bold uppercase py-2 hover:bg-gray-100 transition-colors duration-100">Dismiss</button>
                  <button data-testid="triage-escalate-btn" onClick={() => triage.mutate({ id: selected.id, decision: "escalate" })} className="flex-1 border border-red-600 text-red-700 text-xs font-bold uppercase py-2 hover:bg-red-600 hover:text-white transition-colors duration-100">Escalate</button>
                </div>
                <div className="text-[10px] text-gray-400">Current status: {selected.status}</div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
