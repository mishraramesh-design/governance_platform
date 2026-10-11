import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";

export default function RepoAudit() {
  const { projectId } = useProject();
  const [url, setUrl] = useState("");
  const [result, setResult] = useState(null);

  const audit = useMutation({
    mutationFn: () => api.post("/repo-audit/simulate", { project_id: projectId, github_url: url }),
    onSuccess: (res) => {
      setResult(res.data);
      toast.success("Repo audit simulated");
    },
  });

  return (
    <div data-testid="repo-audit-page">
      <PageHeader title="Repo Audit" subtitle="EC-05: central repository audit, platform-run. This prototype simulates the audit - no live repository is accessed." />

      <div className="border border-gray-200 p-5 mb-6 flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[260px]">
          <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">GitHub Repository URL</label>
          <input data-testid="repo-url-input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/org/repo" className="w-full border border-gray-300 px-3 py-2 text-sm" />
        </div>
        <button data-testid="run-repo-audit-btn" onClick={() => audit.mutate()} disabled={!url || audit.isPending} className="bg-[#FFE600] text-black hover:bg-[#F0D800] font-bold tracking-tight rounded-none px-4 py-2 text-xs border border-black transition-colors duration-100 disabled:opacity-50">
          {audit.isPending ? "Auditing…" : "Run Simulated Audit"}
        </button>
      </div>

      {result && (
        <div data-testid="repo-audit-result" className="border border-black p-5 bg-gray-50">
          <div className="text-[10px] font-bold uppercase tracking-wider text-gray-500 mb-2">{result.note}</div>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div><span className="font-bold text-gray-600">Detected languages:</span> {result.detected_languages.join(", ")}</div>
            <div><span className="font-bold text-gray-600">Suggested integrity tier:</span> {result.suggested_integrity_tier}</div>
            <div className="col-span-2"><span className="font-bold text-gray-600">Folder map:</span> {result.folder_map.join(", ")}</div>
          </div>
        </div>
      )}
    </div>
  );
}
