import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import api from "../lib/api";
import { PageHeader } from "../components/PageHeader";

const stateStyle = {
  ready: "text-green-800 bg-green-50",
  planned_execution_available: "text-blue-800 bg-blue-50",
  completed_source_scan: "text-green-800 bg-green-50",
  authorization_required: "text-amber-900 bg-amber-50",
  blocked_missing_input: "text-gray-600 bg-gray-100",
  planned_requires_repository_test_execution: "text-blue-800 bg-blue-50",
  drafts_require_review: "text-purple-900 bg-purple-50",
  signals_detected_review_required: "text-amber-900 bg-amber-50",
  not_executed_no_scanner_adapter: "text-amber-900 bg-amber-50",
  not_executed_requires_test_environment_and_limits: "text-amber-900 bg-amber-50",
  advisory_readiness_only: "text-purple-900 bg-purple-50",
};

export default function Studio() {
  const [pollError, setPollError] = useState(false);
  const [clockNow, setClockNow] = useState(Date.now());
  const [runs, setRuns] = useState([]);
  const [result, setResult] = useState(null);
  const [webScanMode, setWebScanMode] = useState("passive");
  const [activeScanStagingConfirmed, setActiveScanStagingConfirmed] = useState(false);
  const [excludedPaths, setExcludedPaths] = useState("");
  const [framework, setFramework] = useState("playwright");
  const [frameworkAuthorized, setFrameworkAuthorized] = useState(false);
  const [openapiUrl, setOpenapiUrl] = useState("");
  const [maxExamples, setMaxExamples] = useState(10);
  const [k6Vus, setK6Vus] = useState(2);
  const [k6Duration, setK6Duration] = useState(15);
  const [k6P95, setK6P95] = useState(1000);
  const [k6ErrorRate, setK6ErrorRate] = useState(1);
  const [form, setForm] = useState({
    name: "", github_url: "", target_url: "", authorization_confirmed: false,
    authorization_owner: "", authorization_reference: "", authorization_scope: "",
    duration_hours: 2, frs_text: "", frs_file: null, runtime_logs: "",
  });

  const refreshRuns = () => api.get("/studio/runs").then((r) => setRuns(r.data)).catch(() => setRuns([]));
  useEffect(() => { refreshRuns(); }, []);

  const createRun = useMutation({
    mutationFn: () => {
      const values = {
      ...form,
      github_url: form.github_url.trim() || null,
      target_url: form.target_url.trim() || null,
      authorization_scope: form.authorization_scope.trim() || null,
      authorization_owner: form.authorization_owner.trim() || null,
      authorization_reference: form.authorization_reference.trim() || null,
      frs_text: form.frs_text || null,
      runtime_logs: form.runtime_logs || null,
      duration_hours: Number(form.duration_hours),
      };
      if (!form.frs_file) return api.post("/studio/runs", values);
      const body = new FormData();
      Object.entries(values).filter(([key, value]) => key !== "frs_file" && key !== "frs_text" && value !== null && value !== undefined).forEach(([key, value]) => body.append(key, String(value)));
      body.append("frs_file", form.frs_file);
      return api.post("/studio/runs/upload", body);
    },
    onSuccess: (response) => {
      setResult(response.data);
      refreshRuns();
      toast.success("Governance assessment plan created and recorded");
    },
    onError: (error) => toast.error(error?.response?.data?.detail || "Could not create assessment plan"),
  });

  const runRepositoryAudit = useMutation({
    mutationFn: () => api.post(`/studio/runs/${result.id}/repository-audit`),
    onSuccess: (response) => {
      setResult(response.data);
      refreshRuns();
      toast.success(`Source audit completed · ${response.data.repository_audit?.finding_summary?.total ?? 0} findings`);
    },
    onError: (error) => toast.error(error?.response?.data?.detail || "Repository source audit failed"),
  });

  const runWebSecurityScan = useMutation({
    mutationFn: () => api.post("/studio/runs/" + result.id + "/web-security-scan", {
      mode: webScanMode,
      active_scan_staging_confirmed: webScanMode === "active" && activeScanStagingConfirmed,
      excluded_paths: excludedPaths.split(String.fromCharCode(10)).map((path) => path.trim()).filter(Boolean),
    }),
    onSuccess: async () => {
      const response = await api.get(`/studio/runs/${result.id}`);
      setResult(response.data);
      refreshRuns();
      toast.success((webScanMode === "active" ? "Active" : "Passive") + " web security assessment queued");
    },
    onError: (error) => toast.error(error?.response?.data?.detail || "Could not start web security assessment"),
  });

  const cancelWebScan = useMutation({
    mutationFn: () => api.post(`/studio/runs/${result.id}/web-security-scan/cancel`),
    onSuccess: () => { setResult((current) => ({ ...current, web_security_scan: { ...current.web_security_scan, cancel_requested: true } })); toast.info("Stop requested; waiting for scanner cleanup"); },
    onError: (error) => toast.error(error?.response?.data?.detail || "Could not request scanner stop"),
  });

  useEffect(() => {
    const timer = setInterval(() => setClockNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const runFrameworkAssessment = useMutation({
    mutationFn: () => api.post(`/studio/runs/${result.id}/framework-assessment`, {
      framework, staging_authorized: frameworkAuthorized,
      ...(framework === "schemathesis" ? { openapi_url: openapiUrl, max_examples: Number(maxExamples) } : {}),
      ...(framework === "k6" ? { virtual_users: Number(k6Vus), duration_seconds: Number(k6Duration), max_p95_ms: Number(k6P95), max_error_rate_percent: Number(k6ErrorRate) } : {}),
    }),
    onSuccess: async () => {
      const response = await api.get(`/studio/runs/${result.id}`);
      setResult(response.data);
      refreshRuns();
      toast.success(`${framework} assessment queued`);
    },
    onError: (error) => toast.error(error?.response?.data?.detail || "Could not start framework assessment"),
  });

  useEffect(() => {
    if (!result?.id || (!["queued", "running"].includes(result.web_security_scan?.status) && !["queued", "running"].includes(result.framework_assessment?.status))) return undefined;
    const timer = setInterval(() => {
      api.get(`/studio/runs/${result.id}`).then((response) => { setResult((current) => current?.id === response.data.id ? response.data : current); setPollError(false); }).catch(() => setPollError(true));
    }, 3000);
    return () => clearInterval(timer);
  }, [result?.id, result?.web_security_scan?.status, result?.framework_assessment?.status]);

  const update = (key) => (event) => setForm((current) => ({
    ...current,
    [key]: event.target.type === "checkbox" ? event.target.checked : event.target.value,
  }));

  return (
    <div data-testid="governance-studio-page">
      <PageHeader title="Governance AI Studio" subtitle="One governed intake for repository, requirements, web target and runtime evidence. Deterministic checks produce evidence; models can assist analysis, while accountable humans retain gate decisions." />
      <Link to="/testing-workspace" className="inline-block mb-5 border border-black bg-black text-[#FFE600] px-4 py-3 text-sm font-bold">Open AI Testing Workspace - browser and chat</Link>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.7fr)] gap-6">
        <form onSubmit={(event) => { event.preventDefault(); createRun.mutate(); }} className="border border-gray-200 p-5 space-y-4">
          <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500">New IV&amp;V assessment</div>
          <label className="block text-xs font-bold">Assessment name
            <input required maxLength={120} value={form.name} onChange={update("name")} className="mt-1 w-full border border-gray-300 px-3 py-2 text-sm font-normal" placeholder="Release 2.4 independent assurance" />
          </label>
          <label className="block text-xs font-bold">GitHub repository URL <span className="font-normal text-gray-400">(optional, source audit runs separately)</span>
            <input value={form.github_url} onChange={update("github_url")} className="mt-1 w-full border border-gray-300 px-3 py-2 text-sm font-mono font-normal" placeholder="https://github.com/org/repository" />
          </label>
          <label className="block text-xs font-bold">Deployed application URL <span className="font-normal text-gray-400">(optional; this step will not contact it)</span>
            <input value={form.target_url} onChange={update("target_url")} className="mt-1 w-full border border-gray-300 px-3 py-2 text-sm font-mono font-normal" placeholder="https://staging.example.com" />
          </label>
          {form.target_url.trim() && <div className="border border-amber-300 bg-amber-50 p-3 space-y-2">
            <label className="flex items-start gap-2 text-xs"><input type="checkbox" checked={form.authorization_confirmed} onChange={update("authorization_confirmed")} className="mt-0.5" /><span>I have written authorization from the system owner for assessment of this target.</span></label>
            <div className="grid md:grid-cols-2 gap-2">
              <label className="block text-xs font-bold">Authorizing owner<input required value={form.authorization_owner} onChange={update("authorization_owner")} maxLength={200} className="mt-1 w-full border border-amber-300 bg-white px-3 py-2 text-xs font-normal" placeholder="Owner name / accountable role" /></label>
              <label className="block text-xs font-bold">Approval or ticket reference<input required value={form.authorization_reference} onChange={update("authorization_reference")} maxLength={200} className="mt-1 w-full border border-amber-300 bg-white px-3 py-2 text-xs font-normal" placeholder="Change record / authorization ID" /></label>
            </div>
            <label className="block text-xs font-bold">Exact authorized host/path, exclusions and stop conditions
              <textarea required value={form.authorization_scope} onChange={update("authorization_scope")} rows={2} maxLength={2000} className="mt-1 w-full border border-amber-300 bg-white px-3 py-2 text-xs font-normal" placeholder="example.com/staging/*; exclude /billing/export; stop on elevated error rate" />
            </label>
          </div>}
          <label className="block text-xs font-bold">Authorized assessment window (hours)
            <input type="number" min="1" max="168" value={form.duration_hours} onChange={update("duration_hours")} className="mt-1 w-32 border border-gray-300 px-3 py-2 text-sm font-normal" />
          </label>
          <label className="block text-xs font-bold">FRS / requirements text <span className="font-normal text-gray-400">(processed in memory; candidate statements are saved masked)</span>
            <textarea value={form.frs_text} onChange={update("frs_text")} rows={5} maxLength={2000000} className="mt-1 w-full border border-gray-300 px-3 py-2 text-xs font-mono font-normal" placeholder="Paste requirement lines containing shall, must, or requirement IDs…" />
          </label>
          <label className="block text-xs font-bold">Or upload an FRS document <span className="font-normal text-gray-400">(TXT, Markdown, DOCX or PDF; 2 MB maximum)</span>
            <input type="file" accept=".txt,.md,.docx,.pdf" onChange={(event) => setForm((current) => ({ ...current, frs_file: event.target.files?.[0] || null }))} className="mt-1 block w-full text-xs file:mr-3 file:border file:border-gray-300 file:bg-white file:px-3 file:py-2" />
          </label>
          <label className="block text-xs font-bold">Runtime logs <span className="font-normal text-gray-400">(summary and content hash retained; raw logs are discarded)</span>
            <textarea value={form.runtime_logs} onChange={update("runtime_logs")} rows={4} maxLength={2000000} className="mt-1 w-full border border-gray-300 px-3 py-2 text-xs font-mono font-normal" placeholder="Paste a bounded log window…" />
          </label>
          <button data-testid="create-studio-run" type="submit" disabled={createRun.isPending} className="bg-black text-[#FFE600] px-4 py-2 text-xs font-bold disabled:opacity-50">
            {createRun.isPending ? "Creating evidence plan…" : "Create governed assessment plan"}
          </button>
          <p className="text-[11px] text-gray-500">This action stores scope, input hashes, requirement candidates and deterministic summaries. It does not launch web penetration or load tests.</p>
        </form>

        <section className="border border-gray-200 p-5 h-fit">
          <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-3">Studio guardrails</div>
          <ul className="space-y-2 text-xs text-gray-700 list-disc pl-4">
            <li>Target URLs require explicit written-authorization confirmation and exact scope.</li>
            <li>The intake endpoint makes no network request to the target.</li>
            <li>No credentials, destructive tests, persistence or cross-scope activity.</li>
            <li>Candidate requirements need owner review; no fabricated trace links.</li>
            <li>CMMI artifacts support readiness evidence; the platform does not claim a maturity rating.</li>
          </ul>
        </section>
      </div>

      {result && <section className="mt-6 border border-black" data-testid="studio-run-result">
        <div className="bg-black text-white px-4 py-3 flex items-center justify-between gap-3">
          <div><div className="text-[10px] uppercase tracking-[0.2em] text-gray-300">Plan recorded · {result.id.slice(0, 8)}</div><h2 className="font-bold">{result.name}</h2></div>
          <span className="text-[10px] uppercase border border-[#FFE600] text-[#FFE600] px-2 py-1">{result.status.replaceAll("_", " ")} · evidence ledgered</span>
        </div>
        <div className="p-4 grid md:grid-cols-2 xl:grid-cols-5 gap-3 text-xs">
          <div className="border border-gray-200 p-3"><div className="text-[10px] uppercase text-gray-400">Requirement candidates</div><strong>{result.requirements_candidate_count}</strong></div>
          <div className="border border-gray-200 p-3"><div className="text-[10px] uppercase text-gray-400">Runtime errors / 5xx</div><strong>{result.runtime_summary ? `${result.runtime_summary.error_lines} / ${result.runtime_summary.http_5xx_lines}` : "No logs supplied"}</strong></div>
          <div className="border border-gray-200 p-3"><div className="text-[10px] uppercase text-gray-400">Known sensitive log signals</div><strong>{result.runtime_summary ? `${result.runtime_summary.secret_signal_count ?? 0} secret · ${result.runtime_summary.pii_signal_count ?? 0} PII` : "No logs supplied"}</strong><div className="mt-1 text-[10px] text-gray-500">{result.runtime_summary?.sensitive_data_review?.replaceAll("_", " ") || "Raw logs are not retained"}</div></div>
          <div className="border border-gray-200 p-3"><div className="text-[10px] uppercase text-gray-400">Test outlines · not executed</div><strong>{result.test_case_draft_count ?? 0}</strong></div>
          <div className="border border-gray-200 p-3"><div className="text-[10px] uppercase text-gray-400">Target contact</div><strong>{result.web_security_scan?.status === "completed" ? "Contacted by approved scan" : ["queued", "running"].includes(result.web_security_scan?.status) ? "Web assessment in progress" : result.web_security_scan ? "Contact status uncertain; inspect scan evidence" : "Not contacted"}</strong></div>
        </div>
        <div className="px-4 pb-4 space-y-2">
          <h3 className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500">Deterministic stage plan and gaps</h3>
          {result.plan.map((step) => <div key={step.id} className="border border-gray-200 p-3 flex flex-col md:flex-row md:items-center gap-2 md:gap-4">
            <div className="w-24 shrink-0"><div className="font-mono text-xs font-bold">{step.id}</div><div className="text-[10px] text-gray-400">{step.stage}</div></div>
            <div className="flex-1 text-xs">{step.activity}<div className="text-[10px] text-gray-400 mt-1">Evidence: {step.evidence}</div></div>
            <span className={`text-[9px] uppercase font-bold px-2 py-1 ${stateStyle[step.state] || "bg-gray-100"}`}>{step.state.replaceAll("_", " ")}</span>
          </div>)}
        </div>
        {result.test_case_drafts?.length > 0 && <section className="px-4 pb-4" data-testid="studio-test-case-drafts">
          <h3 className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Trace-linked test design drafts</h3>
          <p className="text-[11px] text-gray-600 mb-2">These deterministic outlines link to extracted requirement candidates. They are not executable tests or pass/fail evidence; approve the setup and measurable assertion before implementation.</p>
          <div className="space-y-2">{result.test_case_drafts.map((testCase) => <article key={testCase.id} className="border border-gray-200 p-3 text-xs">
            <div className="flex flex-wrap items-center gap-2"><strong className="font-mono">{testCase.id}</strong><span className="uppercase text-[9px] bg-gray-100 px-2 py-1">{testCase.category}</span><span className="text-gray-500">Traces to {testCase.source_requirement_id} · line {testCase.source_line}</span><span className="ml-auto text-[9px] uppercase text-purple-800">Draft · review required</span></div>
            <div className="mt-2 font-semibold">{testCase.title}</div><p className="mt-1">Requirement: {testCase.objective}</p>
            <p className="mt-1 text-gray-600">Expected: {testCase.expected_result}</p>
            <p className="mt-1 text-[10px] text-gray-500">Suggested runner: {testCase.recommended_runner}. {testCase.review_note}</p>
          </article>)}</div>
        </section>}
        {result.framework_catalog?.length > 0 && <section className="px-4 pb-4" data-testid="studio-framework-catalog">
          <h3 className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Framework support and runtime availability</h3>
          <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-2">{result.framework_catalog.map((framework) => <article key={framework.id} className="border border-gray-200 p-3 text-xs">
            <div className="flex justify-between gap-2"><strong>{framework.name}</strong><span className={`text-[9px] uppercase ${framework.status === "available" ? "text-green-800" : "text-amber-800"}`}>{framework.status.replaceAll("_", " ")}</span></div>
            <div className="text-[10px] text-gray-500 mt-1">{framework.stage.replaceAll("_", " ")} · {framework.execution_kind.replaceAll("_", " ")} · {framework.license}</div>
            <p className="mt-2 text-gray-700">{framework.note}</p>
          </article>)}</div>
        </section>}
        {result.source?.target_url && <section className="mx-4 mb-4 border border-blue-300 bg-blue-50 p-4" data-testid="studio-web-security-scan">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-xs font-bold uppercase tracking-wider">Governed web security assessment</h3>
              <p className="text-[11px] text-gray-700 mt-1">OWASP ZAP produces deterministic findings. The configured Security &amp; Privacy Agent prioritizes them; AI never sends requests to the target.</p>
            </div>
          </div>
          <label className="mt-3 block text-xs font-bold">Scan mode
            <select value={webScanMode} onChange={(event) => { setWebScanMode(event.target.value); setActiveScanStagingConfirmed(false); }} className="mt-1 block w-full border border-gray-300 bg-white px-3 py-2 text-xs">
              <option value="passive">Passive baseline (safe default)</option>
              <option value="active">Active assessment (attack requests; staging/test only)</option>
            </select>
          </label>
          <label className="mt-3 block text-xs font-bold">Excluded URL paths <span className="font-normal text-gray-500">(one same-host path per line)</span>
            <textarea value={excludedPaths} onChange={(event) => setExcludedPaths(event.target.value)} rows={3} maxLength={5000} className="mt-1 block w-full border border-gray-300 px-3 py-2 font-mono text-xs font-normal" placeholder={"/logout\n/admin/maintenance"} />
          </label>
          {webScanMode === "active" && <label className="mt-3 flex items-start gap-2 border border-amber-400 bg-amber-50 p-3 text-xs font-normal text-amber-950">
            <input type="checkbox" checked={activeScanStagingConfirmed} onChange={(event) => setActiveScanStagingConfirmed(event.target.checked)} className="mt-0.5" />
            <span>I confirm the system owner explicitly approved low-strength active testing of this exact staging/test target during this assessment window, and a restore/incident contact is available. I understand active checks can affect application state or availability.</span>
          </label>}
          <button type="button" onClick={() => runWebSecurityScan.mutate()} disabled={runWebSecurityScan.isPending || ["queued", "running"].includes(result.web_security_scan?.status) || (webScanMode === "active" && !activeScanStagingConfirmed)} className="mt-3 bg-black text-[#FFE600] px-3 py-2 text-xs font-bold disabled:opacity-50">
            {runWebSecurityScan.isPending ? "Queueing…" : result.web_security_scan?.status === "running" ? "Assessment running…" : result.web_security_scan?.status === "queued" ? "Assessment queued…" : result.web_security_scan?.status === "completed" ? "Run assessment again" : "Run " + webScanMode + " assessment"}
          </button>
          {pollError && <p role="alert" className="text-xs text-red-800 mt-2">Live status unavailable. The scanner may still be running. Do not queue another job.</p>}
          {["queued", "running"].includes(result.web_security_scan?.status) && <div role="status" className="mt-3 text-xs space-y-2" data-testid="scan-live-progress">
            <p>Target: {result.source.target_url}</p>
            <p>Stage: {(result.web_security_scan.stage || "queued").replaceAll("_", " ")}
              {Number.isFinite(result.web_security_scan.progress?.stage_percent) ? ` | ${result.web_security_scan.progress.stage_percent}% of this stage` : ""}
              {Number.isFinite(result.web_security_scan.progress?.pending_records) ? ` | ${result.web_security_scan.progress.pending_records} records pending` : ""}</p>
            <p>Elapsed: {Math.max(0, Math.floor((clockNow - Date.parse(result.web_security_scan.started_at || result.web_security_scan.queued_at)) / 1000))} seconds | Job limit: {result.web_security_scan.job_timeout_seconds || 600} seconds plus cleanup</p>
            {result.web_security_scan.heartbeat_at && <p>Last scanner update: {new Date(result.web_security_scan.heartbeat_at).toLocaleTimeString()}
              {clockNow - Date.parse(result.web_security_scan.heartbeat_at) > 45000 ? " | Update delayed; scanner status needs attention" : ""}</p>}
            <button type="button" disabled={cancelWebScan.isPending || result.web_security_scan.cancel_requested || result.web_security_scan.stage === "ai_triage"} onClick={() => cancelWebScan.mutate()} className="border border-red-600 text-red-800 px-3 py-2 disabled:opacity-50">{result.web_security_scan.stage === "ai_triage" ? "Scanner finished; finalizing report..." : result.web_security_scan.cancel_requested ? "Stopping... waiting for cleanup" : "Stop scan"}</button>
          </div>}
          {result.web_security_scan && <div className="mt-3 border-t border-blue-200 pt-3">
            <div className="text-xs font-bold">{result.web_security_scan.status.replaceAll("_", " ")}{result.web_security_scan.status === "completed" ? ` · ${result.web_security_scan.mode.replaceAll("_", " ")} · ${result.web_security_scan.finding_count} findings · ${result.web_security_scan.scanner?.name} ${result.web_security_scan.scanner?.version} · ${result.web_security_scan.scanner?.coverage_status?.replaceAll("_", " ")}` : ""}</div>
            {result.web_security_scan.error && <p className="text-xs text-red-800 mt-1">{result.web_security_scan.error}</p>}
            {result.web_security_scan.status === "completed" && <>
              <button type="button" className="border border-blue-600 px-3 py-2 text-xs" onClick={() => {
                const blob = new Blob([JSON.stringify({ assessment_id: result.id, assessment_name: result.name, scan: result.web_security_scan }, null, 2)], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const link = document.createElement("a"); link.href = url; link.download = `studio-scan-${result.web_security_scan.attempt_id || result.id}.json`; link.click();
                setTimeout(() => URL.revokeObjectURL(url), 1000);
              }}>Download evidence report (JSON)</button>
              <p className="text-xs mt-2">Target: {result.web_security_scan.target_url} | Duration: {result.web_security_scan.elapsed_seconds ?? "unknown"} seconds</p>
              <p className="text-xs mt-2">{result.web_security_scan.scanner?.coverage_note || "Bounded unauthenticated scan; completion does not establish full application coverage."}</p>
              {result.web_security_scan.severity_counts && <p className="text-xs mt-2">{Object.entries(result.web_security_scan.severity_counts).map(([risk, count]) => `${risk}: ${count}`).join(" | ")}</p>}

              {result.web_security_scan.ai_advisory && <article className="mt-3 border border-purple-200 bg-purple-50 p-3 text-xs" data-testid="studio-security-ai-advisory">
                <div className="font-bold">AI-assisted triage · {result.web_security_scan.ai_advisory.model_used || "deterministic fallback"}</div>
                <p className="mt-2 whitespace-pre-wrap">{result.web_security_scan.ai_advisory.text}</p>
                <p className="mt-2 text-[10px] text-purple-900">{result.web_security_scan.ai_advisory.note}</p>
              </article>}
              {!result.web_security_scan.findings?.length && <p className="text-xs text-gray-700 mt-2">No alerts were returned within this scan's coverage. This does not establish that the site is secure.</p>}
              <div className="mt-2 space-y-2">
                {result.web_security_scan.findings?.map((finding, index) => <article key={`${finding.scanner_id}-${index}`} className="border border-blue-200 bg-white p-3 text-xs">
                  <div className="flex flex-wrap justify-between gap-2"><strong>{finding.name}</strong><span className="uppercase font-bold">Risk: {finding.risk} · Confidence: {finding.confidence}</span></div>
                  <div className="font-mono text-[10px] break-all mt-1">{finding.method} {finding.url}{finding.parameter ? ` · ${finding.parameter}` : ""}</div>
                  {finding.description && <p className="mt-2 whitespace-pre-wrap">{finding.description}</p>}
                  {finding.evidence && <p className="mt-1 text-gray-600 break-words">Evidence: {finding.evidence}</p>}
                  {finding.remediation && <p className="mt-2"><strong>Recommended fix:</strong> {finding.remediation}</p>}
                  <div className="mt-2 text-[10px] text-gray-500">{result.web_security_scan.scanner?.name} rule {finding.scanner_id}{finding.cwe_id ? ` · CWE ${finding.cwe_id}` : ""}{finding.wasc_id ? ` · WASC ${finding.wasc_id}` : ""}</div>
                </article>)}
              </div>
              <div className="mt-3 text-[10px] text-gray-600">{result.web_security_scan.limitations?.join(" ")}</div>
              {result.web_security_scan.ledger && <div className="mt-2 font-mono text-[10px] text-gray-500">Security scan ledger {result.web_security_scan.ledger.seq} · {result.web_security_scan.ledger.hash}</div>}
            </>}
          </div>}
        </section>}
        {result.source?.target_url && <section className="mx-4 mb-4 border border-purple-300 bg-purple-50 p-4" data-testid="studio-framework-assessment">
          <h3 className="text-xs font-bold uppercase tracking-wider">Functional, API and performance frameworks</h3>
          <p className="text-[11px] text-gray-700 mt-1">Runs a single bounded framework against the exact authorized HTTPS target. Schemathesis generates API cases with Hypothesis. k6 is GET-only, paced, capped at 3 virtual users and 30 seconds. No response bodies or raw tool output are retained.</p>
          <label className="mt-3 block text-xs font-bold">Framework
            <select value={framework} onChange={(event) => { setFramework(event.target.value); setFrameworkAuthorized(false); }} className="mt-1 block w-full border border-gray-300 bg-white px-3 py-2 text-xs">
              <option value="playwright">Playwright browser smoke</option><option value="schemathesis">Schemathesis API contract + Hypothesis cases</option><option value="k6">k6 bounded load smoke (GET only)</option>
            </select>
          </label>
          {framework === "schemathesis" && <div className="mt-2 grid md:grid-cols-2 gap-2">
            <label className="block text-xs font-bold">OpenAPI schema URL<input type="url" required value={openapiUrl} onChange={(event) => setOpenapiUrl(event.target.value)} className="mt-1 w-full border border-gray-300 bg-white px-3 py-2 text-xs font-normal" placeholder="https://staging.example.com/openapi.json" /></label>
            <label className="block text-xs font-bold">Maximum generated examples<input type="number" min="1" max="25" value={maxExamples} onChange={(event) => setMaxExamples(event.target.value)} className="mt-1 block w-full border border-gray-300 bg-white px-3 py-2 text-xs font-normal" /></label>
          </div>}
          {framework === "k6" && <div className="mt-2 grid md:grid-cols-2 gap-2">
            <label className="block text-xs font-bold">Virtual users (1–3)<input type="number" min="1" max="3" value={k6Vus} onChange={(event) => setK6Vus(event.target.value)} className="mt-1 block w-full border border-gray-300 bg-white px-3 py-2 text-xs font-normal" /></label>
            <label className="block text-xs font-bold">Duration seconds (5–30)<input type="number" min="5" max="30" value={k6Duration} onChange={(event) => setK6Duration(event.target.value)} className="mt-1 block w-full border border-gray-300 bg-white px-3 py-2 text-xs font-normal" /></label>
            <label className="block text-xs font-bold">Maximum p95 latency (100–10,000 ms)<input type="number" min="100" max="10000" value={k6P95} onChange={(event) => setK6P95(event.target.value)} className="mt-1 block w-full border border-gray-300 bg-white px-3 py-2 text-xs font-normal" /></label>
            <label className="block text-xs font-bold">Maximum failed request rate (0–10%)<input type="number" min="0" max="10" step="0.1" value={k6ErrorRate} onChange={(event) => setK6ErrorRate(event.target.value)} className="mt-1 block w-full border border-gray-300 bg-white px-3 py-2 text-xs font-normal" /></label>
          </div>}
          <label className="mt-3 flex items-start gap-2 border border-amber-400 bg-amber-50 p-3 text-xs text-amber-950"><input type="checkbox" checked={frameworkAuthorized} onChange={(event) => setFrameworkAuthorized(event.target.checked)} className="mt-0.5" /><span>I confirm owner-approved testing of this exact staging/test target in the recorded scope and time window. I understand Schemathesis may call API methods described in the schema; I have excluded production data and provided a safe test environment.</span></label>
          <button type="button" onClick={() => runFrameworkAssessment.mutate()} disabled={runFrameworkAssessment.isPending || !frameworkAuthorized || (framework === "schemathesis" && !openapiUrl) || ["queued", "running"].includes(result.framework_assessment?.status)} className="mt-3 bg-black text-white px-3 py-2 text-xs font-bold disabled:opacity-50">{runFrameworkAssessment.isPending ? "Queueing…" : `Run ${framework} assessment`}</button>
          {result.framework_assessment && <div className="mt-3 border-t border-purple-200 pt-3 text-xs"><strong>{result.framework_assessment.status.replaceAll("_", " ")} · {result.framework_assessment.framework}</strong>
            {result.framework_assessment.http_statuses?.length > 0 && <p>HTTP status: {result.framework_assessment.http_statuses.join(", ")} · browser exceptions: {result.framework_assessment.page_error_count} · requests observed: {result.framework_assessment.requests_observed}</p>}
            {result.framework_assessment.metrics && <pre className="mt-2 whitespace-pre-wrap text-[10px]">{JSON.stringify(result.framework_assessment.metrics, null, 2)}</pre>}
            {result.framework_assessment.hypothesis && <p className="mt-1">{result.framework_assessment.hypothesis}</p>}
            {result.framework_assessment.error && <p className="text-red-800">{result.framework_assessment.error}</p>}
            {result.framework_assessment.output_sha256 && <p className="font-mono text-[10px]">Output digest: {result.framework_assessment.output_sha256}</p>}
            {result.framework_assessment.limitations && <p className="mt-1 text-[10px] text-gray-600">{result.framework_assessment.limitations.join(" ")}</p>}
            {result.framework_assessment.ledger && <p className="font-mono text-[10px]">Ledger {result.framework_assessment.ledger.seq} · {result.framework_assessment.ledger.hash}</p>}
          </div>}
        </section>}
        {result.requirements?.length > 0 && <div className="px-4 pb-4"><h3 className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Review candidate requirements</h3><div className="max-h-64 overflow-y-auto border border-gray-200">{result.requirements.map((req) => <div key={req.id} className="border-b border-gray-100 p-2 text-xs"><span className="font-mono font-bold mr-2">{req.id}</span>{req.text}<div className="text-[10px] text-gray-400">Source line {req.source_line} · {req.trace_status}</div></div>)}</div></div>}
        <div className="px-4 pb-4">{result.limitations.map((item) => <p key={item} className="text-[10px] text-gray-500">• {item}</p>)}</div>
        {result.source?.github_url && <div className="px-4 pb-4 flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => runRepositoryAudit.mutate()} disabled={runRepositoryAudit.isPending} className="bg-[#FFE600] border border-black px-3 py-2 text-xs font-bold disabled:opacity-50">{runRepositoryAudit.isPending ? "Cloning and scanning source…" : "Run deterministic repository source audit"}</button>
          <Link to={`/repo-audit?url=${encodeURIComponent(result.source.github_url)}`} className="text-xs underline">Open full audit view →</Link>
        </div>}
        {result.repository_audit && <div className="mx-4 mb-4 border border-green-300 bg-green-50 p-3" data-testid="studio-repository-audit-result">
          <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-green-900">Repository scan completed · {result.repository_audit.project_name}</div>
          <div className="text-xs text-green-900 mt-1">{result.repository_audit.finding_summary?.total ?? 0} findings · {result.repository_audit.profile?.code_files_scanned ?? 0} code files · runtime URL was not scanned</div>
          <div className="mt-3 space-y-1">{result.repository_audit.tool_assessments?.map((tool) => <div key={tool.tool_id} className="flex flex-wrap justify-between gap-2 border-t border-green-200 pt-1 text-[10px]">
            <span className="font-semibold">{tool.name}</span><span>{tool.status.replaceAll("_", " ")}{tool.finding_count != null ? ` · ${tool.finding_count} findings` : ""}{tool.exit_code != null ? ` · exit ${tool.exit_code}` : ""}</span>
            {tool.required_prerequisite && <span className="basis-full text-gray-600">Needs: {tool.required_prerequisite}</span>}
            {tool.output_sha256 && <span className="basis-full font-mono text-gray-500">Evidence digest: {tool.output_sha256}</span>}
            {tool.findings?.slice(0, 25).map((finding, findingIndex) => <span key={`${finding.rule_id}-${findingIndex}`} className="basis-full pl-2 text-gray-700">
              {finding.severity || "finding"} · {finding.rule_id || "rule"}{finding.path ? ` · ${finding.path}` : ""}{finding.line ? `:${finding.line}` : ""}{finding.summary ? ` · ${finding.summary}` : ""}
            </span>)}
          </div>)}</div>
          <div className="text-[10px] text-gray-600 mt-1">Project {result.repository_audit.project_id} · reports and gates linked in the main evidence views.</div>
          <div className="text-[10px] text-gray-500 font-mono mt-1">Source audit ledger {result.repository_audit.ledger?.seq} · {result.repository_audit.ledger?.hash}</div>
        </div>}
        {result.ledger && <div className="border-t border-gray-200 px-4 py-2 text-[10px] text-gray-400 font-mono">Ledger entry {result.ledger.seq} · {result.ledger.hash}</div>}
      </section>}

      <section className="mt-8">
        <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Recent assessment plans</div>
        <div className="border border-gray-200 divide-y divide-gray-100">{runs.length ? runs.map((run) => <button key={run.id} type="button" onClick={() => api.get(`/studio/runs/${run.id}`).then((r) => setResult(r.data))} className="w-full text-left p-3 hover:bg-gray-50 flex justify-between gap-4"><span className="text-xs font-bold">{run.name}</span><span className="text-[10px] font-mono text-gray-400">{run.id}</span></button>) : <p className="p-3 text-xs text-gray-400">No studio runs yet.</p>}</div>
      </section>
    </div>
  );
}
