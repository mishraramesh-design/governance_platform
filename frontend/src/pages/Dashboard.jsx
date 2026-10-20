import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ArrowRight, ClipboardCheck, FileSearch, GitBranch, ShieldCheck } from "lucide-react";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";
import { KpiCard } from "../components/KpiCard";
import { SeverityPill } from "../components/StatusPill";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

function DashboardLoading() {
  return (
    <div className="space-y-5 animate-pulse" data-testid="dashboard-loading" aria-label="Loading governance dashboard">
      <div className="h-10 w-64 bg-gray-100" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">{[0, 1, 2, 3].map((i) => <div key={i} className="h-28 border border-gray-200 bg-gray-50" />)}</div>
      <div className="h-64 border border-gray-200 bg-gray-50" />
    </div>
  );
}

function EmptyChart({ message }) {
  return <div className="h-[220px] flex items-center justify-center text-sm text-gray-500 text-center px-6">{message}</div>;
}

export default function Dashboard() {
  const { projectId, currentProject } = useProject();
  const navigate = useNavigate();
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["dashboard", projectId],
    queryFn: () => api.get("/dashboard", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });

  if (!projectId) {
    return <div data-testid="dashboard-no-project"><PageHeader title="Governance Dashboard" subtitle="Choose a project to review its assurance posture." /><div className="border border-gray-200 p-8 text-center"><p className="text-sm text-gray-600">There are no projects selected yet.</p><button onClick={() => navigate("/projects")} className="mt-4 inline-flex items-center gap-2 bg-[#FFE600] border border-black px-4 py-2 text-sm font-bold">Open projects <ArrowRight size={15} /></button></div></div>;
  }
  if (isLoading) return <DashboardLoading />;
  if (isError || !data) {
    return <div data-testid="dashboard-error"><PageHeader title="Governance Dashboard" subtitle="Your project overview could not be loaded." /><div role="alert" className="border border-red-200 bg-red-50 p-5"><p className="font-bold text-red-900">Dashboard data is temporarily unavailable.</p><p className="mt-1 text-sm text-red-800">Check the connection, then try loading the project overview again.</p><button onClick={() => refetch()} className="mt-3 border border-red-800 px-3 py-1.5 text-sm font-bold text-red-900">Retry</button></div></div>;
  }

  const severityData = Object.entries(data.severity_counts || {}).map(([name, value]) => ({ name, value }));
  const verdictData = Object.entries(data.verdict_counts || {}).map(([name, value]) => ({ name: name.replaceAll("_", " "), value }));
  const priorityFindings = data.priority_findings || [];
  const ledgerValid = data.ledger_status?.valid;
  const quickLinks = [
    { label: "Review open findings", detail: `${data.triage_queue_count} awaiting triage`, to: "/findings", icon: FileSearch },
    { label: "Check traceability", detail: `${data.traceability_coverage_pct ?? 0}% requirements coverage`, to: "/traceability", icon: GitBranch },
    { label: "Review gate readiness", detail: "Inspect assurance checkpoints", to: "/gates", icon: ClipboardCheck },
  ];

  return (
    <div data-testid="dashboard-page">
      <PageHeader title="Governance Dashboard" subtitle={currentProject ? `${currentProject.name} · Tier ${currentProject.integrity_tier} · A read-only view of evidence and items for human review.` : "A read-only view of evidence and items for human review."} />

      <section aria-label="Governance metrics" className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-4 mb-6">
        <button onClick={() => navigate("/findings")} className="text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-black"><KpiCard testId="kpi-findings" label="Total Findings" value={data.total_findings} hint="Across all controls · view findings" /></button>
        <button onClick={() => navigate("/findings")} className="text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-black"><KpiCard testId="kpi-triage" label="Triage Queue" value={data.triage_queue_count} hint="Open FAIL findings · review queue" /></button>
        <button onClick={() => navigate("/traceability")} className="text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-black"><KpiCard testId="kpi-coverage" label="Traceability Coverage" value={`${data.traceability_coverage_pct ?? 0}%`} hint="Requirement to test · view matrix" /></button>
        <button onClick={() => navigate("/adjudication")} className="text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-black"><KpiCard testId="kpi-adjudications" label="Pending Adjudications" value={data.pending_adjudications} hint="L2 disagreements · review" /></button>
      </section>

      <section aria-label="Priority review" className="border border-gray-200 mb-6">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-200 px-4 py-3">
          <div><h2 className="font-[Chivo] text-lg font-bold">Priority review</h2><p className="text-xs text-gray-500">Open high and critical findings · evidence for human assessment</p></div>
          <button onClick={() => navigate("/findings")} className="inline-flex items-center gap-1 text-xs font-bold underline underline-offset-4">All findings <ArrowRight size={14} /></button>
        </div>
        {priorityFindings.length ? (
          <ul className="divide-y divide-gray-100">
            {priorityFindings.map((finding) => (
              <li key={finding.id}>
                <button onClick={() => navigate("/findings")} className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-gray-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-inset focus-visible:outline-black">
                  <span className="mt-0.5"><SeverityPill severity={finding.severity} /></span>
                  <span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-gray-900">{finding.control_name || "Control finding"}</span><span className="mt-0.5 block truncate text-xs text-gray-500">{finding.reason || "Open finding requires review."}</span></span>
                  <span className="shrink-0 text-xs text-gray-400">{finding.created_at ? new Date(finding.created_at).toLocaleDateString() : ""}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : <div className="flex items-center gap-3 px-4 py-5 text-sm text-gray-600"><ShieldCheck size={18} className="text-green-700" /><span>No open high or critical findings in this project.</span></div>}
      </section>

      <section aria-label="Next steps" className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-6">
        {quickLinks.map(({ label, detail, to, icon: Icon }) => <button key={to} onClick={() => navigate(to)} className="group flex items-center gap-3 border border-gray-200 p-4 text-left hover:border-black hover:bg-gray-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-black"><span className="flex h-9 w-9 items-center justify-center bg-[#FFF9BD]"><Icon size={18} /></span><span className="min-w-0 flex-1"><span className="block text-sm font-bold">{label}</span><span className="mt-0.5 block text-xs text-gray-500">{detail}</span></span><ArrowRight size={15} className="shrink-0 transition-transform group-hover:translate-x-1" /></button>)}
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <div className="border border-gray-200 p-4 lg:col-span-2">
          <div className="mb-3 flex items-end justify-between gap-3"><div><h2 className="text-xs uppercase tracking-[0.2em] font-bold text-gray-700">Event trend</h2><p className="mt-1 text-xs text-gray-500">Recorded assurance activity by day</p></div><button onClick={() => navigate("/events")} className="text-xs font-bold underline underline-offset-4">View events</button></div>
          {data.trend?.length ? <ResponsiveContainer width="100%" height={220}><LineChart data={data.trend}><CartesianGrid stroke="#EBEBEF" vertical={false} /><XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#888893" /><YAxis tick={{ fontSize: 11 }} stroke="#888893" allowDecimals={false} /><Tooltip contentStyle={{ borderRadius: 0, border: "1px solid #111" }} /><Line type="monotone" dataKey="events" name="Events" stroke="#111111" strokeWidth={2} dot={{ fill: "#FFE600", r: 4, stroke: "#111", strokeWidth: 1 }} /></LineChart></ResponsiveContainer> : <EmptyChart message="No assurance events recorded for this project yet. Start with the event simulator to collect evidence." />}
        </div>
        <div className="border border-gray-200 p-4 flex flex-col">
          <div className="text-xs uppercase tracking-[0.2em] font-bold text-gray-700">Evidence ledger</div>
          <div data-testid="ledger-status-widget" className={`mt-5 flex items-center gap-2 text-xl font-black ${ledgerValid ? "text-green-700" : "text-red-700"}`}><span className={`h-2.5 w-2.5 rounded-full ${ledgerValid ? "bg-green-600" : "bg-red-600"}`} />{ledgerValid ? "Integrity verified" : "Integrity needs review"}</div>
          <div className="mt-1 text-xs text-gray-500">{data.ledger_status?.total_entries ?? 0} chained entries checked</div>
          <p className="mt-4 flex-1 text-xs leading-relaxed text-gray-500">Ledger integrity is a technical check and does not represent project approval.</p>
          <button data-testid="dashboard-view-ledger-btn" onClick={() => navigate("/ledger")} className="mt-4 inline-flex items-center justify-center gap-2 border border-black bg-[#FFE600] px-3 py-2 text-xs font-bold hover:bg-[#F0D800]">Inspect audit trail <ArrowRight size={14} /></button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="border border-gray-200 p-4"><h2 className="text-xs uppercase tracking-[0.2em] font-bold text-gray-700 mb-1">Findings by severity</h2><p className="text-xs text-gray-500 mb-3">Distribution across assessed controls</p>{severityData.length ? <ResponsiveContainer width="100%" height={200}><BarChart data={severityData}><CartesianGrid stroke="#EBEBEF" vertical={false} /><XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="#888893" /><YAxis tick={{ fontSize: 11 }} stroke="#888893" allowDecimals={false} /><Tooltip contentStyle={{ borderRadius: 0, border: "1px solid #111" }} /><Bar dataKey="value" name="Findings" fill="#111111" radius={0} /></BarChart></ResponsiveContainer> : <EmptyChart message="Severity data will appear after findings are recorded." />}</div>
        <div className="border border-gray-200 p-4"><h2 className="text-xs uppercase tracking-[0.2em] font-bold text-gray-700 mb-1">Findings by verdict</h2><p className="text-xs text-gray-500 mb-3">Outcomes from recorded assessments</p>{verdictData.length ? <ResponsiveContainer width="100%" height={200}><BarChart data={verdictData}><CartesianGrid stroke="#EBEBEF" vertical={false} /><XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="#888893" /><YAxis tick={{ fontSize: 11 }} stroke="#888893" allowDecimals={false} /><Tooltip contentStyle={{ borderRadius: 0, border: "1px solid #111" }} /><Bar dataKey="value" name="Findings" fill="#FFE600" radius={0} /></BarChart></ResponsiveContainer> : <EmptyChart message="Verdict data will appear after controls have been assessed." />}</div>
      </div>
    </div>
  );
}
