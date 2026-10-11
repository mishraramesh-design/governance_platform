import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";
import { VerdictPill, SeverityPill } from "../components/StatusPill";

export default function Requirements() {
  const { projectId } = useProject();
  const qc = useQueryClient();
  const [running, setRunning] = useState(false);

  const { data: requirements } = useQuery({
    queryKey: ["requirements", projectId],
    queryFn: () => api.get("/requirements", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });

  const { data: findings } = useQuery({
    queryKey: ["findings", projectId, "CTRL-01"],
    queryFn: () => api.get("/findings", { params: { project_id: projectId, control_id: "CTRL-01" } }).then((r) => r.data),
    enabled: !!projectId,
  });

  const runScan = useMutation({
    mutationFn: () => api.post("/events/simulate", { project_id: projectId, event_type: "requirements_submitted" }),
    onMutate: () => setRunning(true),
    onSuccess: () => {
      toast.success("Requirements quality scan complete");
      qc.invalidateQueries({ queryKey: ["requirements", projectId] });
      qc.invalidateQueries({ queryKey: ["findings", projectId, "CTRL-01"] });
    },
    onSettled: () => setRunning(false),
  });

  const latestByReq = {};
  (findings || []).forEach((f) => {
    latestByReq[f.subject_ref] = f;
  });

  return (
    <div data-testid="requirements-page">
      <PageHeader
        title="Requirements Quality"
        subtitle="CTRL-01 (deterministic + model-assisted rewrite) and CTRL-02 (acceptance criteria) run against every requirement on this project."
        actions={
          <button
            data-testid="run-requirements-scan-btn"
            onClick={() => runScan.mutate()}
            disabled={running}
            className="bg-[#FFE600] text-black hover:bg-[#F0D800] font-bold tracking-tight rounded-none px-4 py-2 text-xs border border-black transition-colors duration-100 disabled:opacity-50"
          >
            {running ? "Running…" : "Run Requirements Quality Scan"}
          </button>
        }
      />

      <div className="space-y-3">
        {requirements?.map((r) => {
          const f = latestByReq[r.req_id];
          return (
            <div key={r.id} data-testid={`requirement-card-${r.req_id}`} className="border border-gray-200 p-4">
              <div className="flex items-start justify-between gap-4 mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-bold">{r.req_id}</span>
                  <span className="text-[10px] uppercase font-bold bg-gray-100 px-1.5 py-0.5 text-gray-600">{r.criticality}</span>
                </div>
                {f && (
                  <div className="flex items-center gap-2">
                    <SeverityPill severity={f.severity} />
                    <VerdictPill verdict={f.verdict} />
                  </div>
                )}
              </div>
              <p className="text-sm text-gray-800 mb-2">{r.text}</p>
              {f && (
                <div className="text-xs text-gray-500 border-t border-gray-100 pt-2 mt-2">
                  <div className="mb-1"><span className="font-bold text-gray-600">Reason:</span> {f.reason}</div>
                  <div><span className="font-bold text-gray-600">Suggested remedy ({f.method}):</span> {f.suggested_remedy}</div>
                </div>
              )}
              {!f && <div className="text-xs text-gray-400 italic">Not yet scanned - run the quality scan above.</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
