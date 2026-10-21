import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import { AuthenticatedDownload } from '../components/AuthenticatedDownload';
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";

const ARTIFACT_TYPES = [
  { id: "rtm", label: "Requirements Traceability Matrix" },
  { id: "verification_summary", label: "Verification Summary" },
  { id: "defect_log", label: "Defect / Finding Log" },
  { id: "gate_readiness", label: "Gate Readiness Assessment" },
  { id: "data_protection_summary", label: "Data Protection Findings Summary" },
  { id: "metrics_summary", label: "Metrics Summary" },
];

export default function Artifacts() {
  const { projectId } = useProject();
  const qc = useQueryClient();

  const { data: artifacts, isLoading } = useQuery({
    queryKey: ["artifacts", projectId],
    queryFn: () => api.get("/artifacts", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });

  const generate = useMutation({
    mutationFn: (artifact_type) => api.post("/artifacts/generate", { project_id: projectId, artifact_type }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["artifacts", projectId] }),
  });

  return (
    <div data-testid="artifacts-page">
      <PageHeader title="CMMI Artifacts" subtitle="Downloadable, ledger-stamped governance artifacts generated on demand from live evidence." />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-8">
        {ARTIFACT_TYPES.map((t) => (
          <button
            key={t.id}
            data-testid={`generate-artifact-btn-${t.id}`}
            onClick={() => generate.mutate(t.id)}
            disabled={generate.isPending}
            className="text-left border border-gray-300 hover:border-black p-4 transition-colors duration-100 disabled:opacity-50"
          >
            <div className="font-[Chivo] font-bold text-sm mb-1">{t.label}</div>
            <div className="text-xs text-gray-500">Generate from current evidence</div>
          </button>
        ))}
      </div>

      {isLoading && <div className="text-sm text-gray-400">Loading…</div>}

      <div className="space-y-2">
        {[...(artifacts || [])].reverse().map((a) => (
          <div key={a.id} data-testid={`artifact-row-${a.id}`} className="border border-gray-200 p-3 flex items-center justify-between">
            <div className="min-w-0">
              <div className="font-semibold text-sm">{a.title}</div>
              <div className="font-mono text-[10px] text-gray-400">{a.created_at.slice(0, 19)} · {a.ledger_hash?.slice(0, 16)}…</div>
            </div>
            <AuthenticatedDownload path={`/artifacts/${a.id}/download`} filename={`artifact-${a.id}.html`} data-testid={`download-artifact-btn-${a.id}`} className="shrink-0 text-xs font-bold uppercase border border-black px-3 py-1.5 hover:bg-black hover:text-[#FFE600] transition-colors duration-100">
              Download
            </AuthenticatedDownload>
          </div>
        ))}
      </div>
    </div>
  );
}
