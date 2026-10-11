import { useQuery } from "@tanstack/react-query";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";

const STATUS_STYLE = {
  Ready: "bg-green-100 text-green-800 border-green-600",
  "At Risk": "bg-red-100 text-red-800 border-red-600",
  "Not Assessed": "bg-gray-100 text-gray-600 border-gray-400",
  "Not Started": "bg-gray-50 text-gray-400 border-gray-300",
};

export default function Gates() {
  const { projectId } = useProject();
  const { data: gates, isLoading } = useQuery({
    queryKey: ["gates", projectId],
    queryFn: () => api.get("/gates", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });

  return (
    <div data-testid="gates-page">
      <PageHeader title="Gate Readiness" subtitle="G1–G10 advisory gate assessment, computed from live evidence. Human gate owners hold final decision authority at every gate." />
      {isLoading && <div className="text-sm text-gray-400">Loading…</div>}
      <div className="space-y-3">
        {gates?.map((g) => (
          <div key={g.id} data-testid={`gate-row-${g.id}`} className={`border-l-4 p-4 border border-gray-200 ${STATUS_STYLE[g.status]?.split(" ")[2] || ""}`}>
            <div className="flex items-start justify-between gap-4 mb-1">
              <div className="font-[Chivo] font-bold text-sm">{g.id} · {g.name}</div>
              <span className={`text-[10px] font-bold uppercase px-2 py-0.5 border ${STATUS_STYLE[g.status]}`}>{g.status}</span>
            </div>
            <p className="text-sm text-gray-600 mb-1">{g.criteria}</p>
            <p className="text-xs text-gray-500 mb-1">{g.reason}</p>
            <div className="text-[10px] text-gray-400">Approvers: {g.required_approvers.join(", ")} · {g.advisory_note}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
