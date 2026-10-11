import { useQuery } from "@tanstack/react-query";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";

export default function Traceability() {
  const { projectId } = useProject();
  const { data, isLoading } = useQuery({
    queryKey: ["traceability", projectId],
    queryFn: () => api.get("/traceability", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });

  return (
    <div data-testid="traceability-page">
      <PageHeader title="Traceability Matrix" subtitle="Requirement ↔ Design ↔ Commit ↔ Test bidirectional trace, with computed coverage and an explicit gap list (CTRL-03)." />

      {data && (
        <div className="mb-6 border border-black inline-block px-5 py-3 bg-gray-50">
          <span className="text-[10px] uppercase tracking-wider font-bold text-gray-500">Coverage</span>
          <div className="text-3xl font-black text-black">
            <span className={data.coverage_pct >= 80 ? "" : "bg-[#FFE600] px-1"}>{data.coverage_pct}%</span>
          </div>
        </div>
      )}

      {isLoading && <div className="text-sm text-gray-400">Loading…</div>}

      <div className="overflow-x-auto border border-gray-200 mb-8">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-y border-gray-300">
              {["Requirement", "Criticality", "Design", "Commit", "Test", "Trace Complete?"].map((h) => (
                <th key={h} className="text-left text-xs uppercase tracking-wider text-gray-600 font-bold py-2 px-3">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data?.rows.map((r) => (
              <tr key={r.requirement_id} data-testid={`trace-row-${r.requirement_id}`} className="hover:bg-gray-50 transition-colors duration-100">
                <td className="border-b border-gray-200 py-2 px-3 font-mono text-xs font-bold align-top">{r.requirement_id}</td>
                <td className="border-b border-gray-200 py-2 px-3 align-top">{r.criticality}</td>
                <td className="border-b border-gray-200 py-2 px-3 text-xs align-top">{r.design_ids.join(", ") || "—"}</td>
                <td className="border-b border-gray-200 py-2 px-3 text-xs align-top">{r.commit_ids.join(", ") || "—"}</td>
                <td className="border-b border-gray-200 py-2 px-3 text-xs align-top">{r.test_ids.join(", ") || "—"}</td>
                <td className="border-b border-gray-200 py-2 px-3 align-top">
                  <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 ${r.trace_complete ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"}`}>
                    {r.trace_complete ? "Complete" : "Gap"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Gap List ({data?.gaps.length || 0})</div>
        <div className="space-y-1">
          {data?.gaps.map((g) => (
            <div key={g.requirement_id} data-testid={`gap-row-${g.requirement_id}`} className="text-sm border-l-4 border-red-500 bg-red-50 px-3 py-1.5">
              <span className="font-mono font-bold">{g.requirement_id}</span> - missing: {g.missing.join(", ")}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
