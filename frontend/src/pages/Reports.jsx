import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import api from "../lib/api";
import { AuthenticatedDownload } from '../components/AuthenticatedDownload';
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";

export default function Reports() {
  const { projectId } = useProject();
  const { data: reports, isLoading } = useQuery({
    queryKey: ["reports", projectId],
    queryFn: () => api.get("/reports", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });

  return (
    <div data-testid="reports-page">
      <PageHeader title="Reports" subtitle="Every simulated event produces two reports: an Author Report (plain language, per-contributor) and a Team Lead Report (trends & hotspots). Both are downloadable and ledger-stamped." />
      {isLoading && <div className="text-sm text-gray-400">Loading…</div>}
      <div className="space-y-3">
        {reports?.map((r) => (
          <div key={r.id} data-testid={`report-row-${r.id}`} className="border border-gray-200 p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 ${r.type === "author" ? "bg-gray-100 text-gray-700" : "bg-black text-[#FFE600]"}`}>{r.type.replace("_", " ")}</span>
                  <span className="font-[Chivo] font-bold text-sm">{r.title}</span>
                </div>
                <p className="text-sm text-gray-600 mb-1">{r.narrative}</p>
                <div className="font-mono text-[10px] text-gray-400 truncate">Ledger hash: {r.ledger_hash}</div>
              </div>
              <AuthenticatedDownload
                data-testid={`download-report-btn-${r.id}`}
                path={`/reports/${r.id}/download`}
                filename={`report-${r.id}.html`}
                className="shrink-0 text-xs font-bold uppercase border border-black px-3 py-1.5 hover:bg-black hover:text-[#FFE600] transition-colors duration-100"
              >
                Download HTML
              </AuthenticatedDownload>
            </div>
          </div>
        ))}
        {reports && !reports.length && <div className="text-sm text-gray-400 italic">No reports yet - simulate an event first.</div>}
      </div>
    </div>
  );
}
