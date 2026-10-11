import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";
import { VerdictPill } from "../components/StatusPill";

const SAMPLE_LOG = `2026-10-11 09:12:01 INFO login attempt user=asha.verma password=Sup3rSecret!
2026-10-11 09:12:02 INFO request took 1450ms for /api/orders
2026-10-11 09:12:05 ERROR Traceback: NullPointerException in OrderService
2026-10-11 09:12:08 INFO customer aadhaar 234567890123 verified`;

export default function Runtime() {
  const { projectId } = useProject();
  const [logText, setLogText] = useState(SAMPLE_LOG);
  const [result, setResult] = useState(null);

  const analyze = useMutation({
    mutationFn: () => api.post("/runtime/analyze", { project_id: projectId, log_text: logText }),
    onSuccess: (res) => {
      setResult(res.data);
      toast.success("Runtime log analyzed");
    },
  });

  return (
    <div data-testid="runtime-page">
      <PageHeader title="Runtime Assurance" subtitle="Simulated production log analysis - Security, Performance and Quality findings, with log-to-source tracing back to build-time findings." />

      <div className="mb-4">
        <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Log Text</label>
        <textarea data-testid="runtime-log-textarea" value={logText} onChange={(e) => setLogText(e.target.value)} rows={6} className="w-full border border-gray-300 p-3 text-xs font-mono" />
      </div>
      <button data-testid="analyze-log-btn" onClick={() => analyze.mutate()} disabled={analyze.isPending} className="bg-[#FFE600] text-black hover:bg-[#F0D800] font-bold tracking-tight rounded-none px-4 py-2 text-xs border border-black transition-colors duration-100 disabled:opacity-50 mb-8">
        {analyze.isPending ? "Analyzing…" : "Analyze Log"}
      </button>

      {result && (
        <div data-testid="runtime-result" className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {["security", "performance", "quality"].map((k) => (
            <div key={k} className="border border-gray-200 p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] uppercase tracking-wider font-bold text-gray-500">{k}</span>
                <VerdictPill verdict={result[k].verdict === "PASS" ? "PASS" : "FAIL"} />
              </div>
              {k === "security" && (
                <div className="space-y-1 text-xs">
                  {result.security.findings.map((f, i) => <div key={i} className="font-mono">{f.type}: {f.masked}</div>)}
                  {!result.security.findings.length && <div className="text-gray-400 italic">No leaks detected.</div>}
                </div>
              )}
              {k === "performance" && <div className="text-xs">Slow calls (&gt;1000ms): {result.performance.slow_calls_over_1000ms.join(", ") || "none"}</div>}
              {k === "quality" && <div className="text-xs">Error/Exception lines: {result.quality.error_line_count}</div>}
            </div>
          ))}
          <div className="md:col-span-3 border border-gray-200 p-4">
            <div className="text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-2">Log-to-Source Tracing</div>
            {result.log_to_source_tracing.length ? (
              result.log_to_source_tracing.map((t, i) => (
                <div key={i} className="text-xs font-mono">{t.log_hash} → finding {t.traced_to_finding_id} ({t.control_name})</div>
              ))
            ) : (
              <div className="text-xs text-gray-400 italic">No matches against existing build-time evidence.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
