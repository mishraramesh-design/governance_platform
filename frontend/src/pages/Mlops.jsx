import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import { toast } from "sonner";

const STATE_STYLE = {
  promoted: "bg-green-100 text-green-800 border-l-4 border-green-600",
  shadow: "bg-[#FFE600] text-black",
  candidate: "bg-gray-100 text-gray-700 border-l-4 border-gray-400",
  retired: "bg-gray-200 text-gray-500 line-through",
};
const KIND_LABEL = { prompt: "Prompt packs", model: "Model bindings", rule_pack: "Rule-packs" };

function Bar({ value, danger }) {
  return (
    <div className="h-1.5 bg-gray-100 w-full">
      <div className={`h-1.5 ${danger ? "bg-red-500" : "bg-black"}`} style={{ width: `${Math.round((value || 0) * 100)}%` }} />
    </div>
  );
}

function MetricCard({ label, value, suffix = "%", hint }) {
  return (
    <div className="border border-gray-200 p-3" data-testid={`metric-${label}`}>
      <div className="text-2xl font-[Chivo] font-black text-black">{value}{suffix}</div>
      <div className="text-[10px] uppercase tracking-wider text-gray-400 mt-0.5">{label}</div>
      {hint && <div className="text-[10px] text-gray-400 mt-0.5">{hint}</div>}
    </div>
  );
}

export default function Mlops() {
  const qc = useQueryClient();
  const { data: reg } = useQuery({ queryKey: ["mlops-registry"], queryFn: () => api.get("/mlops/registry").then((r) => r.data) });
  const { data: metrics } = useQuery({ queryKey: ["mlops-metrics"], queryFn: () => api.get("/mlops/metrics").then((r) => r.data), refetchInterval: 8000 });

  const act = async (id, kind, verb) => {
    try {
      const r = await api.post(`/mlops/registry/${id}/${verb}`);
      toast.success(verb === "evaluate" ? `Evaluated · F1 ${r.data.result.f1}` : `${verb} ok`);
      qc.invalidateQueries({ queryKey: ["mlops-registry"] });
      qc.invalidateQueries({ queryKey: ["mlops-metrics"] });
    } catch (e) {
      toast.error(e?.response?.data?.detail || `${verb} failed`);
    }
  };

  const entries = reg?.entries || [];
  const kinds = ["rule_pack", "model", "prompt"];

  return (
    <div data-testid="mlops-page">
      <PageHeader
        title="MLOps · Learning Harness"
        subtitle="Governed registry of prompts, model bindings and detector rule-packs with versions and promotion gates, an evaluation harness (precision / recall / F1 + canary recall + drift), and live governance metrics. Every evaluation and promotion is appended to the audit ledger."
      />

      {metrics && (
        <div className="mb-8">
          <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Live governance metrics</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            <MetricCard label="Zero-LLM share" value={metrics.zero_llm_share} hint="verdicts w/o a model" />
            <MetricCard label="Not-assessed rate" value={metrics.not_assessed_rate} hint="never hidden" />
            <MetricCard label="L1 vs L2 disagreement" value={metrics.l1_l2_disagreement_rate} hint="sent to adjudication" />
            <MetricCard label="Noise ratio" value={metrics.noise_ratio} hint="findings dismissed" />
          </div>
          <div className="border border-gray-200">
            <div className="bg-gray-50 border-b border-gray-200 px-3 py-2 text-[11px] font-bold uppercase tracking-[0.2em] text-gray-500">Detector precision · recall · drift</div>
            <table className="w-full text-sm">
              <thead><tr className="border-b border-gray-200">
                {["Detector", "Precision", "Recall", "F1", "Canary recall", "Precision drift vs baseline"].map((h) => (
                  <th key={h} className="text-left text-[10px] uppercase tracking-wider text-gray-500 font-bold py-2 px-3">{h}</th>
                ))}
              </tr></thead>
              <tbody>
                {metrics.detectors.map((d) => (
                  <tr key={d.detector} data-testid={`detector-metric-${d.detector}`} className="border-b border-gray-100">
                    <td className="py-2 px-3 font-mono text-xs font-bold">{d.detector}</td>
                    <td className="py-2 px-3 w-40"><div className="flex items-center gap-2"><span className="text-xs w-10">{d.precision}</span><Bar value={d.precision} /></div></td>
                    <td className="py-2 px-3 w-40"><div className="flex items-center gap-2"><span className="text-xs w-10">{d.recall}</span><Bar value={d.recall} danger={d.recall < 0.8} /></div></td>
                    <td className="py-2 px-3 text-xs font-bold">{d.f1}</td>
                    <td className="py-2 px-3 text-xs">{d.canary_recall}</td>
                    <td className="py-2 px-3 text-xs">
                      <span className={d.drift_precision >= 0 ? "text-green-700" : "text-red-700"}>
                        {d.drift_precision > 0 ? "+" : ""}{d.drift_precision ?? "—"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between border-b border-gray-200 pb-1 mb-3">
        <h2 className="font-[Chivo] font-bold text-lg">Registry</h2>
        <span className="text-xs text-gray-400">{reg?.summary?.total ?? 0} entries · promotion gate F1 ≥ {reg?.promotion_threshold}</span>
      </div>

      {kinds.map((kind) => {
        const items = entries.filter((e) => e.kind === kind);
        if (!items.length) return null;
        return (
          <div key={kind} className="mb-6">
            <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">{KIND_LABEL[kind]} ({items.length})</div>
            <div className="overflow-x-auto border border-gray-200">
              <table className="w-full text-sm">
                <thead><tr className="bg-gray-50 border-b border-gray-300">
                  {["Ref", "Name", "Ver", "State", "Latest F1", "Actions"].map((h) => (
                    <th key={h} className="text-left text-[10px] uppercase tracking-wider text-gray-600 font-bold py-2 px-3">{h}</th>
                  ))}
                </tr></thead>
                <tbody>
                  {items.map((e) => (
                    <tr key={e.id} data-testid={`registry-row-${e.ref}`} className="hover:bg-gray-50 border-b border-gray-100">
                      <td className="py-1.5 px-3 font-mono text-xs font-bold">{e.ref}</td>
                      <td className="py-1.5 px-3 text-xs">{e.name}</td>
                      <td className="py-1.5 px-3 text-xs">v{e.version}</td>
                      <td className="py-1.5 px-3"><span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 ${STATE_STYLE[e.state] || ""}`}>{e.state}</span></td>
                      <td className="py-1.5 px-3 text-xs">{e.latest_eval ? e.latest_eval.f1 : "—"}</td>
                      <td className="py-1.5 px-3">
                        <div className="flex gap-1">
                          {kind === "rule_pack" && (
                            <button data-testid={`eval-btn-${e.ref}`} onClick={() => act(e.id, kind, "evaluate")} className="text-[10px] uppercase font-bold border border-gray-400 px-2 py-0.5 hover:border-black">Evaluate</button>
                          )}
                          <button data-testid={`shadow-btn-${e.ref}`} onClick={() => act(e.id, kind, "shadow")} className="text-[10px] uppercase font-bold border border-gray-400 px-2 py-0.5 hover:border-black">Shadow</button>
                          <button data-testid={`promote-btn-${e.ref}`} onClick={() => act(e.id, kind, "promote")} className="text-[10px] uppercase font-bold border border-black px-2 py-0.5 hover:bg-black hover:text-[#FFE600]">Promote</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
