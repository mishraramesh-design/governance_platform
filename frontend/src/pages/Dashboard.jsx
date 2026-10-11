import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";
import { KpiCard } from "../components/KpiCard";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

export default function Dashboard() {
  const { projectId } = useProject();
  const navigate = useNavigate();
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard", projectId],
    queryFn: () => api.get("/dashboard", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });

  if (isLoading || !data) {
    return <div className="text-sm text-gray-400" data-testid="dashboard-loading">Loading dashboard…</div>;
  }

  const severityData = Object.entries(data.severity_counts || {}).map(([k, v]) => ({ name: k, value: v }));
  const verdictData = Object.entries(data.verdict_counts || {}).map(([k, v]) => ({ name: k, value: v }));

  return (
    <div data-testid="dashboard-page">
      <PageHeader title="Governance Dashboard" subtitle="Observe, collect evidence, advise. Nothing on this page approves or rejects anything - humans decide." />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-4 mb-8">
        <KpiCard testId="kpi-findings" label="Total Findings" value={data.total_findings} hint="Across all controls" />
        <KpiCard testId="kpi-triage" label="Triage Queue" value={data.triage_queue_count} hint="Open FAIL findings" />
        <KpiCard testId="kpi-coverage" label="Traceability Coverage" value={`${data.traceability_coverage_pct ?? 0}%`} hint="Req → Design → Commit → Test" />
        <KpiCard testId="kpi-adjudications" label="Pending Adjudications" value={data.pending_adjudications} hint="L2 disagreements" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-8">
        <div className="border border-gray-200 p-4 lg:col-span-2">
          <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-3">Event Trend</div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data.trend}>
              <CartesianGrid stroke="#EBEBEF" vertical={false} />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="#888893" />
              <YAxis tick={{ fontSize: 11 }} stroke="#888893" allowDecimals={false} />
              <Tooltip contentStyle={{ borderRadius: 0, border: "1px solid #111" }} />
              <Line type="linear" dataKey="events" stroke="#111111" strokeWidth={2} dot={{ fill: "#FFE600", r: 4, stroke: "#111", strokeWidth: 1 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="border border-gray-200 p-4">
          <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-3">Ledger Status</div>
          <div data-testid="ledger-status-widget" className={`text-2xl font-black mb-1 ${data.ledger_status.valid ? "text-green-700" : "text-red-700"}`}>
            {data.ledger_status.valid ? "VALID" : "BROKEN"}
          </div>
          <div className="text-xs text-gray-500">{data.ledger_status.total_entries} chained entries</div>
          <button
            data-testid="dashboard-view-ledger-btn"
            onClick={() => navigate("/ledger")}
            className="mt-4 bg-[#FFE600] text-black hover:bg-[#F0D800] font-bold tracking-tight rounded-none px-3 py-1.5 text-xs border border-black transition-colors duration-100"
          >
            View Full Ledger
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="border border-gray-200 p-4">
          <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-3">Findings by Severity</div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={severityData}>
              <CartesianGrid stroke="#EBEBEF" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="#888893" />
              <YAxis tick={{ fontSize: 11 }} stroke="#888893" allowDecimals={false} />
              <Tooltip contentStyle={{ borderRadius: 0, border: "1px solid #111" }} />
              <Bar dataKey="value" fill="#111111" radius={0} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="border border-gray-200 p-4">
          <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-3">Findings by Verdict</div>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={verdictData}>
              <CartesianGrid stroke="#EBEBEF" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} stroke="#888893" />
              <YAxis tick={{ fontSize: 11 }} stroke="#888893" allowDecimals={false} />
              <Tooltip contentStyle={{ borderRadius: 0, border: "1px solid #111" }} />
              <Bar dataKey="value" fill="#FFE600" radius={0} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
