import { useState, useEffect, useRef } from "react";
import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import api, { downloadAuthed } from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";

const SEV_STYLE = { critical: "bg-red-600 text-white", high: "bg-red-100 text-red-800", medium: "bg-[#FFE600] text-black", low: "bg-gray-200 text-gray-700" };
const GATE_STYLE = { "Ready": "text-green-700", "At Risk": "text-red-700", "Not Assessed": "text-gray-400", "Not Started": "text-gray-400" };

export default function RepoAudit() {
  const { setProjectId, refreshProjects } = useProject();
  const navigate = useNavigate();
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [branch, setBranch] = useState("");
  const [level, setLevel] = useState(3);
  const [sensitivity, setSensitivity] = useState("unknown");
  const [fmap, setFmap] = useState([]);
  const [job, setJob] = useState(null);
  const [result, setResult] = useState(null);
  const timer = useRef(null);
  const PURPOSES = ["source", "tests", "config", "infra", "docs", "generated", "other"];

  const stop = () => { if (timer.current) { clearInterval(timer.current); timer.current = null; } };
  useEffect(() => stop, []);

  const finish = async (jobId) => {
    const j = (await api.get(`/repo-audit/jobs/${jobId}`)).data;
    setJob(j);
    if (j.status === "done") {
      stop();
      await refreshProjects();
      setProjectId(j.project_id);
      const p = await api.get("/projects");
      setResult({ project: p.data.find((x) => x.id === j.project_id) || { id: j.project_id, name: j.github_url },
        diff: j.diff, finding_summary: j.finding_summary, coverage: j.coverage });
      toast.success(`Audit complete · ${j.finding_summary.total} findings`);
    } else if (j.status === "failed" || j.status === "cancelled") {
      stop();
      toast.error(j.status === "failed" ? (j.error || "Audit failed") : "Audit cancelled");
    }
  };

  const audit = useMutation({
    mutationFn: () => api.post("/repo-audit/ingest", {
      github_url: url, git_token: token || null, branch: branch || null,
      integrity_level: Number(level), data_sensitivity: sensitivity,
      folder_map: fmap.filter((r) => r.path.trim()),
    }),
    onSuccess: (res) => {
      setResult(null);
      setToken("");
      const id = res.data.job_id;
      setJob({ id, status: "queued" });
      stop();
      timer.current = setInterval(() => finish(id).catch(() => {}), 2000);
    },
    onError: (e) => toast.error(e?.response?.data?.detail?.[0]?.msg || e?.response?.data?.detail || "Audit failed"),
  });

  const running = job && ["queued", "cloning", "scanning", "analysing"].includes(job.status);
  const cancel = () => api.post(`/repo-audit/jobs/${job.id}/cancel`).catch((e) => toast.error(e?.response?.data?.detail || "Cannot cancel"));
  const setRow = (i, k, v) => setFmap(fmap.map((r, j) => (j === i ? { ...r, [k]: v } : r)));

  return (
    <div data-testid="repo-audit-page">
      <PageHeader title="Repo Audit (A21 Stack Profiler)" subtitle="EC-05: the platform clones a public GitHub repository read-only, profiles its stack, runs the deterministic detectors over the real source, and generates the author & team-lead reports plus the gate pack. Observe and advise only — nothing is written back." />

      <div className="border border-gray-200 p-5 mb-6 space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex-1 min-w-[320px]">
            <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">GitHub repository URL</label>
            <input data-testid="repo-url-input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/org/repo" className="w-full border border-gray-300 px-3 py-2 text-sm font-mono" />
          </div>
          <div className="w-40">
            <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Branch (default if empty)</label>
            <input data-testid="repo-branch-input" value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="main" className="w-full border border-gray-300 px-3 py-2 text-sm font-mono" />
          </div>
          <div className="min-w-[220px]">
            <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Read-only git token (private repo)</label>
            <input data-testid="repo-token-input" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} placeholder="not stored, not logged" className="w-full border border-gray-300 px-3 py-2 text-sm font-mono" />
          </div>
        </div>
        <div className="flex flex-wrap gap-3">
          <div>
            <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Integrity level (IEEE 1012)</label>
            <select data-testid="repo-level" value={level} onChange={(e) => setLevel(e.target.value)} className="border border-gray-300 px-2 py-2 text-sm">
              <option value={4}>4 – highest</option><option value={3}>3 – high</option><option value={2}>2 – medium</option><option value={1}>1 – low</option>
            </select>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Data sensitivity</label>
            <select data-testid="repo-sensitivity" value={sensitivity} onChange={(e) => setSensitivity(e.target.value)} className="border border-gray-300 px-2 py-2 text-sm">
              {["unknown", "none", "internal", "personal", "sensitive-personal", "financial"].map((x) => <option key={x}>{x}</option>)}
            </select>
          </div>
        </div>
        <div>
          <div className="flex items-center justify-between mb-1">
            <div className="text-[10px] uppercase tracking-wider font-bold text-gray-500">Folder map (optional — tells the audit what each folder is and which module owns it)</div>
            <button data-testid="add-folder-row" onClick={() => setFmap([...fmap, { path: "", purpose: "source", module: "" }])} className="text-[10px] uppercase font-bold border border-black px-2 py-1 hover:bg-black hover:text-[#FFE600]">+ Add folder</button>
          </div>
          {fmap.length > 0 && (
            <table className="w-full text-xs"><tbody>
              {fmap.map((r, i) => (
                <tr key={i} className="border-b border-gray-100">
                  <td className="py-1 pr-2"><input aria-label="folder path" value={r.path} onChange={(e) => setRow(i, "path", e.target.value)} placeholder="src/bidding" className="w-full border border-gray-300 px-2 py-1 font-mono" /></td>
                  <td className="py-1 pr-2 w-32"><select aria-label="purpose" value={r.purpose} onChange={(e) => setRow(i, "purpose", e.target.value)} className="w-full border border-gray-300 px-1 py-1">{PURPOSES.map((x) => <option key={x}>{x}</option>)}</select></td>
                  <td className="py-1 pr-2 w-48"><input aria-label="module" value={r.module || ""} onChange={(e) => setRow(i, "module", e.target.value)} placeholder="module e.g. Bidding" className="w-full border border-gray-300 px-2 py-1" /></td>
                  <td className="py-1 w-8"><button aria-label="remove folder" onClick={() => setFmap(fmap.filter((_, j) => j !== i))} className="text-gray-400 hover:text-red-600">✕</button></td>
                </tr>
              ))}
            </tbody></table>
          )}
          <p className="text-[11px] text-gray-400 mt-1">“generated” folders are skipped. Personal-data patterns inside “tests” are reported at low severity; secrets are never reduced.</p>
        </div>
        <div className="flex gap-2">
          <button data-testid="run-repo-audit-btn" onClick={() => audit.mutate()} disabled={!url || audit.isPending || running} className="bg-[#FFE600] text-black hover:bg-black hover:text-[#FFE600] font-bold tracking-tight px-4 py-2 text-xs border border-black transition-colors duration-100 disabled:opacity-50">
            {running ? "Audit running…" : "Run Audit"}
          </button>
          {running && <button data-testid="cancel-audit-btn" onClick={cancel} className="border border-black px-4 py-2 text-xs font-bold hover:bg-black hover:text-white">Cancel</button>}
        </div>
      </div>

      {job && (
        <div data-testid="job-status" className="border border-gray-200 p-3 mb-4 text-sm flex flex-wrap gap-4 items-center">
          <span className="text-[10px] uppercase font-bold tracking-wider">Status</span>
          <span className={`font-bold ${job.status === "failed" ? "text-red-700" : job.status === "done" ? "text-green-700" : ""}`}>{job.status}</span>
          {job.files != null && <span className="text-xs text-gray-500">{job.files} files scanned so far</span>}
          {job.error && <span className="text-xs text-red-700">{job.error}</span>}
        </div>
      )}

      {result && (
        <div data-testid="repo-audit-result" className="space-y-6">
          {/* Evidence pack export */}
          <div className="border border-gray-200 p-4 flex flex-wrap items-center justify-between gap-2 bg-gray-50">
            <div>
              <div className="font-[Chivo] font-bold text-sm">Evidence Pack</div>
              <p className="text-xs text-gray-500">One-click auditor bundle: profile, findings, reports, API traceability and ledger hashes.</p>
            </div>
            <div className="flex gap-2">
              <button data-testid="download-pdf-btn" onClick={() => downloadAuthed(`/repo-audit/${result.project.id}/evidence-pack?format=pdf`, "evidence_pack.pdf")} className="text-xs font-bold bg-black text-white px-3 py-2 hover:bg-[#FFE600] hover:text-black transition-colors">Download PDF</button>
              <button data-testid="download-docx-btn" onClick={() => downloadAuthed(`/repo-audit/${result.project.id}/evidence-pack?format=docx`, "evidence_pack.docx")} className="text-xs font-bold border border-black px-3 py-2 hover:bg-black hover:text-[#FFE600] transition-colors">Download DOCX</button>
            </div>
          </div>
          {result.diff && (
            <div data-testid="audit-diff" className="border border-gray-200 p-4 flex flex-wrap gap-6 text-sm">
              <span><b>{result.diff.new}</b> new</span><span><b>{result.diff.unchanged}</b> unchanged</span><span><b>{result.diff.resolved}</b> resolved (archived, not deleted)</span>
            </div>
          )}
          {result.coverage && (
            <div data-testid="audit-coverage" className="border border-gray-200 p-4 text-xs text-gray-700">
              <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500 mb-1">Coverage — what was and was not scanned</div>
              {result.coverage.files_scanned} of {result.coverage.files_seen} candidate files scanned · skipped: {result.coverage.skipped_generated} generated, {result.coverage.skipped_large} too large (&gt;{Math.round(result.coverage.max_bytes / 1024)} KB), {result.coverage.skipped_unreadable} unreadable, {result.coverage.skipped_over_cap} over the {result.coverage.max_files} file cap.
            </div>
          )}
          {/* Stack profile */}
          {result.profile && <div className="border border-gray-200 p-4">
            <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500 mb-2">Stack profile · {result.project.name} · integrity level {result.project.integrity_level}</div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
              <div><div className="text-[10px] uppercase text-gray-400 mb-1">Languages</div>{Object.entries(result.profile.languages).map(([l, c]) => <span key={l} className="inline-block text-xs bg-gray-100 px-1.5 py-0.5 mr-1 mb-1">{l} · {c}</span>)}</div>
              <div><div className="text-[10px] uppercase text-gray-400 mb-1">Frameworks</div>{result.profile.frameworks.length ? result.profile.frameworks.map((f) => <span key={f} className="inline-block text-xs bg-black text-[#FFE600] px-1.5 py-0.5 mr-1 mb-1">{f}</span>) : "—"}</div>
              <div><div className="text-[10px] uppercase text-gray-400 mb-1">Scope</div><div className="text-xs">{result.profile.code_files_scanned} files · ~{result.profile.approx_loc.toLocaleString()} LOC scanned</div></div>
            </div>
          </div>}

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

          {!result.reports && (
            <div className="border border-gray-200 p-4 text-sm flex gap-2 items-center">
              Reports and gates for this audit:
              <button onClick={() => navigate("/reports")} className="text-[10px] uppercase font-bold border border-black px-2 py-1 hover:bg-black hover:text-[#FFE600]">Reports →</button>
              <button onClick={() => navigate("/gates")} className="text-[10px] uppercase font-bold border border-black px-2 py-1 hover:bg-black hover:text-[#FFE600]">Gate Readiness →</button>
            </div>
          )}
          {/* Reports */}
          {(result.reports || []).map((r) => (
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

          {/* API traceability */}
          {result.audit?.endpoints?.length > 0 && (
            <div className="border border-gray-200 p-4" data-testid="traceability-section">
              <div className="text-[10px] font-bold uppercase tracking-[0.2em] text-gray-500 mb-2">
                API Traceability · {result.audit.endpoint_count} endpoints ({result.audit.endpoints.filter((e) => !e.tested_by?.length).length} untested)
              </div>
              <div className="overflow-x-auto max-h-72 overflow-y-auto border border-gray-100">
                <table className="w-full text-xs">
                  <thead><tr className="bg-gray-50 border-b border-gray-200">
                    {["Method", "Path", "Defined in", "Tested by"].map((h) => <th key={h} className="text-left px-2 py-1.5 text-[10px] uppercase tracking-wider text-gray-500">{h}</th>)}
                  </tr></thead>
                  <tbody>
                    {result.audit.endpoints.slice(0, 60).map((e, i) => (
                      <tr key={i} data-testid={`endpoint-row-${i}`} className="border-b border-gray-100">
                        <td className="px-2 py-1 font-mono font-bold">{e.method}</td>
                        <td className="px-2 py-1 font-mono">{e.path}</td>
                        <td className="px-2 py-1 text-gray-500 truncate max-w-[200px]">{e.defined_in}</td>
                        <td className="px-2 py-1">{e.tested_by?.length ? <span className="text-green-700">{e.tested_by.length} test(s)</span> : <span className="text-red-700 font-bold">untested</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Gate pack */}
          {result.gates && <div className="border border-gray-200 p-4">
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
          </div>}
        </div>
      )}
    </div>
  );
}
