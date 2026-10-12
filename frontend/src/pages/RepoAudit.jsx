import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";

const SEV_STYLE = { critical: "bg-red-600 text-white", high: "bg-red-100 text-red-800", medium: "bg-[#FFE600] text-black", low: "bg-gray-200 text-gray-700" };
const GATE_STYLE = { "Ready": "text-green-700", "At Risk": "text-red-700", "Not Assessed": "text-gray-400", "Not Started": "text-gray-400" };

export default function RepoAudit() {
  const { setProjectId, refreshProjects } = useProject();
  const navigate = useNavigate();
  const [url, setUrl] = useState("https://github.com/mishraramesh-design/myauction-node");
  const [result, setResult] = useState(null);

  const audit = useMutation({
    mutationFn: () => api.post("/repo-audit/ingest", { github_url: url }),
    onSuccess: async (res) => {
      setResult(res.data);
      await refreshProjects();
      setProjectId(res.data.project.id);
      toast.success(`Audited ${res.data.project.name} · ${res.data.finding_summary.total} findings`);
    },
    onError: (e) => toast.error(e?.response?.data?.detail || "Audit failed"),
  });

  return (
    <div data-testid="repo-audit-page">
      <PageHeader title="Repo Audit (A21 Stack Profiler)" subtitle="EC-05: the platform clones a public GitHub repository read-only, profiles its stack, runs the deterministic detectors over the real source, and generates the author & team-lead reports plus the gate pack. Observe and advise only — nothing is written back." />

      <div className="border border-gray-200 p-5 mb-6 flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[320px]">
          <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Public GitHub Repository URL</label>
          <input data-testid="repo-url-input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/org/repo" className="w-full border border-gray-300 px-3 py-2 text-sm font-mono" />
        </div>
        <button data-testid="run-repo-audit-btn" onClick={() => audit.mutate()} disabled={!url || audit.isPending} className="bg-[#FFE600] text-black hover:bg-black hover:text-[#FFE600] font-bold tracking-tight px-4 py-2 text-xs border border-black transition-colors duration-100 disabled:opacity-50">
          {audit.isPending ? "Cloning & scanning…" : "Run Live Audit"}
        </button>
      </div>

      {audit.isPending && <div className="text-sm text-gray-400 mb-4">Cloning the repository and running all detectors — this can take up to a minute…</div>}

      {result && (
        <div data-testid="repo-audit-result" className="space-y-6">
          {/* Stack profile */}
          <div className="border border-gray-200 p-4">
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500 mb-2">Stack profile · {result.project.name} · suggested tier {result.project.integrity_tier}</div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
              <div><div className="text-[10px] uppercase text-gray-400 mb-1">Languages</div>{Object.entries(result.profile.languages).map(([l, c]) => <span key={l} className="inline-block text-xs bg-gray-100 px-1.5 py-0.5 mr-1 mb-1">{l} · {c}</span>)}</div>
              <div><div className="text-[10px] uppercase text-gray-400 mb-1">Frameworks</div>{result.profile.frameworks.length ? result.profile.frameworks.map((f) => <span key={f} className="inline-block text-xs bg-black text-[#FFE600] px-1.5 py-0.5 mr-1 mb-1">{f}</span>) : "—"}</div>
              <div><div className="text-[10px] uppercase text-gray-400 mb-1">Scope</div><div className="text-xs">{result.profile.code_files_scanned} files · ~{result.profile.approx_loc.toLocaleString()} LOC scanned</div></div>
            </div>
          </div>

          {/* Findings summary */}
          <div className="border border-gray-200 p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">Findings · {result.finding_summary.total} total ({result.finding_summary.fail} FAIL)</div>
              <button data-testid="open-findings-btn" onClick={() => navigate("/findings")} className="text-[10px] uppercase font-bold border border-black px-2 py-1 hover:bg-black hover:text-[#FFE600]">Open in Findings Explorer →</button>
            </div>
            <div className="flex flex-wrap gap-2 mb-3">
              {Object.entries(result.finding_summary.by_severity).map(([s, c]) => (
                <span key={s} data-testid={`sev-${s}`} className={`text-[11px] font-bold uppercase px-2 py-0.5 ${SEV_STYLE[s] || "bg-gray-100"}`}>{s}: {c}</span>
              ))}
            </div>
            <div className="text-xs text-gray-600">{Object.entries(result.finding_summary.by_control).map(([k, v]) => <div key={k}>{k}: {v}</div>)}</div>
          </div>

          {/* Reports */}
          {result.reports.map((r) => (
            <div key={r.id} data-testid={`report-${r.type}`} className="border border-gray-200 p-4">
              <div className="flex items-center justify-between mb-1">
                <div className="font-[Chivo] font-bold text-sm">{r.title}</div>
                <span className="text-[10px] font-mono text-gray-400">ledger {r.ledger_hash?.slice(0, 12)}…</span>
              </div>
              <p className="text-sm text-gray-800 whitespace-pre-wrap mb-3">{r.narrative}</p>
              {r.sections.map((sec, i) => (
                <div key={i} className="mb-2">
                  <div className="text-[10px] font-bold uppercase tracking-wider text-gray-400">{sec.heading}</div>
                  <ul className="text-xs text-gray-700 list-disc ml-4">{sec.body.slice(0, 8).map((b, j) => <li key={j}>{b}</li>)}</ul>
                </div>
              ))}
            </div>
          ))}

          {/* Gate pack */}
          <div className="border border-gray-200 p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500">Gate pack</div>
              <button data-testid="open-gates-btn" onClick={() => navigate("/gates")} className="text-[10px] uppercase font-bold border border-black px-2 py-1 hover:bg-black hover:text-[#FFE600]">Open Gate Readiness →</button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              {result.gates.map((g) => (
                <div key={g.id} data-testid={`gate-${g.id}`} className="border border-gray-200 p-2">
                  <div className="font-mono text-xs font-bold">{g.id}</div>
                  <div className="text-[10px] text-gray-500 leading-tight mb-1">{g.name}</div>
                  <div className={`text-xs font-bold ${GATE_STYLE[g.status] || ""}`}>{g.status}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
