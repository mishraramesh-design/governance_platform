import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";
import { ProvenancePill } from "../components/StatusPill";

export default function EdgeClients() {
  const { projectId } = useProject();
  const qc = useQueryClient();
  const [clientId, setClientId] = useState("");
  const [note, setNote] = useState("");

  const { data: clients } = useQuery({ queryKey: ["edge-clients"], queryFn: () => api.get("/edge-clients").then((r) => r.data) });
  const { data: contributions } = useQuery({
    queryKey: ["edge-contributions", projectId],
    queryFn: () => api.get("/edge-clients/contributions", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });

  const simulate = useMutation({
    mutationFn: () => api.post("/edge-clients/simulate", { client_id: clientId, project_id: projectId, note, event_type: "commit_pushed" }),
    onSuccess: (res) => {
      toast.success(res.data.mode === "unverified_contribution" ? "Unverified client contribution recorded" : "Event routed through the platform pipeline");
      qc.invalidateQueries({ queryKey: ["edge-contributions", projectId] });
      qc.invalidateQueries({ queryKey: ["findings"] });
    },
  });

  return (
    <div data-testid="edge-clients-page">
      <PageHeader title="Edge Client Simulator" subtitle="Copilot/Droid/CLI/webhooks all reach the same one central platform - but only platform-routed clients may set a verdict." />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mb-8">
        {clients?.map((c) => (
          <div key={c.id} data-testid={`edge-client-card-${c.id}`} className={`border p-4 ${clientId === c.id ? "border-black" : "border-gray-200"}`}>
            <div className="flex items-center justify-between mb-1">
              <span className="font-mono text-xs font-bold">{c.id}</span>
              <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 ${c.may_set_verdict ? "bg-black text-[#FFE600]" : "bg-gray-100 text-gray-600"}`}>
                {c.may_set_verdict ? "May set verdict" : "Never sets verdict"}
              </span>
            </div>
            <div className="font-[Chivo] font-bold text-sm mb-1">{c.name}</div>
            <div className="text-xs text-gray-500 mb-2">{c.who_uses_it} · {c.trust_class}</div>
            <button data-testid={`select-edge-client-btn-${c.id}`} onClick={() => setClientId(c.id)} className="text-[10px] font-bold uppercase border border-gray-400 px-2 py-1 hover:border-black">
              Select
            </button>
          </div>
        ))}
      </div>

      <div className="border border-gray-200 p-5 mb-8 flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Note / payload</label>
          <input data-testid="edge-client-note-input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Copilot suggests a fix for CTRL-06" className="w-full border border-gray-300 px-3 py-2 text-sm" />
        </div>
        <button data-testid="simulate-edge-client-btn" onClick={() => simulate.mutate()} disabled={!clientId || simulate.isPending} className="bg-[#FFE600] text-black hover:bg-[#F0D800] font-bold tracking-tight rounded-none px-4 py-2 text-xs border border-black transition-colors duration-100 disabled:opacity-50">
          {simulate.isPending ? "Submitting…" : "Simulate Contribution"}
        </button>
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Unverified Client Contributions</div>
        <div className="space-y-2">
          {contributions?.map((c) => (
            <div key={c.id} data-testid={`edge-contribution-row-${c.id}`} className="border border-dashed border-gray-400 p-3 flex items-center justify-between">
              <div>
                <span className="font-mono text-xs font-bold mr-2">{c.client_id}</span>
                <span className="text-sm">{c.note || "(no note)"}</span>
              </div>
              <ProvenancePill provenance={c.provenance} />
            </div>
          ))}
          {contributions && !contributions.length && <div className="text-sm text-gray-400 italic">No unverified contributions yet.</div>}
        </div>
      </div>
    </div>
  );
}
