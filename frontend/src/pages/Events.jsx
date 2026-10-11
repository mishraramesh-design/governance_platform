import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";
import { VerdictPill, SeverityPill } from "../components/StatusPill";

const EVENT_TYPES = [
  { value: "requirements_submitted", label: "Requirements Submitted", needsSource: false },
  { value: "commit_pushed", label: "Commit Pushed", needsSource: "commit" },
  { value: "test_uploaded", label: "Test Uploaded", needsSource: false },
  { value: "release_candidate", label: "Release Candidate", needsSource: false },
];

export default function Events() {
  const { projectId } = useProject();
  const qc = useQueryClient();
  const [eventType, setEventType] = useState("commit_pushed");
  const [sourceRef, setSourceRef] = useState("");
  const [lastResult, setLastResult] = useState(null);

  const { data: commits } = useQuery({
    queryKey: ["commits", projectId],
    queryFn: () => api.get("/commits", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });

  const { data: events } = useQuery({
    queryKey: ["events", projectId],
    queryFn: () => api.get("/events", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });

  const simulate = useMutation({
    mutationFn: () => api.post("/events/simulate", { project_id: projectId, event_type: eventType, source_ref: sourceRef || null }),
    onSuccess: (res) => {
      setLastResult(res.data);
      toast.success(`Event simulated - ${res.data.findings.length} finding(s) generated`);
      qc.invalidateQueries({ queryKey: ["events", projectId] });
      qc.invalidateQueries({ queryKey: ["dashboard", projectId] });
      qc.invalidateQueries({ queryKey: ["findings"] });
      qc.invalidateQueries({ queryKey: ["reports"] });
    },
    onError: () => toast.error("Event simulation failed"),
  });

  const needsSource = EVENT_TYPES.find((e) => e.value === eventType)?.needsSource;

  return (
    <div data-testid="events-page">
      <PageHeader title="Event Simulator" subtitle="Simulate an SDLC event to trigger its mapped controls, run Level-2 review where applicable, chain results into the ledger, and generate two reports." />

      <div className="border border-gray-200 p-5 mb-6 flex flex-wrap items-end gap-4">
        <div>
          <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Event Type</label>
          <select
            data-testid="event-type-select"
            value={eventType}
            onChange={(e) => {
              setEventType(e.target.value);
              setSourceRef("");
            }}
            className="border border-gray-300 px-3 py-2 text-sm rounded-none focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
          >
            {EVENT_TYPES.map((e) => (
              <option key={e.value} value={e.value}>{e.label}</option>
            ))}
          </select>
        </div>
        {needsSource === "commit" && (
          <div>
            <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Commit</label>
            <select
              data-testid="commit-select"
              value={sourceRef}
              onChange={(e) => setSourceRef(e.target.value)}
              className="border border-gray-300 px-3 py-2 text-sm rounded-none focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
            >
              <option value="">Select commit…</option>
              {commits?.map((c) => (
                <option key={c.id} value={c.id}>{c.commit_id} - {c.author} - {c.message}</option>
              ))}
            </select>
          </div>
        )}
        <button
          data-testid="simulate-event-btn"
          onClick={() => simulate.mutate()}
          disabled={simulate.isPending || (needsSource === "commit" && !sourceRef)}
          className="bg-[#FFE600] text-black hover:bg-[#F0D800] font-bold tracking-tight rounded-none px-4 py-2 text-xs border border-black transition-colors duration-100 disabled:opacity-50"
        >
          {simulate.isPending ? "Simulating…" : "Simulate Event"}
        </button>
      </div>

      {lastResult && (
        <div data-testid="simulate-result-panel" className="border border-black p-5 mb-6 bg-gray-50">
          <div className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">Latest Run - {lastResult.findings.length} finding(s)</div>
          <div className="space-y-2">
            {lastResult.findings.map((f) => (
              <div key={f.id} className="flex items-center justify-between bg-white border border-gray-200 px-3 py-2">
                <div className="text-sm">
                  <span className="font-mono text-xs font-bold mr-2">{f.control_id}</span>
                  {f.control_name}
                </div>
                <div className="flex items-center gap-2">
                  <SeverityPill severity={f.severity} />
                  <VerdictPill verdict={f.verdict} />
                </div>
              </div>
            ))}
          </div>
          <div className="text-xs text-gray-500 mt-3">Two reports generated - see the Reports page.</div>
        </div>
      )}

      <div>
        <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Event History</div>
        <div className="overflow-x-auto border border-gray-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-y border-gray-300">
                {["Timestamp", "Type", "Triggered By", "Controls Triggered"].map((h) => (
                  <th key={h} className="text-left text-xs uppercase tracking-wider text-gray-600 font-bold py-2 px-3">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events?.map((e) => (
                <tr key={e.id} data-testid={`event-row-${e.id}`} className="hover:bg-gray-50 transition-colors duration-100">
                  <td className="border-b border-gray-200 py-2 px-3 font-mono text-xs">{e.created_at.slice(0, 19)}</td>
                  <td className="border-b border-gray-200 py-2 px-3 font-semibold">{e.event_type}</td>
                  <td className="border-b border-gray-200 py-2 px-3 text-gray-600">{e.triggered_by}</td>
                  <td className="border-b border-gray-200 py-2 px-3 text-xs text-gray-500">{e.controls_triggered.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
